"""Bundle the light-rail and tram lines of a city onto shared centre lines and order them.

    python3 scripts/line_bundles.py <country> <city> [out.png]

A prototype after the method of Brosi and Bast, "Large-Scale Generation of Transit Maps from
OpenStreetMap Data", The Cartographic Journal 2024 (CC BY 4.0; no code of theirs is used):

1. Support graph. Every line is sampled every STEP metres; a sample within MERGE metres of an
   existing node joins it (the node moves to the mean of its samples), otherwise it becomes a new
   node. Consecutive samples give edges labelled with the lines that use them. The last few nodes
   of the line being inserted are blocked, so a line does not merge with itself. Two rounds, the
   second fed with the first's edges. Nodes of degree 2 whose two edges carry the same lines are
   then contracted, leaving one centre line per stretch of shared track.
2. Line order. On every edge the lines get a left-to-right order. Lines may cross only at nodes;
   the cost of an ordering is CROSS for every pair of lines that cross at a node plus SPLIT for
   every pair that run side by side on one edge and stop being neighbours on the next while still
   together. Greedy start, then simulated annealing over swaps of neighbours on one edge.
3. Drawing (for the comparison picture only). Each line is offset from its edge's centre line by
   its place in the order; at a node it is joined to its next edge by a curve.

The input is data/<country>_metro.geojson as the pipeline writes it; nothing is changed there.
"""
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[1]
STEP = 5.0          # m between samples
MERGE = 22.0        # m: samples nearer than this to a node join it (the two tracks of a street, a shared stop)
CROSS, SPLIT = 4.0, 1.0
SPACING, TRIM = 14.0, 40.0   # m, for the comparison picture: about 2 px apart at z13


class Projection:
    def __init__(self, lon0, lat0):
        self.lon0, self.lat0, self.kx, self.ky = lon0, lat0, 111320 * math.cos(math.radians(lat0)), 110540

    def __call__(self, lon, lat):
        return ((lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky)

    def back(self, x, y):
        return (self.lon0 + x / self.kx, self.lat0 + y / self.ky)


def samples(co, step=STEP):
    out = [co[0]]
    for (x0, y0), (x1, y1) in zip(co, co[1:]):
        d = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(d // step))
        out.extend((x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(1, n + 1))
    return out


class Network:
    """Centre lines built line by line. A new line follows the network wherever it runs within
    MERGE metres of it and roughly parallel (so a crossing at right angles is not a shared
    stretch); elsewhere it adds its own course as new edges, joined to the network where the
    shared stretches begin and end."""

    def __init__(self, source_bound=False):
        self.source_bound = source_bound
        self.source_audit = {"corridor_rejections": 0, "coverage_rejections": 0}
        self.node = {}                         # id -> (x, y)
        self.edge = {}                         # id -> {"co": [(x, y)], "u", "v", "lines": set}
        self.next_id = 0

    def new_node(self, pt):
        self.next_id += 1
        self.node[self.next_id] = tuple(pt)
        return self.next_id

    def new_edge(self, co, u, v, lines):
        self.next_id += 1
        self.edge[self.next_id] = {"co": [tuple(c) for c in co], "u": u, "v": v, "lines": set(lines)}
        return self.next_id

    def tree(self):
        ids = list(self.edge)
        return ids, [LineString(self.edge[i]["co"]) for i in ids]

    def split_at(self, pt, snap=None):
        """The node at a point on the network, splitting the edge there if need be."""
        from shapely.geometry import Point
        from shapely.ops import substring
        p = Point(pt)
        best, best_d = None, 1.0
        for i, e in self.edge.items():
            d = LineString(e["co"]).distance(p)
            if d < best_d:
                best, best_d = i, d
        if best is None:
            return None
        e = self.edge[best]
        line = LineString(e["co"])
        t = line.project(p)
        snap = SNAP if snap is None else snap
        if line.length <= 2 * snap:              # a short stretch: its nearer end
            return e["u"] if t <= line.length / 2 else e["v"]
        if t <= snap:
            return e["u"]
        if t >= line.length - snap:
            return e["v"]
        n = self.new_node(line.interpolate(t).coords[0])
        a, b = substring(line, 0, t), substring(line, t, line.length)
        del self.edge[best]
        self.new_edge(list(a.coords), e["u"], n, e["lines"])
        self.new_edge(list(b.coords), n, e["v"], e["lines"])
        return n

    def path(self, a, b, corridor=None):
        import heapq
        adj = defaultdict(list)
        for i, e in self.edge.items():
            geom = LineString(e["co"])
            if corridor is not None and not geom.covered_by(corridor):
                continue
            w = geom.length
            adj[e["u"]].append((e["v"], i, w)); adj[e["v"]].append((e["u"], i, w))
        dist, prev, heap = {a: 0.0}, {}, [(0.0, a)]
        while heap:
            d, x = heapq.heappop(heap)
            if x == b:
                break
            if d > dist.get(x, 1e18):
                continue
            for y, i, w in adj[x]:
                if d + w < dist.get(y, 1e18):
                    dist[y], prev[y] = d + w, (x, i)
                    heapq.heappush(heap, (d + w, y))
        if b not in dist:
            return None, None
        edges, x = [], b
        while x != a:
            x, i = prev[x]
            edges.append(i)
        return edges, dist[b]

    def insert(self, co, line):
        from shapely import STRtree
        from shapely.geometry import Point
        pts = samples(co)
        if len(pts) < 2:
            return
        matched = [None] * len(pts)
        if self.edge:
            ids, geoms = self.tree()
            tree = STRtree(geoms)
            for k, pt in enumerate(pts):
                a, b = pts[max(0, k - 2)], pts[min(len(pts) - 1, k + 2)]
                hits = tree.query(Point(pt).buffer(MERGE))
                best, best_d = None, MERGE
                for h in hits:
                    g = geoms[h]
                    d = g.distance(Point(pt))
                    if d >= best_d:
                        continue
                    t = g.project(Point(pt))
                    q0, q1 = g.interpolate(max(0, t - 8)), g.interpolate(min(g.length, t + 8))
                    ux, uy = q1.x - q0.x, q1.y - q0.y
                    vx, vy = b[0] - a[0], b[1] - a[1]
                    nu, nv = math.hypot(ux, uy), math.hypot(vx, vy)
                    if nu and nv and abs(ux * vx + uy * vy) / (nu * nv) > math.cos(math.radians(35)):
                        best, best_d = g.interpolate(t).coords[0], d
                matched[k] = best
        # runs of matched samples; shorter than MIN_SHARED is a crossing, not a shared stretch
        runs, k = [], 0
        while k < len(pts):
            j = k
            while j + 1 < len(pts) and (matched[j + 1] is None) == (matched[k] is None):
                j += 1
            runs.append([matched[k] is not None, k, j])
            k = j + 1
        for r in runs:
            if r[0] and (r[2] - r[1]) * STEP < MIN_SHARED:
                r[0] = False
        merged = []
        for r in runs:
            if merged and merged[-1][0] == r[0]:
                merged[-1][2] = r[2]
            else:
                merged.append(r)
        attach = None                           # node where the line last left the network
        for idx, (on, a, b) in enumerate(merged):
            if on:
                n0, n1 = self.split_at(matched[a]), self.split_at(matched[b])
                source_run = LineString(pts[a:b+1])
                corridor = source_run.buffer(MERGE+SNAP+1e-6) if self.source_bound else None
                route, length = (self.path(n0, n1, corridor) if n0 and n1 and n0 != n1 else (None, None))
                if self.source_bound and not route and n0 and n1 and n0 != n1:
                    self.source_audit['corridor_rejections'] += 1
                if route and self.source_bound:
                    from shapely.ops import unary_union
                    reused = unary_union([LineString(self.edge[i]['co']) for i in route])
                    if not source_run.covered_by(reused.buffer(MERGE+SNAP+1e-6)):
                        self.source_audit['coverage_rejections'] += 1
                        route = None
                if route and length < 1.4 * (b - a) * STEP + 60:
                    for i in route:
                        self.edge[i]["lines"].add(line)
                    if attach is not None and attach != n0:
                        self.new_edge([self.node[attach], self.node[n0]], attach, n0, [line])
                    attach = n1
                    continue
            own = pts[a:b + 1]
            u = attach if attach is not None else self.new_node(own[0])
            last = idx == len(merged) - 1
            if last:
                v = self.new_node(own[-1])
            else:
                nxt = merged[idx + 1]
                v = self.split_at(matched[nxt[1]]) if nxt[0] and matched[nxt[1]] else None
                v = v or self.new_node(own[-1])
            # leave and join the centre line smoothly: the line's own track near a node it shares
            # with other lines is left out, so the line turns away from the node, not across the bundle
            inner = [q for q in own[1:-1]
                     if (attach is None or math.dist(q, self.node[u]) > CROP)
                     and (last or math.dist(q, self.node[v]) > CROP)]
            co2 = [self.node[u]] + inner + [self.node[v]]
            # A source run can leave a bundle and return to the same junction.
            # Its equal endpoint IDs do not make a kilometre-long loop empty.
            # Match close_short's existing small-loop limit, while retaining
            # the actual sampled source course and both source_bound checks.
            # A loop with next to no width that stays at the node is no loop (thin_loop): the
            # line passed the junction a few metres off it and both ends were snapped to that one
            # node (Munich Karlsplatz, 2026-10-22: 65 m long, 0.6 m wide on average, never 21 m
            # from the node, drawn as a knot of trams 19, N19 and 21).
            if u != v or LineString(co2).length >= 2 * SHORT and not thin_loop(co2):
                self.new_edge(co2, u, v, [line])
            attach = v


MIN_SHARED = 40.0   # m: a shorter run along the network is a crossing or a touch, not shared track
SNAP = 25.0         # m: a line joining or leaving the centre line within this of a node uses that node
CROP = 30.0         # m: a line's own track this near a node where it meets other lines is not drawn
SHORT = 30.0        # m: stretches shorter than this are closed up into one node
THIN = 5.0          # m: a loop narrower than this on average runs out and back on itself


def thin_loop(co):
    """A closed course from its node co[0] that is no loop: never further than CROP from the node
    (where a line's own track is not drawn anyway) and under THIN wide on average (enclosed area
    over half its length). A line that passed a junction a few metres off it, both ends snapped to
    the junction's node. A longer out-and-back, a branch drawn on both of its tracks (Basel 8,
    Antwerp 12), is the line's own course and stays."""
    from shapely.geometry import Polygon
    if len(co) < 4:
        return True
    if max(math.dist(co[0], c) for c in co) > CROP:
        return False
    area = Polygon(co).buffer(0).area
    return area / (LineString(co).length / 2) < THIN


def build(paths, *, source_bound=False):
    """paths: [(coords in metres, frozenset of one line)], inserted longest first."""
    net = Network(source_bound=source_bound)
    for co, lines in sorted(paths, key=lambda p: -LineString(p[0]).length if len(p[0]) > 1 else 0):
        (line,) = lines
        if len(co) > 1:
            net.insert(co, line)
    close_short(net)
    return net


def close_short(net):
    """Close up stretches shorter than SHORT: their two nodes become one, at the midpoint, and the
    stretches meeting there end at it. Several nodes a few metres apart at one junction would
    otherwise leave the page no room to ease a line from one place to another."""
    while True:
        short = sorted((LineString(e["co"]).length, i) for i, e in net.edge.items() if e["u"] != e["v"])
        short = [(length, i) for length, i in short if length < SHORT]
        if net.source_bound:
            degree = defaultdict(int)
            for edge in net.edge.values():
                degree[edge["u"]] += 1
                degree[edge["v"]] += 1
            # An isolated source piece has no junction to close. Removing its
            # only edge loses both genuine ends, however short that piece is.
            short = [(length, i) for length, i in short
                     if not (degree[net.edge[i]["u"]] == degree[net.edge[i]["v"]] == 1)]
        if not short:
            break
        _, i = short[0]
        e = net.edge.pop(i)
        u, v = e["u"], e["v"]
        mid = ((net.node[u][0] + net.node[v][0]) / 2, (net.node[u][1] + net.node[v][1]) / 2)
        net.node[u] = mid
        for j, f in list(net.edge.items()):
            if v in (f["u"], f["v"]) or u in (f["u"], f["v"]):
                if f["u"] == v:
                    f["u"] = u
                if f["v"] == v:
                    f["v"] = u
                co = list(f["co"])
                if f["u"] == u:
                    co[0] = mid
                if f["v"] == u:
                    co[-1] = mid
                f["co"] = co
                if f["u"] == f["v"] and (LineString(co).length < 2 * SHORT or thin_loop(co)):
                    del net.edge[j]                        # a small or thin loop left by closing up a triangle
        del net.node[v]


def contract(g):
    """Edges as polylines between nodes that are junctions, ends, or where the lines change."""
    adj = defaultdict(list)
    for i, e in g.edge.items():
        adj[e["u"]].append(i); adj[e["v"]].append(i)
    keep = {v for v, es in adj.items() if len(es) != 2 or g.edge[es[0]]["lines"] != g.edge[es[1]]["lines"]}
    seen, out = set(), []
    for start in sorted(adj):
        if start not in keep:
            continue
        for i in adj[start]:
            if i in seen:
                continue
            co, node, nodes = [], start, [start]
            cur = i
            while True:
                seen.add(cur)
                e = g.edge[cur]
                seg = e["co"] if e["u"] == node else e["co"][::-1]
                co.extend(seg if not co else seg[1:])
                node = e["v"] if e["u"] == node else e["u"]
                nodes.append(node)
                if node in keep:
                    break
                cur = next(x for x in adj[node] if x != cur)
            # several stretches, each too long for close_short, can make up a thin loop at a node
            # as well (Halle Marktplatz, Tram 5, 2026-10-22: 77 m, never 27 m from the node)
            if node == start and thin_loop(co):
                continue
            out.append({"co": co, "u": start, "v": node, "lines": sorted(g.edge[i]["lines"])})
    # rings with no kept node
    for i, e in g.edge.items():
        if i not in seen:
            seen.add(i)
            out.append({"co": e["co"], "u": e["u"], "v": e["v"], "lines": sorted(e["lines"])})
    return out


def outward(g, edge, node):
    """Unit direction of an edge leaving a node, over its first ~30 m."""
    pts = edge["co"] if edge["u"] == node else edge["co"][::-1]
    x0, y0 = pts[0]
    for x, y in pts[1:]:
        if math.hypot(x - x0, y - y0) >= 30:
            break
    d = math.hypot(x - x0, y - y0) or 1
    return ((x - x0) / d, (y - y0) / d)


class Order:
    def __init__(self, g, edges):
        self.g, self.edges = g, edges
        self.at = defaultdict(list)            # node -> [edge index]
        for i, e in enumerate(edges):
            self.at[e["u"]].append(i)
            if e["v"] != e["u"]:
                self.at[e["v"]].append(i)
        self.angle = {}
        for v, es in self.at.items():
            for i in es:
                dx, dy = outward(g, edges[i], v)
                self.angle[(v, i)] = math.atan2(dy, dx)
        self.order = [list(e["lines"]) for e in edges]
        # where each line goes on at each node: the straightest other edge that carries it
        self.next = {}
        for v, es in self.at.items():
            for i in es:
                for line in edges[i]["lines"]:
                    others = [j for j in es if j != i and line in edges[j]["lines"]]
                    if others:
                        a = self.angle[(v, i)]
                        self.next[(v, i, line)] = max(others, key=lambda j: abs(math.remainder(self.angle[(v, j)] - a, 2 * math.pi)))

    def out_pos(self, i, v):
        """Each line's place on edge i, counted left to right as seen from node v looking along it."""
        o = self.order[i] if self.edges[i]["u"] == v else self.order[i][::-1]
        return {line: k for k, line in enumerate(o)}

    def node_cost(self, v):
        cost = 0.0
        pos = {i: self.out_pos(i, v) for i in self.at[v]}
        for i in self.at[v]:
            lines = self.order[i]
            for a_i in range(len(lines)):
                for b_i in range(a_i + 1, len(lines)):
                    a, b = lines[a_i], lines[b_i]
                    fa, fb = self.next.get((v, i, a)), self.next.get((v, i, b))
                    if fa is None or fb is None:
                        continue
                    left = pos[i][a] < pos[i][b]
                    if fa == fb:
                        if left == (pos[fa][a] < pos[fa][b]):
                            cost += CROSS
                        elif abs(pos[i][a] - pos[i][b]) == 1 and abs(pos[fa][a] - pos[fa][b]) != 1:
                            cost += SPLIT
                    else:
                        # f later than g counter-clockwise from i means f lies to the right
                        base = self.angle[(v, i)]
                        ccw = lambda j: (self.angle[(v, j)] - base) % (2 * math.pi)
                        a_right = ccw(fa) > ccw(fb)
                        if a_right == left:
                            cost += CROSS
        return cost / 2                                     # every pair is seen from both of its edges

    def total(self):
        return sum(self.node_cost(v) for v in self.at)

    def anneal(self, rounds=60000, seed=1):
        rng = random.Random(seed)
        movable = [i for i, o in enumerate(self.order) if len(o) > 1]
        if not movable:
            return 0.0
        cost = self.total()
        best, best_cost = [list(o) for o in self.order], cost
        for it in range(1, rounds + 1):
            t = 1.0 / it * 1000
            i = rng.choice(movable)
            k = rng.randrange(len(self.order[i]) - 1)
            ends = {self.edges[i]["u"], self.edges[i]["v"]}
            before = sum(self.node_cost(v) for v in ends)
            o = self.order[i]
            o[k], o[k + 1] = o[k + 1], o[k]
            delta = sum(self.node_cost(v) for v in ends) - before
            if delta <= 0 or rng.random() < math.exp(-delta / t):
                cost += delta
                if cost < best_cost:
                    best, best_cost = [list(x) for x in self.order], cost
            else:
                o[k], o[k + 1] = o[k + 1], o[k]
        self.order = best
        return best_cost


def drawn(g, edges, order, spacing, trim):
    """Offset polylines per (edge, line), and curves joining a line's edges at nodes."""
    parts = defaultdict(list)                  # line -> list of polylines
    ends = {}                                  # (edge, line, node) -> (point, direction into the node)
    for i, e in enumerate(edges):
        base = LineString(e["co"])
        if base.length < 2 * trim + 1:
            inner = base
        else:
            from shapely.ops import substring
            inner = substring(base, trim, base.length - trim)
        n = len(order.order[i])
        for k, line in enumerate(order.order[i]):
            off = ((n - 1) / 2 - k) * spacing            # left of u -> v is positive
            seg = inner.offset_curve(off) if off else inner
            if seg.is_empty or seg.geom_type != "LineString" or len(seg.coords) < 2:
                continue
            pts = list(seg.coords)
            parts[line].append(pts)
            ends[(i, line, e["u"])] = (pts[0], (pts[0][0] - pts[1][0], pts[0][1] - pts[1][1]))
            ends[(i, line, e["v"])] = (pts[-1], (pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]))
    joins = defaultdict(list)
    for (v, i, line), j in order.next.items():
        if i > j or (i, line, v) not in ends or (j, line, v) not in ends:
            continue
        (p, dp), (q, dq) = ends[(i, line, v)], ends[(j, line, v)]
        lp, lq = math.hypot(*dp) or 1, math.hypot(*dq) or 1
        k = math.hypot(q[0] - p[0], q[1] - p[1]) * 0.4
        c1 = (p[0] + dp[0] / lp * k, p[1] + dp[1] / lp * k)
        c2 = (q[0] + dq[0] / lq * k, q[1] + dq[1] / lq * k)
        curve = [((1 - t) ** 3 * p[0] + 3 * (1 - t) ** 2 * t * c1[0] + 3 * (1 - t) * t * t * c2[0] + t ** 3 * q[0],
                  (1 - t) ** 3 * p[1] + 3 * (1 - t) ** 2 * t * c1[1] + 3 * (1 - t) * t * t * c2[1] + t ** 3 * q[1])
                 for t in (s / 12 for s in range(13))]
        joins[line].append(curve)
    return parts, joins


def load(code, city):
    fc = json.loads((ROOT / "data" / f"{code}_metro.geojson").read_text())
    feats = [f for f in fc["features"] if f["properties"].get("ct") == city and f["properties"].get("jk") == "urban"]
    lons = [c[0] for f in feats for part in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]]) for c in part]
    lats = [c[1] for f in feats for part in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]]) for c in part]
    proj = Projection(sum(lons) / len(lons), sum(lats) / len(lats))
    colour, paths = {}, []
    for f in feats:
        p = f["properties"]
        key = f"{p.get('network', '')}|{p['n']}|{p.get('rid', '')}"
        colour[key] = p.get("col", "#5cc8ff")
        for part in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]]):
            paths.append(([proj(*c) for c in part], frozenset([key])))
    return proj, colour, paths, feats


DROP = ("off", "goff", "sh", "soff", "bn", "op", "ap", "lead")


def apply(features, code, cities, *, source=None, endpoint_cities=(), endpoint_audit=None, context_sink=None,
          geographic_cities=(), source_bound_cities=(), source_bound_identities=()):
    """The pipeline's step: the light-rail and tram lines of each named city are written again
    along the shared centre lines, one feature per stretch, each with its place there (property
    off, in steps right of the stretch's direction; bn, how many lines share it). The page joins a
    line's stretches at their common ends and eases between places. Other features are unchanged.
    geographic_cities optionally batches actual near geometry across the specified ct labels;
    it changes neither list identities nor the separately selected endpoint_cities.
    source_bound_cities opts legacy batches into bidirectional source-safe reuse.
    Every member in a batch must have a selected ct or exact native identity
    (g, network, n, rid). Mixed or unselected batches retain the default.
    Exact identities allow a reviewed city inside a shared fallback ct without
    enabling that entire fallback. This does not enable endpoint ordering."""
    every = cities is True
    chosen = lambda f: f["properties"].get("jk") == "urban" and (every or f["properties"].get("ct") in cities)
    endpoint = [f for f in features if chosen(f) and f['properties'].get('ct') in endpoint_cities]
    out = [f for f in features if not chosen(f)]
    if endpoint:
        from endpoint_bundles import apply_endpoint
        out.extend(apply_endpoint(endpoint, code, source or {}, endpoint_audit, context_sink))
    for city, mine in groups([f for f in features if chosen(f) and f['properties'].get('ct') not in endpoint_cities],
                             geographic_cities=geographic_cities):
        pts = [c for f in mine for part in parts_of(f) for c in part]
        proj = Projection(sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
        props, paths = {}, []
        for f in mine:
            p = f["properties"]
            key = f"{p.get('network', '')}|{p['n']}|{p.get('rid', '')}"
            props.setdefault(key, {k: v for k, v in p.items() if k not in DROP})
            paths.extend(([proj(*c) for c in part], frozenset([key])) for part in parts_of(f))
        def source_selected(f):
            p = f['properties']
            return p.get('ct') in source_bound_cities or (p.get('g'),p.get('network',''),p['n'],p.get('rid','')) in source_bound_identities
        bounded = bool(mine) and all(source_selected(f) for f in mine)
        g = build(paths, source_bound=bounded)
        edges = contract(g)
        order = Order(g, edges)
        cost = order.anneal(rounds=min(60000, max(4000, 400 * sum(1 for o in order.order if len(o) > 1))))
        lonlat = lambda xy: [round(v, 7) for v in proj.back(*xy)]
        stretch = []                            # each edge in metres, its ends exactly on its nodes
        for e in edges:
            inner = list(LineString(e["co"]).simplify(SIMPLIFY).coords) if len(e["co"]) > 2 else e["co"]
            stretch.append([g.node[e["u"]]] + [tuple(c) for c in inner[1:-1]] + [g.node[e["v"]]])
        drawn = smooth_lines(edges, stretch, order)
        for i, e in enumerate(edges):
            n = len(order.order[i])
            for k, key in enumerate(order.order[i]):
                q = dict(props[key])
                q["off"] = k - (n - 1) / 2          # right of the stretch's direction is positive, as line-offset
                q["bn"] = n
                co = [lonlat(c) for c in drawn[i, key]]
                out.append({"type": "Feature", "properties": q, "geometry": {"type": "LineString", "coordinates": co}})
        print(f"{code} {city} light rail bundled: {len(props)} lines on {len(edges)} stretches "
              f"({sum(1 for e in edges if len(e['lines']) > 1)} shared); order cost {cost:.0f}", flush=True)
    return out


def groups(features, *, geographic_cities=()):
    """Legacy city/bounding-box batches, or scoped metric geographic batches.

    Only geographic_cities crosses ct labels, within one known country and MERGE
    metres of actual geometry. The returned city string is a diagnostic label.
    """
    # A city is a presentation/list identity. Only explicitly enabled cities may
    # share a support graph across that identity, and only with actual geometry
    # within the same metric distance used by Network (MERGE metres).
    enabled = frozenset(geographic_cities)
    by_city, geographic = defaultdict(list), defaultdict(list)
    for f in features:
        props = f["properties"]
        city, country = props.get("ct"), props.get("g")
        if city in enabled:
            # An unknown country must not provide cross-city country evidence.
            geographic[(country or "", city if not country else "")].append(f)
        else:
            by_city[city].append(f)
    out = []
    for city in sorted(by_city, key=lambda c: c or ""):
        fs = by_city[city]
        box = []
        for f in fs:
            pts = [c for part in parts_of(f) for c in part]
            box.append((min(x for x, _ in pts) - REACH, min(y for _, y in pts) - REACH,
                        max(x for x, _ in pts) + REACH, max(y for _, y in pts) + REACH))
        parent = list(range(len(fs)))
        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for i in range(len(fs)):
            for j in range(i + 1, len(fs)):
                a, b = box[i], box[j]
                if a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]:
                    parent[root(i)] = root(j)
        sets = defaultdict(list)
        for i, f in enumerate(fs):
            sets[root(i)].append(f)
        out.extend((city, members) for _, members in sorted(sets.items()))
    for _, fs in sorted(geographic.items()):
        pts = [c for f in fs for part in parts_of(f) for c in part]
        if not pts:
            out.extend((f["properties"].get("ct"), [f]) for f in fs)
            continue
        # Projection emits metres (kx=111320*cos(lat0), ky=110540). Bounding
        # boxes only accelerate candidates; their overlap is never a union.
        proj = Projection(sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
        from shapely.geometry import MultiLineString
        from shapely.strtree import STRtree
        geometries = [MultiLineString([[proj(*c) for c in part] for part in parts_of(f)
                                      if len(part) >= 2]) for f in fs]
        tree = STRtree(geometries)
        parent = list(range(len(fs)))
        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for i, geom in enumerate(geometries):
            for j in tree.query(geom, predicate="dwithin", distance=MERGE):
                j = int(j)
                if j > i:
                    parent[root(i)] = root(j)
        sets = defaultdict(list)
        for i, f in enumerate(fs):
            sets[root(i)].append(f)
        for _, members in sorted(sets.items()):
            # Diagnostic group label only. Feature ct/network/rid stay intact.
            cities = sorted({f["properties"].get("ct") or "" for f in members})
            out.append((" / ".join(cities), members))
    return out


REACH = 0.005       # degrees (about 400 m) around a line's extent: nearer lines are bundled together
SIMPLIFY = 1.5      # m: the tolerance a written stretch is simplified to (its ends stay where they are)
SAMPLE = 2.0        # m between the points a line's course is smoothed over
SIGMA = 8.0         # m: the width of the smoothing; a corner of the centre lines becomes a curve of about 12 m radius
KEEP = 0.4          # m: the tolerance a smoothed piece is simplified to


def smooth_lines(edges, stretch, order):
    """{(edge index, line): coordinates in metres, in the edge's direction}. A line's stretches are
    joined through every node it passes (where it has exactly two stretches) and its course is
    smoothed there: the centre lines meet at nodes in corners, and where a line leaves a bundle
    its own track near the node is left out (CROP), so without this it turns in a mitre where its
    tram turns in a curve ("优化电车平滑度", 2026-10-18, two corners in Zurich). A Gaussian of SIGMA
    over points SAMPLE apart; the ends of a course (a terminus, a branching of the line) stay
    exactly where they are. Every stretch is sampled on its own, the same for every line on it, so
    lines that run together stay together until a few SIGMA from where one turns away."""
    pieces = {}
    for i, e in enumerate(edges):                       # evenly along the stretch, its ends exactly on its nodes
        line = LineString(stretch[i])
        n = max(1, math.ceil(line.length / SAMPLE))
        pieces[i] = [stretch[i][0]] + [line.interpolate(line.length * k / n).coords[0] for k in range(1, n)] + [stretch[i][-1]]
    ends = defaultdict(lambda: defaultdict(list))       # line -> node -> [(edge, the end there)]
    for i, e in enumerate(edges):
        for key in order.order[i]:
            ends[key][e["u"]].append((i, 0))
            ends[key][e["v"]].append((i, 1))
    drawn = {}
    for key, at in ends.items():
        through = {v for v, es in at.items() if len(es) == 2 and
                   (not hasattr(order, 'connections') or
                    (order.next.get((v, es[0][0], key)) == es[1][0] and
                     order.next.get((v, es[1][0], key)) == es[0][0]))}
        left = {i for v in at for i, _ in at[v]}
        while left:
            # walk a course: from an end that is not passed through, else (a ring) from anywhere
            start = next((i for i in sorted(left) for v, end in ((edges[i]["u"], 0), (edges[i]["v"], 1)) if v not in through), None)
            ring = start is None
            i = start if not ring else min(left)
            node = edges[i]["u"] if ring or edges[i]["u"] not in through else edges[i]["v"]
            course = []                                 # (edge, reversed)
            while i in left:
                left.discard(i)
                rev = edges[i]["u"] != node
                course.append((i, rev))
                node = edges[i]["u"] if rev else edges[i]["v"]
                if node not in through:
                    break
                i = next(j for j, _ in at[node][:2] if j != i or at[node][0][0] == at[node][1][0])
            pts, cut = [], [0]
            for i, rev in course:
                co = pieces[i][::-1] if rev else pieces[i]
                pts.extend(co if not pts else co[1:])
                cut.append(len(pts) - 1)
            closed = ring and len(pts) > 3 and math.dist(pts[0], pts[-1]) < 1e-6
            out = gaussian(pts, closed)
            for (i, rev), a, b in zip(course, cut, cut[1:]):
                co = out[a:b + 1]
                co = list(LineString(co).simplify(KEEP).coords) if len(co) > 2 else co
                drawn[i, key] = co[::-1] if rev else co
    return drawn


def gaussian(pts, closed):
    """pts smoothed by a Gaussian of SIGMA metres along them; the ends are kept (a point reflection
    beyond each end, so a straight end stays straight), a closed course wraps round."""
    n = len(pts)
    if n < 3:
        return list(pts)
    reach = int(3 * SIGMA / SAMPLE) + 1
    if closed:
        ring = pts[:-1]
        m = len(ring)
        ext = [ring[k % m] for k in range(-reach, m + reach)]
    else:
        head = [(2 * pts[0][0] - pts[k][0], 2 * pts[0][1] - pts[k][1]) for k in range(min(reach, n - 1), 0, -1)]
        tail = [(2 * pts[-1][0] - pts[-1 - k][0], 2 * pts[-1][1] - pts[-1 - k][1]) for k in range(1, min(reach, n - 1) + 1)]
        ext = head + list(pts) + tail
    off = reach if closed else len(head)
    w = [math.exp(-((k * SAMPLE) ** 2) / (2 * SIGMA ** 2)) for k in range(-reach, reach + 1)]
    out = []
    for j in range(n - 1 if closed else n):
        c = j + off
        lo, hi = max(0, c - reach), min(len(ext) - 1, c + reach)
        sx = sy = sw = 0.0
        for k in range(lo, hi + 1):
            wk = w[k - c + reach]
            sx += wk * ext[k][0]; sy += wk * ext[k][1]; sw += wk
        out.append((sx / sw, sy / sw))
    if closed:
        out.append(out[0])
    else:
        out[0], out[-1] = pts[0], pts[-1]
    return out


def parts_of(f):
    return f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]]


def main(code, city, out=None, frame=None):
    """frame: (lon, lat, width in km) to draw just that window, at about z13 scale."""
    proj, colour, paths, feats = load(code, city)
    g = build(paths)
    edges = contract(g)
    o = Order(g, edges)
    start = o.total()
    final = o.anneal()
    shared = [e for e in edges if len(e["lines"]) > 1]
    print(f"{code} {city}: {len(feats)} lines, {len(g.node)} nodes, {len(edges)} edges "
          f"({len(shared)} shared, up to {max(len(e['lines']) for e in edges)} lines); cost {start:.0f} -> {final:.0f}", flush=True)
    if out:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 2, figsize=(20, 10), facecolor="#111")
        for ax in axes:
            ax.set_facecolor("#111"); ax.set_aspect("equal"); ax.axis("off")
        for co, lines in paths:                              # as drawn now: each line on its own track
            (key,) = lines
            axes[0].plot([x for x, _ in co], [y for _, y in co], color=colour[key], lw=2.2)
        axes[0].set_title("now: each line on its own track", color="white")
        parts, joins = drawn(g, edges, o, spacing=SPACING, trim=TRIM)
        for line, polys in parts.items():
            for pts in polys + joins[line]:
                axes[1].plot([x for x, _ in pts], [y for _, y in pts], color=colour[line], lw=2.2, solid_capstyle="butt")
        axes[1].set_title(f"bundled and ordered (cost {final:.0f})", color="white")
        # frame the part where lines share track, with a margin
        xs = [x for e in edges if len(e["lines"]) > 1 for x, _ in e["co"]] or [x for co, _ in paths for x, _ in co]
        ys = [y for e in edges if len(e["lines"]) > 1 for _, y in e["co"]] or [y for co, _ in paths for _, y in co]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        half = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 400
        if frame:
            (cx, cy), half = proj(frame[0], frame[1]), frame[2] * 500
        for ax in axes:
            ax.set_xlim(cx - half, cx + half); ax.set_ylim(cy - half, cy + half)
        fig.savefig(out, dpi=110, bbox_inches="tight", facecolor="#111")
    return g, edges, o


if __name__ == "__main__":
    frame = tuple(map(float, sys.argv[4].split(","))) if len(sys.argv) > 4 else None
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None, frame)
