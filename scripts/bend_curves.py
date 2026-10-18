"""Bounded local centre curves for explicitly selected, frozen pilot junctions."""
import math
from collections import defaultdict
from shapely.geometry import LineString
from line_bundles import SAMPLE, SIGMA, KEEP
NODE_SIGMA=16.0
NODE_REACH=96.0
CURVE_REACH=192.0
CURVE_KEEP=.015

def smooth_lines(edges, stretch, order, nodes):
    """Smooth selected (node, source identity) junctions in a frozen graph.

    ``nodes`` maps a node to None (the whole shared family) or exact source
    identities. True course ends stay fixed. Distant simplifier vertices are
    retained, and the caller separately audits source displacement and render
    topology before accepting the result.
    """
    def selected(node, key):
        allowed = nodes.get(node, ())
        return allowed is None or key in allowed
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
            # Only bundled through-junctions use the wider kernel. Long source
            # curves and unconnected branch endpoints keep the existing policy.
            junctions = []
            for k in range(1, len(course)):
                left_i, right_i = course[k - 1][0], course[k][0]
                node = edges[left_i]['u'] if course[k - 1][1] else edges[left_i]['v']
                if selected(node, key) and max(len(order.order[left_i]), len(order.order[right_i])) > 1:
                    junctions.append(cut[k])
            first_node = edges[course[0][0]]['v'] if course[0][1] else edges[course[0][0]]['u']
            if closed and selected(first_node, key) and max(len(order.order[course[0][0]]), len(order.order[course[-1][0]])) > 1:
                junctions.extend([0, len(pts) - 1])
            out = gaussian(pts, closed, junctions)
            legacy = gaussian(pts, closed)
            for (i, rev), a, b in zip(course, cut, cut[1:]):
                old = legacy[a:b + 1]
                coarse = list(LineString(old).simplify(KEEP).coords) if len(old) > 2 else old
                # Retain the old simplifier's actual vertices outside local
                # windows. Re-simplifying the remaining long prefix changes its
                # normals and can introduce a distant offset loop.
                indices = []
                cursor = 0
                for point in coarse:
                    while cursor < len(old) - 1 and math.dist(old[cursor], point) > 1e-9:
                        cursor += 1
                    indices.append(a + cursor)
                marked = [any(abs(j - node) * SAMPLE <= CURVE_REACH for node in junctions)
                          for j in range(a, b + 1)]
                runs = []
                for j in range(a, b):
                    if marked[j-a] or marked[j-a+1]:
                        if runs and runs[-1][1] == j:
                            runs[-1][1] = j + 1
                        else:
                            runs.append([j, j + 1])
                windows = []
                for lo, hi in runs:
                    lo = max((j for j in indices if j <= lo), default=a)
                    hi = min((j for j in indices if j >= hi), default=b)
                    if windows and lo <= windows[-1][1]:
                        windows[-1][1] = max(hi, windows[-1][1])
                    else:
                        windows.append([lo, hi])
                co, cursor = [], 0
                for lo, hi in windows:
                    while cursor < len(indices) and indices[cursor] < lo:
                        co.append(coarse[cursor]); cursor += 1
                    fine = list(LineString(out[lo:hi + 1]).simplify(CURVE_KEEP).coords)
                    co.extend(fine if not co or co[-1] != fine[0] else fine[1:])
                    while cursor < len(indices) and indices[cursor] <= hi:
                        cursor += 1
                co.extend(coarse[cursor:])
                drawn[i, key] = co[::-1] if rev else co
    return drawn


def gaussian(pts, closed, junctions=()):
    """pts smoothed by a Gaussian of SIGMA metres along them; the ends are kept (a point reflection
    beyond each end, so a straight end stays straight), a closed course wraps round."""
    n = len(pts)
    if n < 3:
        return list(pts)
    reach = int(3 * (NODE_SIGMA if junctions else SIGMA) / SAMPLE) + 1
    if closed:
        ring = pts[:-1]
        m = len(ring)
        ext = [ring[k % m] for k in range(-reach, m + reach)]
    else:
        head = [(2 * pts[0][0] - pts[k][0], 2 * pts[0][1] - pts[k][1]) for k in range(min(reach, n - 1), 0, -1)]
        tail = [(2 * pts[-1][0] - pts[-1 - k][0], 2 * pts[-1][1] - pts[-1 - k][1]) for k in range(1, min(reach, n - 1) + 1)]
        ext = head + list(pts) + tail
    off = reach if closed else len(head)
    weights = {}
    def kernel(j):
        distance = min((abs(j - node) * SAMPLE for node in junctions), default=NODE_REACH)
        t = max(0.0, 1.0 - distance / NODE_REACH)
        eased = t ** 3 * (10 + t * (-15 + 6 * t))
        sigma = SIGMA + (NODE_SIGMA - SIGMA) * eased
        key = round(sigma, 9)
        if key not in weights:
            weights[key] = [math.exp(-((k * SAMPLE) ** 2) / (2 * sigma ** 2)) for k in range(-reach, reach + 1)]
        return weights[key], int(3 * sigma / SAMPLE) + 1
    out = []
    for j in range(n - 1 if closed else n):
        c = j + off
        w, local_reach = kernel(j)
        lo, hi = max(0, c - local_reach), min(len(ext) - 1, c + local_reach)
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

