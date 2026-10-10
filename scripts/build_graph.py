"""Build the routing network used by the "between two stations" search.

Input : data/raw/routing_input.pkl, routing_metro.pkl (classified rail tracks and metro tracks,
        written by scripts/process_osm.py), data/stations.geojson, data/metro_stations.geojson
Output: data/graph.json, and a hub id (property g) on every routable station in the two station files

The network covers China only and is made of the running lines themselves: nodes are junctions,
edges are the track between them with its line, class and length. Every station gets a hub node
linked to every nearby track of each line (a double line has one per direction and they only meet
at junctions), so a route can start, end and change lines at a station without running on past it.
Railway stations are linked to railway track and metro stations to metro track; a railway station
and a metro station next to each other are joined by a walk, which is how a route gets from one
network to the other. Railway track that a metro company runs its trains on (class "mrail") can be
boarded at either kind of station.
A tram is boarded at a stop on its own track: tram track is linked to what lies right by it, and
a tram stop (property t) to tram track only, not to the metro that runs under its street. From a
tram stop to the metro stations beside it is a walk.
A metro station is linked to the lines that stop there (data/raw/routing_stops.pkl, from the stops
of the lines' route relations: scripts/metro_stops.py), not to a line that runs past it within a
few hundred metres, and to such a line's track even where it lies further from the dot than the
usual reach (平安里: the 19号线 platforms are 400 m from it). A line whose relations give no stops
is linked by distance, and listed. A station that no line stops at, by the relations, is linked
only to a line whose track runs right through it, unless its name says it is not open: OSM's
relations miss a stop here and there (陶然桥 on the 14号线), and such a station would be cut off.

Railway track joins wherever two tracks share a point: a train runs through a junction from one
line onto the next. Metro lines are kept apart: each has its own nodes, also where it shares
track with another line or where a connecting track joins two lines, so a passenger changes
between metro lines only at a station, and pays for the change.
Yard and siding tracks are left out: a route should read as a sequence of real, named lines.

Costs are running times from a nominal speed per class (for metros an average that includes
stops), a few minutes at each station hub, and walking pace between stations; there is no
timetable behind them.
"""
import json
import math
import pickle
import re
from collections import Counter, defaultdict
from pathlib import Path

from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"
# km/h. metro and mrail (intercity and suburban lines run by a metro company) are averages with stops; w is walking
SPEED = {"hsr350": 300, "hsr250": 220, "hsr200": 160, "main": 100, "branch": 60, "metro": 36, "mrail": 70, "w": 4.5}
URBAN = ("metro", "mrail")
SHAPE_TOL = 0.0004       # degrees (~40 m): how closely a drawn route follows the track
STATION_R = 0.007        # degrees (~700 m): track this close to a station belongs to it
METRO_R = 0.003          # the same for a metro station (~300 m): stations and lines are much closer together
TRAM_R = 0.0008          # and for tram track (~90 m): a stop is on its track, and the next street has another line
STOP_R = 0.008           # (~800 m) the track of a line that stops at a metro station, by its relations
THROUGH_R = 0.0006       # (~65 m) a line's track this close runs through the station
NOT_OPEN = re.compile(r"在建|规划|建设中|未开通|暂未开通|暂缓开通|暫緩開通|预留|預留|緊急|紧急")
TRANSFER_MIN = 12        # minutes between a railway station hub and one of its tracks; with the walk, this is
                         # what keeps a trip across town on the metro instead of hopping on a train for one stop
METRO_MIN = 3            # the same at a metro station
WALK_R = 0.006           # a railway station and a metro station this close are joined by a walk
TRAM_WALK_R = 0.003      # a tram stop and a metro station this close are joined by a walk
WALK_DETOUR = 1.4        # walking distance over the straight line
MAX_LINKS = 12           # tracks linked per station


def pack(c):
    return (round(c[0] * 1e6) << 32) | (round(c[1] * 1e6) & 0xFFFFFFFF)


def km(coords):
    s = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        s += math.hypot((x2 - x1) * math.cos(math.radians((y1 + y2) / 2)), y2 - y1) * 111.32
    return s


ways = pickle.load(open(RAW / "routing_input.pkl", "rb"))   # written locally by process_osm.py
ways = [w for w in ways if w[2] == "cn" and w[0] != "svc"]           # (class, line, country, coordinates, colour)
tram_from = len(ways)        # the tracks of the tram lines come last, from here on
if (RAW / "routing_metro.pkl").exists():
    for name, colour, tracks, tram in pickle.load(open(RAW / "routing_metro.pkl", "rb")):
        if not tram:
            tram_from = len(ways) + len(tracks)
        ways += [("metro", name, "cn", co, colour) for co in tracks]
# the metro lines that stop at each metro station, and the lines that have stops to judge by
STOPS = pickle.load(open(RAW / "routing_stops.pkl", "rb")) if (RAW / "routing_stops.pkl").exists() else {"lines": [], "dots": {}}
judged = set(STOPS["lines"])
stations = json.load(open(OUT / "stations.geojson"))
metro_stations = json.load(open(OUT / "metro_stations.geojson"))
# every station with what it may be linked to: (feature, radius, metro?)
stops = [(f, STATION_R, False) for f in stations["features"]] + [(f, METRO_R, True) for f in metro_stations["features"]]
for f, _, _ in stops:
    f["properties"].pop("g", None)
lines, line_idx = [], {}
way_line = []
for cls, name, country, co, colour in ways:
    k = (name, cls, country)
    if k not in line_idx:
        line_idx[k] = len(lines)
        lines.append([name, cls, country] + ([colour] if colour else []))
    way_line.append(line_idx[k])
print(f"{len(ways)} tracks on {len(lines)} lines")


def node(c, wi):
    """Identity of a track point: the place itself on a railway, the place on its line for a metro."""
    return (pack(c), way_line[wi]) if ways[wi][0] == "metro" else pack(c)

# ---- 1. track vertices near stations become nodes, so a station sits on the network ----
CELL = 0.01
st_cells = set()
for f, _, _ in stops:
    x, y = f["geometry"]["coordinates"]
    cx, cy = int(x // CELL), int(y // CELL)
    st_cells.update((cx + dx, cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
near = defaultdict(list)     # cell -> (lon, lat, way)
for wi, way in enumerate(ways):
    for x, y in way[3]:
        cell = (int(x // CELL), int(y // CELL))
        if cell in st_cells:
            near[cell].append((x, y, wi))
forced, st_links = set(), []
passing, by_distance, through = Counter(), Counter(), Counter()     # lines left unlinked as they do not stop there; links made by distance alone
for f, radius, metro in stops:
    x, y = f["geometry"]["coordinates"]
    cx, cy = int(x // CELL), int(y // CELL)
    cosy = math.cos(math.radians(y))
    best = {}                # way -> (distance, vertex, way)
    tram_stop = bool(f["properties"].get("t"))
    stopping = STOPS["dots"].get((f["properties"]["n"], x, y)) if metro and not tram_stop else None
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for vx, vy, wi in near.get((cx + dx, cy + dy), ()):
                if ways[wi][0] != "mrail" and (ways[wi][0] == "metro") != metro:
                    continue
                if tram_stop and wi < tram_from:
                    continue
                d = math.hypot((vx - x) * cosy, vy - y)
                reach = TRAM_R if wi >= tram_from else radius
                if stopping is not None and ways[wi][0] == "metro" and wi < tram_from and ways[wi][1] in judged:
                    if ways[wi][1] in stopping:
                        reach = STOP_R
                    elif stopping or d > THROUGH_R or NOT_OPEN.search(f["properties"]["n"]):
                        if d <= radius:
                            passing[(f["properties"]["n"], ways[wi][1])] += 1
                        continue             # the line runs past without stopping here
                    else:
                        through[(f["properties"]["n"], ways[wi][1])] += 1
                if d <= reach and (wi not in best or d < best[wi][0]):
                    best[wi] = (d, (vx, vy), wi)
    # Ways of one line that touch end to end are one track; the station is linked once to each track.
    track = {wi: wi for wi in best}

    def root(wi):
        while track[wi] != wi:
            track[wi] = track[track[wi]]
            wi = track[wi]
        return wi
    at = defaultdict(list)
    for wi in best:
        for c in (ways[wi][3][0], ways[wi][3][-1]):
            at[(way_line[wi], pack(c))].append(wi)
    for group in at.values():
        for wi in group[1:]:
            track[root(wi)] = root(group[0])
    per_track = {}
    for wi, hit in best.items():
        if root(wi) not in per_track or hit[0] < per_track[root(wi)][0]:
            per_track[root(wi)] = hit
    # a station's tram links are counted apart: they take no other line's place among its links
    picks = [(node(v, wi), ways[wi][0] in URBAN) for tram in (False, True)
             for _, v, wi in sorted(hit for hit in per_track.values() if (hit[2] >= tram_from) == tram)[:MAX_LINKS]]
    forced.update(q for q, _ in picks)
    st_links.append(picks)
    if metro and not tram_stop:
        for _, _, wi in per_track.values():
            if ways[wi][0] == "metro" and wi < tram_from and ways[wi][1] not in judged:
                by_distance[(f["properties"]["n"], ways[wi][1])] += 1
print(f"metro stations: {len(passing)} (station, line) pairs left unlinked, as the line passes without stopping; "
      f"{len(by_distance)} linked by distance alone, the line's relations giving no stops:", sorted(by_distance)[:40])
print(f"metro stations no line stops at by the relations, linked to the line whose track runs through them: {len(through)}", sorted(through))

# ---- 2. split tracks at junctions ----
use, ends = Counter(), set()
for wi, way in enumerate(ways):
    pts = [node(c, wi) for c in way[3]]
    for q in set(pts):
        use[q] += 1
    ends.add(pts[0])
    ends.add(pts[-1])
raw = []                     # (a, b, coords, line)
for wi, way in enumerate(ways):
    co, start = way[3], 0
    for i in range(1, len(co)):
        q = node(co[i], wi)
        if i == len(co) - 1 or use[q] >= 2 or q in ends or q in forced:
            if node(co[start], wi) != q:
                raw.append((node(co[start], wi), q, co[start:i + 1], way_line[wi]))
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
transfer, metro_transfer, walk = len(lines), len(lines) + 1, len(lines) + 2
lines += [["", "x", ""], ["", "y", ""], ["", "w", ""]]      # hub links to railway track, to metro track; a walk
hub_start = len(node_xy)     # nodes from here on are station hubs
hubs = Counter()
for (f, _, metro), picks in zip(stops, st_links):
    picks = [(node_id[q], urban) for q, urban in picks if q in node_id]
    if not picks:
        continue
    hub = len(node_xy)
    node_xy.append(tuple(f["geometry"]["coordinates"]))
    f["properties"]["g"] = hub
    hubs[metro] += 1
    for n, urban in picks:           # getting on an urban service is quicker than getting on a train
        E.append((hub, n, metro_transfer if urban else transfer, 0, []))
# a walk between a railway station and each metro station beside it
cells, tram_cells = defaultdict(list), defaultdict(list)
for f in metro_stations["features"]:
    if "g" in f["properties"]:
        x, y = f["geometry"]["coordinates"]
        (tram_cells if f["properties"].get("t") else cells)[(int(x // CELL), int(y // CELL))].append((x, y, f["properties"]["g"]))


def walks_from(f, among, reach, most):
    """Walks from a station to the nearest few of the stations in `among` (by cell) within reach."""
    x, y = f["geometry"]["coordinates"]
    cosy = math.cos(math.radians(y))
    close = sorted((math.hypot((mx - x) * cosy, my - y), g) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                   for mx, my, g in among.get((int(x // CELL) + dx, int(y // CELL) + dy), ()))
    found = [(f["properties"]["g"], g, walk, max(120, round(d * 111320 * WALK_DETOUR)), []) for d, g in close[:most] if d <= reach]
    E.extend(found)
    return len(found)


walks = sum(walks_from(f, cells, WALK_R, 3) for f in stations["features"] if "g" in f["properties"])
# and, counted apart from those, to the tram stops beside it; from a tram stop to the metro stations beside it
tram_walks = sum(walks_from(f, tram_cells, WALK_R, 2) for f in stations["features"] if "g" in f["properties"])
tram_walks += sum(walks_from(f, cells, TRAM_WALK_R, 2) for f in metro_stations["features"] if f["properties"].get("t") and "g" in f["properties"])
print(f"{len(node_xy)} nodes, {len(E)} edges, {shape_pts} shape points; on the network: {hubs[False]} of {len(stations['features'])} "
      f"railway stations, {hubs[True]} of {len(metro_stations['features'])} metro stations, {walks} walks between the two, {tram_walks} to and from tram stops")

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
graph = {"speed": SPEED, "transferMin": TRANSFER_MIN, "metroMin": METRO_MIN, "hubStart": hub_start, "lines": lines, "nodes": flat_nodes, "edges": flat_edges, "shapes": flat_shapes}
(OUT / "graph.json").write_text(json.dumps(graph, ensure_ascii=False, separators=(",", ":")))
(OUT / "stations.geojson").write_text(json.dumps(stations, ensure_ascii=False, separators=(",", ":")))
(OUT / "metro_stations.geojson").write_text(json.dumps(metro_stations, ensure_ascii=False, separators=(",", ":")))
print(f"graph.json: {(OUT / 'graph.json').stat().st_size / 1e6:.1f} MB")
