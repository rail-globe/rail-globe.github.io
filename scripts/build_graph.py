"""Build the routing network used by the "between two stations" search.

Input : data/raw/routing_input.pkl (classified tracks, written by scripts/process_osm.py)
        data/stations.geojson
Output: data/graph.json, and a hub id (property g) on every routable station in stations.geojson

The network covers China only and is made of the running lines themselves: nodes are junctions,
edges are the track between them with its line, class and length. Every station gets a hub node
linked to the nearby track of each line, so a route can start, end and change lines at a station.
Yard and siding tracks are left out: a route should read as a sequence of real, named lines.

Costs are running times from a nominal speed per class; there is no timetable behind them.
"""
import json
import math
import pickle
from collections import Counter, defaultdict
from pathlib import Path

from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"
SPEED = {"hsr350": 300, "hsr250": 220, "hsr200": 160, "main": 100, "branch": 60}   # km/h
SHAPE_TOL = 0.0004       # degrees (~40 m): how closely a drawn route follows the track
STATION_R = 0.007        # degrees (~700 m): track this close to a station belongs to it
TRANSFER_MIN = 4         # minutes between a station hub and one of its tracks
MAX_LINKS = 8            # tracks linked per station


def pack(c):
    return (round(c[0] * 1e6) << 32) | (round(c[1] * 1e6) & 0xFFFFFFFF)


def km(coords):
    s = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        s += math.hypot((x2 - x1) * math.cos(math.radians((y1 + y2) / 2)), y2 - y1) * 111.32
    return s


ways = pickle.load(open(RAW / "routing_input.pkl", "rb"))   # written locally by process_osm.py
ways = [w for w in ways if w[2] == "cn" and w[0] != "svc"]
stations = json.load(open(OUT / "stations.geojson"))
for f in stations["features"]:
    f["properties"].pop("g", None)
lines, line_idx = [], {}
way_line = []
for cls, name, country, co in ways:
    k = (name, cls, country)
    if k not in line_idx:
        line_idx[k] = len(lines)
        lines.append([name, cls, country])
    way_line.append(line_idx[k])
print(f"{len(ways)} tracks on {len(lines)} lines")

# ---- 1. track vertices near stations become nodes, so a station sits on the network ----
CELL = 0.01
st_cells = set()
for f in stations["features"]:
    x, y = f["geometry"]["coordinates"]
    cx, cy = int(x // CELL), int(y // CELL)
    st_cells.update((cx + dx, cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
near = defaultdict(list)     # cell -> (lon, lat, line)
for wi, (cls, name, country, co) in enumerate(ways):
    for x, y in co:
        cell = (int(x // CELL), int(y // CELL))
        if cell in st_cells:
            near[cell].append((x, y, way_line[wi]))
forced, st_links = set(), []
for f in stations["features"]:
    x, y = f["geometry"]["coordinates"]
    cx, cy = int(x // CELL), int(y // CELL)
    cosy = math.cos(math.radians(y))
    best = {}                # line -> (distance, vertex)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for vx, vy, li in near.get((cx + dx, cy + dy), ()):
                d = math.hypot((vx - x) * cosy, vy - y)
                if d <= STATION_R and (li not in best or d < best[li][0]):
                    best[li] = (d, (vx, vy))
    ranked = sorted(best.items(), key=lambda kv: kv[1][0])
    picks = [v for _, (_, v) in ranked[:MAX_LINKS]]
    forced.update(pack(v) for v in picks)
    st_links.append(picks)

# ---- 2. split tracks at junctions ----
use, ends = Counter(), set()
for cls, name, country, co in ways:
    pts = [pack(c) for c in co]
    for q in set(pts):
        use[q] += 1
    ends.add(pts[0])
    ends.add(pts[-1])
raw = []                     # (a, b, coords, line)
for wi, (cls, name, country, co) in enumerate(ways):
    start = 0
    for i in range(1, len(co)):
        q = pack(co[i])
        if i == len(co) - 1 or use[q] >= 2 or q in ends or q in forced:
            if pack(co[start]) != q:
                raw.append((pack(co[start]), q, co[start:i + 1], way_line[wi]))
            start = i
del use
print(f"{len(raw)} pieces between junctions")

# ---- 3. join pieces through plain two-way nodes of the same line ----
adj = defaultdict(list)
for ei, (a, b, co, li) in enumerate(raw):
    adj[a].append(ei)
    adj[b].append(ei)
used = [False] * len(raw)
edges = []                   # (a, b, coords, line)


def extend(node, ei, li):
    """Follow the chain from `node` (an end of piece ei) while it is a plain through node."""
    chain = []
    while node not in forced and len(adj[node]) == 2:
        nxt = adj[node][0] if adj[node][1] == ei else adj[node][1]
        if used[nxt] or raw[nxt][3] != li:
            break
        a, b, co, _ = raw[nxt]
        if a == b:
            break
        used[nxt] = True
        chain.append(co if a == node else co[::-1])
        node = b if a == node else a
        ei = nxt
    return node, chain


for ei, (a, b, co, li) in enumerate(raw):
    if used[ei]:
        continue
    used[ei] = True
    end, fwd = extend(b, ei, li)
    start, back = extend(a, ei, li)
    coords = []
    for part in [c[::-1] for c in back[::-1]] + [co] + fwd:
        coords += part if not coords else part[1:]
    edges.append((start, end, coords, li))
del raw, adj
print(f"{len(edges)} edges after joining")

# ---- 4. number the nodes, add station hubs ----
node_id, node_xy = {}, []


def nid(q, xy):
    if q not in node_id:
        node_id[q] = len(node_xy)
        node_xy.append(xy)
    return node_id[q]


E = []                       # [u, v, line, metres, shape...]
shape_pts = 0
for a, b, co, li in edges:
    u, v = nid(a, co[0]), nid(b, co[-1])
    simp = list(LineString(co).simplify(SHAPE_TOL, preserve_topology=False).coords)[1:-1] if len(co) > 2 else []
    shape_pts += len(simp)
    E.append((u, v, li, round(km(co) * 1000), simp))
transfer = len(lines)
lines.append(["", "x", ""])
hub_start = len(node_xy)     # nodes from here on are station hubs
hubs = 0
for f, picks in zip(stations["features"], st_links):
    f["properties"].pop("g", None)
    picks = [node_id[pack(v)] for v in picks if pack(v) in node_id]
    if not picks:
        continue
    hub = len(node_xy)
    node_xy.append(tuple(f["geometry"]["coordinates"]))
    f["properties"]["g"] = hub
    hubs += 1
    for n in picks:
        E.append((hub, n, transfer, 0, []))
print(f"{len(node_xy)} nodes, {len(E)} edges, {shape_pts} shape points, {hubs} of {len(stations['features'])} stations on the network")

# ---- 5. write: integer coordinates (1e-5 degrees), shapes as deltas from the edge's first node ----
q5 = lambda v: round(v * 1e5)
flat_nodes = [q5(v) for xy in node_xy for v in xy]
flat_edges, flat_shapes = [], []
for u, v, li, m, simp in E:
    flat_edges += [u, v, li, m, len(simp)]
    px, py = q5(node_xy[u][0]), q5(node_xy[u][1])
    for x, y in simp:
        qx, qy = q5(x), q5(y)
        flat_shapes += [qx - px, qy - py]
        px, py = qx, qy
graph = {"speed": SPEED, "transferMin": TRANSFER_MIN, "hubStart": hub_start, "lines": lines, "nodes": flat_nodes, "edges": flat_edges, "shapes": flat_shapes}
(OUT / "graph.json").write_text(json.dumps(graph, ensure_ascii=False, separators=(",", ":")))
(OUT / "stations.geojson").write_text(json.dumps(stations, ensure_ascii=False, separators=(",", ":")))
print(f"graph.json: {(OUT / 'graph.json').stat().st_size / 1e6:.1f} MB")
