"""Which metro lines stop at a station: from the stops of the lines' route relations, not from
how close a line passes (scripts/process_osm.py writes it, scripts/build_graph.py links by it).

A line that runs under a station without stopping there is no line of that station. Linking a
station to every line within 300 m of it gave 长椿街 the 19号线 that passes under it (it is a
2号线 station) and 王舍人立交桥 the 济南 3号线, and left 平安里 without the 19号线 that does stop
there, 400 m from its dot. So:
- a line's stops are the stop and platform members of its route relations (each with its name,
  or the name of its stop_area);
- a line stops at a station dot when one of its stops has the dot's name within SAME_NAME_M of
  it, or when any of its stops is within SAME_PLACE_M of it (a stop mapped under another name);
- dots of one name within SAME_NAME_M of each other are one station: they share their lines
  (the platforms of two lines at an interchange are often mapped as two dots);
- where OSM lacks a stop that a source gives, data/metro_stop_overrides.json adds it, with the
  source;
- a line with no stops in OSM at all cannot be judged so: it is linked by distance, as before,
  and listed.
"""
import json
import math
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / "data" / "metro_stop_overrides.json"
SAME_NAME_M = 1500
SAME_PLACE_M = 150
TRADITIONAL = str.maketrans("廣鐵綫線東馬灣機場門輕軌區環聯絡貨車專運濱園臺", "广铁线线东马湾机场门轻轨区环联络货车专运滨园台")
STATUS = re.compile(r"[（(]?(在建|规划|建设中|未开通|暂缓开通|暫緩開通|预留)[)）]?")


def metres(a, b):
    return math.hypot((a[0] - b[0]) * math.cos(math.radians((a[1] + b[1]) / 2)), a[1] - b[1]) * 111320


def canon(name):
    """What two spellings of one station's name have in common: 平安里站 is 平安里, 國家圖書館 is 国家图书馆
    as far as these characters go, a station's name with its line or its status is its name."""
    s = name or ""
    if re.search(r"[一-鿿]", s):
        s = re.sub(r"[A-Za-z][A-Za-z .'\-/&,]*", "", s)          # 盧押道 Luard Road
    s = re.sub(r"\s", "", s).translate(TRADITIONAL)
    s = STATUS.sub("", s)
    s = re.sub(r"(?<=[一-鿿])\d+号线$", "", s)
    s = re.sub(r"[（(]\s*[)）]", "", s)
    for _ in range(2):
        if len(s) > 2:
            s = re.sub(r"(地铁站|捷运站|捷運站|站)$", "", s)
    return s


def stops_of(routes, stopping):
    """{route relation: [(canonical name, name, lon, lat)]}. routes: the relations wanted;
    stopping: the extract's "stops" (scripts/extract_osm.py route_stops)."""
    nodes, platforms, areas = stopping["nodes"], stopping["platforms"], stopping["areas"]
    out = {}
    for rid in routes:
        found = []
        for kind, ref, role in stopping["routes"].get(rid, ()):
            if kind == "n" and ref in nodes:
                tags, lon, lat = nodes[ref]
                name = tags.get("name:zh") or tags.get("name") or ""
                if not re.search(r"[一-鿿]", name) and ref in areas:
                    name = areas[ref]                                # a stop position named "1" or "A" in its stop area
            elif kind == "w" and ref in platforms:
                tags, lon, lat = platforms[ref]
                name = tags.get("name:zh") or tags.get("name") or ""
            else:
                continue
            found.append((canon(name), name, lon, lat))
        out[rid] = found
    return out


def overrides(path=OVERRIDES):
    return json.loads(path.read_text()) if path.exists() else []


def lines_at(dots, line_stops, extra=()):
    """The lines that stop at each dot: [sorted line names] in the order of dots.
    dots: [(name, lon, lat)]; line_stops: {line: [(canonical name, name, lon, lat)]};
    extra: rows of the overrides file ({"line", "station", "at"})."""
    grid = defaultdict(list)                     # 0.02 degree cell -> (line, canonical name, lon, lat)
    for line, stops in line_stops.items():
        for c, _, x, y in stops:
            grid[(int(x // 0.02), int(y // 0.02))].append((line, c, x, y))
    found = []
    for name, x, y in dots:
        c, here = canon(name), set()
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for line, sc, sx, sy in grid.get((int(x // 0.02) + i, int(y // 0.02) + j), ()):
                    if line in here:
                        continue
                    d = metres((x, y), (sx, sy))
                    if d <= SAME_PLACE_M or (sc == c and d <= SAME_NAME_M):
                        here.add(line)
        found.append(here)
    for row in extra:
        at = tuple(row["at"])
        near = [k for k, (name, x, y) in enumerate(dots) if canon(name) == canon(row["station"]) and metres((x, y), at) <= 300]
        for k in near:
            found[k].add(row["line"])
    # dots of one name close together are one station
    by_name = defaultdict(list)
    for k, (name, x, y) in enumerate(dots):
        by_name[canon(name)].append(k)
    shared = [set(s) for s in found]
    for ks in by_name.values():
        for a in ks:
            for b in ks:
                if a != b and metres(dots[a][1:], dots[b][1:]) <= SAME_NAME_M:
                    shared[a] |= found[b]
    return [sorted(s) for s in shared]
