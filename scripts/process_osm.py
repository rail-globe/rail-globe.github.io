"""Stage 2: classify the extracted OSM objects and write the map layers.

Inputs : data/raw/extract.pkl     (scripts/extract_osm.py: China, Hong Kong, Macao, Taiwan)
         data/raw/extract_uk.pkl  (scripts/extract_osm.py uk: United Kingdom)
Outputs: data/rail_hsr.geojson, rail_conv.geojson, rail_build.geojson, rail_shared.geojson, stations.geojson,
         metro.geojson, metro_stations.geojson, metro_cities.json, yards.geojson, depots.geojson,
         lines.json
Nominal classes used for geometry grouping and routing before design annotation:
  hsr350  high-speed, maxspeed >= 300 km/h
  hsr250  high-speed, 250-299 (or unknown speed on a high-speed line)
  hsr200  intercity and fast lines below 250; Greater Bay Area intercity lines belong here
          whatever their speed tags say
  main    conventional, usage=main
  branch  conventional, other usages / untagged
  build   under construction (property h marks high-speed)

Every line is drawn once: of a double line only one track is written to the map layers
(scripts/single_track.py), except where the two directions run on separate alignments. The
routing network and the station matching still use every track.
Track grouping uses a principal class to build a continuous geometry. The final map is
then split by documented section design speeds (scripts/design_speeds.py), without
changing the geometry or using design speeds as operating speeds in the routing graph.
Tracks are grouped into lines by name (spelling variants such as 京沪高铁 / 京沪高速线 or
广深Ⅰ线 / 广深Ⅱ线 are one line); its internal group takes the principal track class, and
unnamed connecting stretches follow the line they join.
Where a second line of another class runs over the same track (listed in SHARED_KNOWN, or its
route=railway relation includes track that carries the first line's name), the track keeps its
own line and the second line is written to rail_shared.geojson; the map draws it as a parallel
line beside it.

Metro lines keep their official colour (property col) from the OSM route relations.
Who operates an intercity or suburban line decides where it is shown:
  - a line whose trains are run by a metro company (Guangdong Intercity under Guangzhou Metro,
    Shanghai Suburban Railway under Shentong...) leaves the rail classes and is written to
    metro.geojson with k = "m", whatever its speed; it stays in the routing network. Where the
    trains use only part of the line (Xi'an's 西户线 runs 阿房宫南 - 户县 on a longer freight
    line), only that stretch moves and the rest stays a rail line;
  - a suburban service run by a national-rail bureau over shared track (Beijing S2, Jinshan...)
    keeps its track as a rail line and is written to metro.geojson with k = "s". The map draws it
    as one parallel line beside the national line, so each service is reduced to a single path
    (one of the two tracks of a double line) with one consistent direction; the sideways offset
    then always falls on the same side.
Metro, light rail, monorail and maglev lines are taken for the whole country.
UK lines carry their main passenger operator (property o).
"""
import heapq
import json
import math
import os
import pickle
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from shapely.geometry import LineString, MultiLineString, Point, shape
from shapely.prepared import prep
from shapely.ops import linemerge, substring, unary_union
from shapely.strtree import STRtree

from single_track import bridge, curved, join_up, one_track, smooth, stitch
from finish_display import finish_metro
from metro_bends import trim_unowned_loop
from rail_classes import grade_votes, principal_class
from rail_status import corrected_tags, load_rules
from side_by_side import side_by_side
from metro_fit import fit as metro_fit, summary as metro_fit_summary
from along import FINE, TRACK, TRACK_MIN, exactly, meeting, settled

# The grouping below walks sets of names and coordinates. Python seeds their order afresh on every
# run, and with it which line an ambiguous piece of track went to: 輕鐵505綫 came out 6 km long in
# one run and 9 km in the next, with nothing changed. A fixed seed makes a run repeatable: the same
# data and the same code give the same map.
if __name__ == "__main__" and os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable] + sys.argv)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"
TOL = {"hsr350": 0.00012, "hsr250": 0.00012, "hsr200": 0.0001,
       "main": 0.0002, "branch": 0.0003, "build": 0.0002, "metro": 0.00006,
       "light": 0.00002}       # light rail: a 25 m curve is gone at 6 m tolerance
# How finely a bend is drawn back as a curve (single_track.curved): a point for about every so many
# degrees of turning, at most so many to a stretch, none closer together than so far (degrees).
# Every point is paid for in the size of the files the page loads, and the conventional network is
# both the longest and the most winding: the fast lines and the metros, drawn thick and looked at
# closely, get the fine curves, the conventional lines enough to take the corners off.
CURVE = {"hsr350": (4, 5, 0.0003), "hsr250": (4, 5, 0.0003), "hsr200": (4, 5, 0.0003), "metro": (10, 4, 0.0003), "light": (10, 6, 0.00004),
         "main": (8, 3, 0.0006), "branch": (8, 3, 0.0006), "build": (8, 3, 0.0006)}
SKIP_USAGE = {"industrial", "military", "tourism", "test", "freight;industrial"}
METRO_RAIL = {"subway", "light_rail", "monorail", "maglev"}
METRO_DEFAULT = "#5cc8ff"
# Not metro: trams, airport people movers, theme-park and company-campus lines.
NOT_METRO = re.compile(r"有轨|华为|比亚迪|世界之窗|旅客捷运|旅客捷運|旅客自动|APM T\d|APM$|People Mover|旅游|观光|文旅|小火车|绿博园|云轨"
                       r"|车辆段|联络线|付线|直通|贯通|直达|^TSB$|^[上下]行线$|自动旅客|机场捷运")   # through-running services are trains, not lines
# Route relations whose own name is only a direction ("A→B"): English name -> line name.
METRO_ALIAS = {"Changsha Maglev Express": "长沙磁浮快线"}
# The city a metro line belongs to, read off its name ("武汉地铁2号线", "宁波市轨道交通6号线").
METRO_CITY = re.compile(r"^(.{2,5}?)市?(?:地铁|地鐵|轨道交通|軌道交通|捷運|機場捷運|輕軌|磁浮|市域|市郊|云巴)")
CITY_OF = {"港鐵": "香港", "輕鐵": "香港"}                  # systems named without their city
INTERCITY_GROUP = {"44": "广东城际"}                        # metro-run intercity lines of a province, listed together
CITY_MERGE_DEG = 0.45                                      # a one-line "city" this close to a bigger one is part of it
METRO_SYSTEM = re.compile(r"地铁|地鐵|轨道交通|軌道交通|捷運|輕軌|轻轨|輕鐵|港鐵|市域|市郊|磁浮|云巴")
CN_DIGIT = {c: i for i, c in enumerate("零一二三四五六七八九")}
# Greater Bay Area intercity network: lines named 城际 plus branches that carry another name,
# and lines mostly used by the intercity train services (route relations of the 城际 operators).
IC_NAME = re.compile(r"城际|琶洲支线|^江门线$|^广深[ⅠⅡⅢⅣ]?线$")
IC_NETWORK = re.compile(r"城际")
SUBURBAN = re.compile(r"市郊|市域|金山铁路|绍兴城际|青平快线")     # suburban and intercity train services over national lines, matched on name and network
# Operators of route=train services that count as metro companies, and those that never do.
METRO_OPERATOR = re.compile(r"地铁|地鐵|轨道交通|軌道交通|广东城际|市域铁路运营|申通|港鐵|MTR")
RAIL_OPERATOR = re.compile(r"中国铁路|铁路局|广深铁路|国铁")
METRO_OP_SHARE = 0.5     # share of a line's track that metro-operated trains must use to move the line
METRO_OP_WHOLE = 0.9     # above this the whole line moves; below it only the stretch the trains run on
GBA_BOX = (111.3, 21.5, 115.5, 24.5)     # west, south, east, north: Guangdong-Hong Kong-Macao Greater Bay Area
# A second line over another line's track is drawn beside it when the two differ in class.
SHARED_LINE_KM = 30     # both lines must be real lines, not connectors
SHARED_MIN_KM = 6       # track km shared (a double line counts twice)
SHARED_SKIP = re.compile(r"联络|疏解|绕行|外绕|旧线|既有|货线|货车|^\(原\)|^（原）")
# OSM names every track after one line only (the official line names do not overlap), so a line that
# is commonly understood to run on over another line's track is listed here:
# (line drawn beside, line whose track it uses, the two stations the shared stretch runs between).
SHARED_KNOWN = [
    # Wuhan-Shiyan HSR: Hankou - Yunmeng East on the Wuhan-Xiaogan intercity line
    ("武西高速线", "武孝城际线", (114.2494, 30.6217), (113.7789, 31.0481)),
    # Longyan-Longchuan HSR: Longyan - Gutianhuizhi on the Ganzhou-Ruijin-Longyan line
    ("龙龙高速线", "赣瑞龙线", (117.0006, 25.1000), (116.7676, 25.1871)),
]
IC_SHARE = 0.4      # share of a line's Bay Area track used by intercity services
MINOR_LINE_KM = 10  # track km below which a named "line" is treated as a fragment of its neighbour
# A tunnel or a bridge is a structure on a line, however long: track named after one (八卦山隧道 and
# 龜山隧道 on the Taiwan high-speed line) belongs to the line on either side, which it otherwise cuts in two.
STRUCTURE = re.compile(r"(隧道|隧洞|大橋|大桥|特大桥|橋|桥)$")
LISTED_KM = 20      # conventional lines with at least this much track are listed in lines.json
STUB_DEG = 0.05     # ~5 km: a piece of a fast line this short and this far from the rest of the line is not in service
# Names reused all over the country (connectors, depot leads); such a name only identifies a line locally.
GENERIC = re.compile(r"联络|疏解|外绕|走行|动车所|动车段|出入|存车|牵出|渡线|站线|^[上下]行|^正线|^客车|^货车|机务|折返|环线$|^专用线$|^支线$")
MPH = 1.609344
YARD_SERVICE = {"yard", "siding", "crossover"}      # station and depot tracks; industrial spurs are left out
DEPOT_NAME = re.compile(r"动车所|动车段|车辆段|机务段|编组站|车辆基地|停车场|客技站|整备|折返段|车辆厂|机车厂|检修"
                        r"|[Dd]epot|TMD|T&RSMD|TRSMD|Sidings|Yard|Works|Carriage|Traincare|Maintenance", re.I)
# UK passenger operators: (pattern on the route's operator tag, brand, colour for dark imagery, weight).
# A line is coloured by the operator whose services cover most of its track; open-access, sleeper and
# cross-country operators run over other companies' main lines, so they count for less.
UK_OPERATORS = [
    (r"Translink|NI Railways|Northern Ireland Railways", "NI Railways", "#9be564", 1.0),
    (r"LNER|London North Eastern|Virgin Trains East Coast", "LNER", "#e4002b", 1.0),
    (r"Avanti", "Avanti West Coast", "#17b8a6", 1.0),
    (r"Great Western|^GWR$", "Great Western Railway", "#3fae6a", 1.0),
    (r"ScotRail", "ScotRail", "#4f8ff7", 1.0),
    (r"^Northern|Arriva Rail North|Arriva Trains North", "Northern", "#8f7bf2", 1.0),
    (r"Trans[Pp]ennine", "TransPennine Express", "#00c3f0", 0.9),
    (r"East Midlands", "East Midlands Railway", "#b06ab3", 1.0),
    (r"Greater Anglia|National Express", "Greater Anglia", "#ff8a80", 1.0),
    (r"South ?[Ee]astern", "Southeastern", "#39b6ff", 1.0),
    (r"Thameslink|^Southern|Great Northern|Gatwick Express", "Govia Thameslink Railway", "#ff5aa5", 1.0),
    (r"South Western|Island Line", "South Western Railway", "#6f8cff", 1.0),
    (r"Chiltern", "Chiltern Railways", "#35c5ff", 1.0),
    (r"West Midlands|London Midland|London Northwestern", "West Midlands Trains", "#ff8a1f", 1.0),
    (r"Trafnidiaeth Cymru|Transport for Wales|Arriva Trains Wales", "Transport for Wales", "#ff5252", 1.0),
    (r"Merseyrail", "Merseyrail", "#ffe14d", 1.0),
    (r"^c2c", "c2c", "#e64bd0", 1.0),
    (r"Transport for London|GTS Rail|London Overground|Elizabeth|Arriva Rail London", "Transport for London", "#a678e8", 1.0),
    (r"Heathrow Express", "Heathrow Express", "#c58af9", 1.0),
    (r"Eurostar", "Eurostar", "#ffd23f", 1.2),
    (r"Cross ?Country", "CrossCountry", "#e0457b", 0.45),
    (r"Caledonian Sleeper", "Caledonian Sleeper", "#5fd3bc", 0.2),
    (r"Lumo", "Lumo", "#4d7dff", 0.25),
    (r"Grand Central", "Grand Central", "#f5a623", 0.25),
    (r"Hull Trains", "Hull Trains", "#2bd1c8", 0.25),
]
OP_SHARE = 0.25     # an operator must serve at least this share of a line's track to colour it
# Lines whose OSM speed tags are too incomplete to classify: name -> (canonical name, class, km/h).
# High Speed 1 is built for 300 km/h; half of its track carries no maxspeed tag.
KNOWN_LINES = {("uk", "High Speed 1"): ("High Speed 1", "hsr350", 300),
               ("uk", "Channel Tunnel Rail Link"): ("High Speed 1", "hsr350", 300)}
# Display design classes are applied after continuous geometry has been built.
DISPLAY_CLASSES = {}


def speed_of(tags):
    for k in ("maxspeed", "maxspeed:design", "design_speed"):
        v = tags.get(k)
        if v:
            m = re.search(r"\d+", v)
            if m:
                return round(int(m.group()) * MPH) if "mph" in v else int(m.group())
    return None


def name_of(tags, country="cn"):
    return (tags.get("name") if country == "uk" else tags.get("name:zh") or tags.get("name")) or ""


SIMPLIFIED = str.maketrans("廣鐵綫線東馬灣機場門輕軌區環聯絡貨車專運濱園", "广铁线线东马湾机场门轻轨区环联络货车专运滨园")


def line_key(name, country, lon, lat):
    """Identity of the line a named track belongs to, tolerant of spelling variants."""
    if (country, name) in KNOWN_LINES:
        return (country, KNOWN_LINES[(country, name)][0])
    if country == "uk":
        return (country, name)
    name = name.translate(SIMPLIFIED)       # the Hong Kong section of a line is named in traditional characters
    k = re.sub(r"[ⅠⅡⅢⅣⅤIV]+线$", "线", name)
    k = re.sub(r"(上行|下行)线?$", "", k) or name
    k = re.sub(r"(高速铁路|高速线|高铁线|高铁)$", "高速", k)
    k = re.sub(r"(客运专线|客专线|客专)$", "客专", k)
    k = re.sub(r"(城际铁路|城际轨道交通|城际线|城际)$", "城际", k)
    k2 = re.sub(r"(铁路|线)$", "", k)
    k = k2 if len(k2) >= 2 else k
    return (country, k, round(lon * 2), round(lat * 2)) if GENERIC.search(name) else (country, k)


def uk_operator(tag):
    for pattern, brand, _, weight in UK_OPERATORS:
        if re.search(pattern, tag or ""):
            return brand, weight
    return None, 0


def speed_class(sp):
    return None if not sp else "hsr350" if sp >= 300 else "hsr250" if sp >= 250 else "hsr200"


def km(coords):
    s = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        dx = (x2 - x1) * math.cos(math.radians((y1 + y2) / 2))
        s += math.hypot(dx, y2 - y1) * 111.32
    return s


def runs_of(lines):
    """Join touching segments into runs of track."""
    merged = linemerge(MultiLineString(lines))
    return list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]


def rounded(geoms, tol, join=True, curve=None):
    """Simplified, rounded coordinate lists for the map layers. With join, the geometries are the
    pieces of one line and are made continuous. With curve (an entry of CURVE), the bends left by
    simplifying are drawn back as curves, so a line has no sharp angle at its vertices."""
    if join and len(geoms) > 1:
        geoms = stitch(runs_of(geoms))
    out = []
    for g in geoms:
        # Simplification must precede rounding and corner treatment. Rounding to five decimals
        # used to reintroduce metre-sized reversals at the joins, after they had been smoothed.
        # The reduction stage already removes duplicate tracks and turnback stubs. At this
        # stage preserve all remaining vertices: another run may end at one of them.
        co = smooth(list(g.simplify(tol, preserve_topology=False).coords), reverse=181)
        if len(co) > 1 and LineString(co).length > 0:
            out.append([[round(x, 6), round(y, 6)] for x, y in (curved(co, *curve, within=tol) if curve else co)])
    return out


def drawn_once(tracks, every=None):
    """tracks: {line: runs of track}. Returns {line: what to draw}, each double line drawn once
    (scripts/single_track.py) and the lines joined up again where they meet. A railway line is one
    line: its second track counts as an alignment of its own only when it runs kilometres apart.
    With every (all track there is), a line interrupted for a short way is carried through."""
    once = {k: [runs, one_track(runs, keep=0.05, apart=0.004, apart_min=0.01)] for k, runs in tracks.items()}
    closed = join_up(list(once.values()))
    if every:
        named = {k: v[1] for k, v in once.items() if k[1]}
        print("lines carried through a short interruption:", bridge(named, every), flush=True)
    print(f"drawn once: {sum(g.length for r in tracks.values() for g in r) * 100:.0f} -> "
          f"{sum(g.length for _, d in once.values() for g in d) * 100:.0f} (degrees x 100); gaps closed at junctions: {closed}")
    return {k: d for k, (_, d) in once.items()}


def merge_simplify(lines, tol, single=True, curve=None):
    """Join touching segments, simplify, and return (rounded coordinate lists, every run of track)."""
    parts = runs_of(lines)
    return rounded(one_track(parts) if single else parts, tol, join=single, curve=curve), parts


def same_way(chains):
    """Turn every piece of a path to run the same way, so a sideways offset stays on one side.
    The pieces come back in the order they were given."""
    order = sorted(range(len(chains)), key=lambda i: -chains[i].length)
    done, todo = {order[0]: chains[order[0]]}, order[1:]
    tips = {i: (chains[i].coords[0], chains[i].coords[-1]) for i in order}

    def apart(i, j):         # between the ends of two pieces: they follow one another end to end
        return min(math.hypot(a[0] - b[0], a[1] - b[1]) for a in tips[i] for b in tips[j])
    while todo:
        i, j = min(((i, j) for i in todo for j in done), key=lambda ij: apart(*ij))
        todo.remove(i)
        g, ref = chains[i], done[j]
        a, b = Point(g.coords[0]), Point(g.coords[-1])
        sa, sb = ref.project(a), ref.project(b)
        if abs(sa - sb) > 1e-9:
            flip = sa > sb
        elif sa > ref.length / 2:           # carries on past the end of the reference piece
            flip = a.distance(ref) > b.distance(ref)
        else:                               # leads up to its start
            flip = a.distance(ref) < b.distance(ref)
        done[i] = LineString(list(g.coords)[::-1]) if flip else g
    return [done[i] for i in range(len(chains))]


def single_path(groups, gap=0.0018, near=0.0003, keep=0.012, one_way=True):
    """One track's worth of a line drawn beside another, every piece running the same way.

    groups: the ways of each route relation, most important first; a double line has a relation
    and a track per direction. The first group is the path. Of a later group only track that
    leaves the path is added: a stretch that gets further than `gap` degrees from it (the other
    track is 5 m away on plain line, more at stations and junctions), followed back along its
    own track until it is within `near` of the path again, so the piece meets the path instead
    of stopping short of it. Such a piece is kept when it is long (a branch, or the two
    directions on separate alignments for more than `keep`), when it closes a hole between two
    loose ends of the path, or when it carries the path on past a loose end.
    With one_way=False a single group holds both tracks, and each run of track is taken in turn.
    """
    if not one_way:
        merged = linemerge(MultiLineString([co for lines in groups for co in lines]))
        groups = [[list(g.coords)] for g in sorted(merged.geoms if hasattr(merged, "geoms") else [merged], key=lambda g: -g.length)]
    geoms = lambda g: [x for x in (g.geoms if hasattr(g, "geoms") else [g]) if x.geom_type == "LineString" and x.length > 0]
    chains = []
    for lines in groups:
        lines = list({tuple(co): co for co in lines}.values())       # a relation can list a way twice
        parts = geoms(linemerge(MultiLineString(lines)))
        if not chains:
            chains += parts
            continue
        path = unary_union(chains)
        close, wide = path.buffer(near), path.buffer(gap)
        pieces = [x for g in parts for x in geoms(g.difference(close))]
        # pieces that touch end to end form one run of track
        group_of = list(range(len(pieces)))
        at = defaultdict(list)
        for i, x in enumerate(pieces):
            for c in (x.coords[0], x.coords[-1]):
                at[(round(c[0], 6), round(c[1], 6))].append(i)

        def root(i):
            while group_of[i] != i:
                group_of[i] = group_of[group_of[i]]
                i = group_of[i]
            return i
        for ids in at.values():
            for i in ids[1:]:
                group_of[root(i)] = root(ids[0])
        runs = defaultdict(list)
        for i in range(len(pieces)):
            runs[root(i)].append(i)
        loose = [(i, Point(c)) for i, g in enumerate(chains) for c in (g.coords[0], g.coords[-1])
                 if all(h.distance(Point(c)) > 1e-7 for j, h in enumerate(chains) if j != i)]
        for ids in runs.values():
            far = sum(pieces[i].difference(wide).length for i in ids)
            ends = [Point(k) for k, v in at.items() if len(v) == 1 and v[0] in ids]
            met = {i for e in ends for i, q in loose if e.distance(q) < 4 * near}
            if far > keep or len(met) >= 2 or (met and far > 0):
                chains += [pieces[i] for i in ids]
    return same_way(chains) if chains else []


def track_between(ws, a, b):
    """Coordinates along one track of a line from the track end nearest a to the one nearest b, or None."""
    adj = defaultdict(list)
    for w in ws:
        u, v = w["co"][0], w["co"][-1]
        adj[u].append((v, w["km"], w["co"]))
        adj[v].append((u, w["km"], w["co"][::-1]))
    if not adj:
        return None
    start = min(adj, key=lambda q: km([q, a]))
    dist, prev, heap = {start: 0.0}, {}, [(0.0, start)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for v, length, co in adj[u]:
            if d + length < dist.get(v, math.inf):
                dist[v], prev[v] = d + length, (u, co)
                heapq.heappush(heap, (d + length, v))
    goal = min(dist, key=lambda q: km([q, b]))
    if goal == start or km([goal, b]) > 2:
        return None
    legs = []
    while goal != start:
        goal, co = prev[goal]
        legs.append(co)
    legs.reverse()
    return legs[0] + [pt for co in legs[1:] for pt in co[1:]]


def carry_on(path, host_ways, guest_ways, limit=5.0, lead=0.25):
    """Carry a shared stretch on, at either end, to where the other line's own track begins, and a
    short way along it.

    A shared stretch is given by two stations, but the line that uses it leaves its own track at a
    junction some way before the station. Without this the line would stop at the junction and
    start again beside the track at the station. The lead-in along its own track lets the two
    drawn parts overlap, so the line reads as one that steps aside rather than one that breaks.
    """
    own = defaultdict(list)              # track end of the guest line -> its track leading away from there
    for w in guest_ways:
        own[w["co"][0]].append(w["co"])
        own[w["co"][-1]].append(w["co"][::-1])
    adj = defaultdict(list)
    for w in host_ways:
        adj[w["co"][0]].append((w["co"][-1], w["km"], w["co"]))
        adj[w["co"][-1]].append((w["co"][0], w["km"], w["co"][::-1]))
    for at_start in (True, False):
        start = path[0] if at_start else path[-1]
        dist, prev, heap, goal = {start: 0.0}, {}, [(0.0, start)], None
        while heap:
            d, u = heapq.heappop(heap)
            if u in own:
                goal = u
                break
            if d > dist[u] or d > limit:
                continue
            for v, length, co in adj.get(u, ()):
                if d + length < dist.get(v, math.inf):
                    dist[v], prev[v] = d + length, (u, co)
                    heapq.heappush(heap, (d + length, v))
        if goal is None:
            continue
        more, node = [], goal
        while node != start:
            node, co = prev[node]
            more = co + more[1:] if more else list(co)
        tail, left = [], lead               # a short way along the guest line's own track
        for (x1, y1), (x2, y2) in zip(own[goal][0], own[goal][0][1:]):
            seg = km([(x1, y1), (x2, y2)])
            if seg >= left:
                f = left / seg
                tail.append((x1 + (x2 - x1) * f, y1 + (y2 - y1) * f))
                break
            tail.append((x2, y2))
            left -= seg
        more = (more or [goal]) + tail
        path = more[::-1] + list(path[1:]) if at_start else list(path[:-1]) + more
    return path


def geometry(lines):
    return {"type": "MultiLineString", "coordinates": lines} if len(lines) > 1 else {"type": "LineString", "coordinates": lines[0]}


def write(name, feats):
    p = OUT / name
    p.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":")))
    print(f"{name}: {len(feats)} features, {p.stat().st_size / 1e6:.2f} MB")


# ---------------------------------------------------------------- load
# The pickles are written locally by scripts/extract_osm.py, so loading them is safe here.
ex = pickle.load(open(RAW / "extract.pkl", "rb"))
ways = [(wid, t, co, "cn") for wid, t, co in ex["ways"]]
stations_raw = [(t, lon, lat, "cn") for t, lon, lat in ex["stations"]]
places_raw = [(kind, t, lon, lat, "cn") for kind, t, lon, lat in ex.get("places", [])]
# The United Kingdom is not processed here any more: like Japan it has a script and layers of its
# own (scripts/process_uk.py), and site.json's "uk" only tells the page to load them. The UK
# branches further down get no input and do nothing; they are what the with-uk branch used.
WITH_UK = False
uk = {"ways": [], "stations": [], "relations": [], "places": []}
ways += [(wid, t, co, "uk") for wid, t, co in uk["ways"]]
stations_raw += [(t, lon, lat, "uk") for t, lon, lat in uk["stations"]]
places_raw += [(kind, t, lon, lat, "uk") for kind, t, lon, lat in uk.get("places", [])]

# Keep the source cache intact. Corrections feed both the drawn layers and routing input.
status_rules = load_rules(OUT / "rail_status_overrides.json")
status_matches, status_changes, corrected_ways = Counter(), [], []
for wid, t, co, country in ways:
    fixed, evidence = corrected_tags(t, co, status_rules) if country == "cn" else (t, None)
    if evidence:
        status_matches[evidence] += 1
        if fixed != t:
            status_changes.append({"way": wid, "name": name_of(t), "rule": evidence,
                                   "before": t.get("railway"), "after": fixed.get("railway"), "track_km": km(co)})
    corrected_ways.append((wid, fixed, co, country))
ways = corrected_ways
freshness_dir = ROOT / "output" / "freshness"
freshness_dir.mkdir(parents=True, exist_ok=True)
(freshness_dir / "status-corrections.json").write_text(json.dumps(
    {"sources": ex.get("sources", []), "matches": dict(status_matches), "changes": status_changes},
    ensure_ascii=False, indent=2))
print("source-backed status changes:", dict(Counter((r["before"], r["after"]) for r in status_changes
                                                    if r["before"] != r["after"])), flush=True)


# Metro lines are grouped by province (two cities' "Line 1" stay apart); the outlines are the ones
# cached by scripts/build_border.py. They are GCJ-02, a few hundred metres off, which is close enough here.
prov_polys = {}
prov_file = RAW / "border" / "100000_full.json"
if prov_file.exists():
    for f in json.load(open(prov_file))["features"]:
        code = str(f["properties"]["adcode"])
        if code.isdigit():
            g = shape(f["geometry"]).buffer(0)
            prov_polys[code[:2]] = (g.bounds, prep(g))
else:
    print("no province outlines (run scripts/build_border.py); metro lines are skipped")


def in_gba(lon, lat):
    return GBA_BOX[0] <= lon <= GBA_BOX[2] and GBA_BOX[1] <= lat <= GBA_BOX[3]


def region_of(lon, lat):
    """Province code ('11' Beijing, '44' Guangdong, '81' Hong Kong...) of a point, None at sea or abroad."""
    for k, (b, g) in prov_polys.items():
        if b[0] <= lon <= b[2] and b[1] <= lat <= b[3] and g.contains(Point(lon, lat)):
            return k
    return None


# ---------------------------------------------------------------- route relations
masters = {}
for rid, t, members in ex["relations"]:
    if t.get("type") == "route_master":
        for mtype, ref in members:
            if mtype == "r":
                masters[ref] = t


def zh(s):
    """Chinese part of a bilingual name: '南港島綫 South Island Line' -> '南港島綫'."""
    s = re.sub("[\ufe0f\u20e3]", "", s or "")           # keycap digits typed as emoji
    s = re.split(r"[:：(（]|→|➡|=>|-->|⇒", s)[0].strip()
    if re.search(r"[一-鿿]", s):
        s = re.sub(r"\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'\-]*$", "", s)
        s = re.sub(r"^[A-Za-z .'\-]*[a-z][A-Za-z .'\-]*(?=[一-鿿])", "", s)
        s = re.sub(r"\s+", "", s).replace("臺", "台")
    return s


def readable_on_dark(col):
    """Lift a dark line colour (Beijing suburban navy) so it shows on dark satellite imagery."""
    if not col:
        return col
    import colorsys
    r, g, b = (int(col[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, l, sat = colorsys.rgb_to_hls(r, g, b)
    if l >= 0.5:
        return col
    r, g, b = colorsys.hls_to_rgb(h, 0.64, max(sat, 0.55))
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def colour_of(*tags):
    for t in tags:
        c = (t or {}).get("colour", "").strip()
        if re.fullmatch(r"#[0-9a-fA-F]{6}", c):
            return c.lower()
        if re.fullmatch(r"#[0-9a-fA-F]{3}", c):
            return "#" + "".join(ch * 2 for ch in c[1:]).lower()
    return None


def cn_number(s):
    """'五' -> 5, '十二' -> 12, '二十一' -> 21."""
    if "十" not in s:
        return int("".join(str(CN_DIGIT[c]) for c in s))
    tens, _, ones = s.partition("十")
    return (CN_DIGIT[tens] if tens else 1) * 10 + (CN_DIGIT[ones] if ones else 0)


def metro_line_name(m, t):
    """'广州地铁3号线' from master/route tags; the network disambiguates 'Line 3' of different cities."""
    alias = METRO_ALIAS.get(m.get("name:en") or t.get("name:en"))
    if alias:
        return alias
    net = zh(m.get("network") or t.get("network") or "")
    cands = [c for c in (m.get("name:zh"), m.get("name"), t.get("name:zh"), t.get("name")) if c and zh(c) != net]
    raw = next((c for c in cands if re.search(r"[一-鿿]", c)), None) or next(iter(cands), "")
    line = re.sub(r"^(地铁|轻轨|磁悬浮)(?=.)", "", zh(raw))
    line = re.sub(r"(普通車|直達車|-?[上下]行)$", "", line)
    ref = (m.get("ref") or t.get("ref") or "").strip()
    if ref.isdigit() and re.match(rf"{ref}\s", raw.strip()):
        line = ref               # "2 白云北路 - 中兴路": a number followed by the termini
    if not re.search(r"[一-鿿]", line) and not line.isdigit():
        return ""                # "A>B" in Latin letters only: not a line name
    line = re.sub(r"([一二三四五六七八九十]+)(?=号线)", lambda g: str(cn_number(g.group(1))), line)
    if line[-1].isdigit():
        line += "号线"
    if not net or net in line or line.startswith(net[:2]):
        return line
    k = next((k for k in range(min(len(net), len(line)), 0, -1) if net.endswith(line[:k])), 0)
    if k:
        return net + line[k:]    # 台北捷運 + 捷運板南線 -> 台北捷運板南線
    return line if METRO_SYSTEM.search(line) else net + line


way_metro = {}       # way id -> (line name, colour)
metro_rels = []      # (line name, colour, way ids in order): one per route relation, i.e. per direction or service pattern
way_suburb = {}      # national-rail way id -> (suburban service name, colour); bureau-operated
suburb_rels = defaultdict(list)   # service name -> [(colour, ordered way ids)], one entry per route relation
way_metro_op = {}    # national-rail way id -> colour; used by trains a metro company operates
ic_rel_ways = set()  # ways used by Greater Bay Area intercity train services
rail_rels = []       # (line name, way ids) from route=railway relations: the track a named line runs over
for rid, t, members in ex["relations"]:
    if t.get("type") != "route":
        continue
    m = masters.get(rid, {})
    if t.get("route") == "railway":
        nm = zh(t.get("name:zh") or t.get("name") or "")
        if nm:
            rail_rels.append((nm, [ref for mtype, ref in members if mtype == "w"]))
    elif t.get("route") in METRO_RAIL:
        info = (metro_line_name(m, t), colour_of(m, t))
        if NOT_METRO.search(info[0] or ""):
            continue             # its track is claimed by the real line's own relation instead
        for mtype, ref in members:
            if mtype == "w":
                way_metro.setdefault(ref, info)
        if info[0]:
            metro_rels.append((info[0], info[1], [ref for mtype, ref in members if mtype == "w"]))
    elif t.get("route") == "train":
        net = " ".join(filter(None, (m.get("network"), t.get("network"), t.get("operator"), m.get("name"), t.get("name"))))
        if IC_NETWORK.search(net):
            ic_rel_ways.update(ref for mtype, ref in members if mtype == "w")
        operator = " ".join(filter(None, (t.get("operator"), m.get("operator"))))
        if METRO_OPERATOR.search(operator) and not RAIL_OPERATOR.search(operator):
            for mtype, ref in members:
                if mtype == "w":
                    way_metro_op.setdefault(ref, colour_of(m, t))
        elif SUBURBAN.search(" ".join(filter(None, (m.get("network"), t.get("network"), m.get("name"), t.get("name"))))):
            info = (zh(m.get("name:zh") or m.get("name") or t.get("name:zh") or t.get("name")), colour_of(m, t))
            suburb_rels[info[0]].append((info[1], [ref for mtype, ref in members if mtype == "w"]))
            for mtype, ref in members:
                if mtype == "w":
                    way_suburb.setdefault(ref, info)



def same_colour(a, b):
    """Two lines in (nearly) one colour: a through service under two names, drawn in one place."""
    if not a or not b:
        return a == b
    return sum(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) for i in (1, 3, 5)) < 40


uk_masters = {}
for rid, t, members in uk["relations"]:
    if t.get("type") == "route_master":
        for mtype, ref in members:
            if mtype == "r":
                uk_masters[ref] = t
uk_way_ops = defaultdict(dict)       # way id -> {brand: weight}
for rid, t, members in uk["relations"]:
    if t.get("type") == "route" and t.get("route") == "train":
        brand, weight = uk_operator(t.get("operator") or uk_masters.get(rid, {}).get("operator"))
        if brand:
            for mtype, ref in members:
                if mtype == "w":
                    uk_way_ops[ref][brand] = weight

# ---------------------------------------------------------------- split ways into rail / metro / build / yards
rail, build, metro_ways, yard_tracks, suburb_ways = [], [], [], [], []
for wid, t, co, country in ways:
    r = t.get("railway")
    # Track tagged as siding or yard that a metro line's route relation runs over is running track
    # all the same: the platform tracks of a station (Sunny Bay), the way into a terminus (Hong Kong).
    if (r == "rail" or r in METRO_RAIL) and t.get("service") and not (r in METRO_RAIL and wid in way_metro):
        if t["service"] in YARD_SERVICE:
            yard_tracks.append(co)
        if r == "rail" and country == "cn" and wid in way_suburb:
            suburb_ways.append((wid, co))     # platform loops the service actually runs through
    elif r in METRO_RAIL or (r == "rail" and wid in way_metro and country == "cn"):
        if t.get("construction") and wid not in way_metro:
            continue                          # mapped as metro track but still marked as being built, and in no line's relation
        if t.get("usage") == "tourism" or (t.get("usage") in SKIP_USAGE and wid not in way_metro):
            continue                          # a sightseeing line is not a metro (辽源, 丽江, 清远); test and works track is not a line
        metro_ways.append((wid, t, co))       # includes heavy-rail metro such as MTR East Rail, Guangzhou 18/22
    elif r == "rail":
        if t.get("usage") in SKIP_USAGE:
            continue
        if country == "cn" and wid in way_suburb:
            suburb_ways.append((wid, co))     # the track stays a rail line; the service is drawn on top
        sp = speed_of(t)
        rail.append({"id": wid, "n": name_of(t, country), "sp": sp, "g": country, "co": co, "km": km(co),
                     "ops": uk_way_ops.get(wid) if country == "uk" else None,
                     "fast": sp >= 200 if sp else t.get("highspeed") == "yes",
                     "conv": "main" if t.get("usage") == "main" else "branch",
                     "gba": country == "cn" and in_gba(*co[0])})
    elif r == "construction" and (t.get("construction") == "rail" or t.get("construction:railway") == "rail") and not t.get("service"):
        sp = speed_of(t)
        build.append((name_of(t, country), t.get("highspeed") == "yes" or bool(sp and sp >= 200), co))
print(f"rail ways: {len(rail)}, under construction: {len(build)}, metro ways: {len(metro_ways)}, yard tracks: {len(yard_tracks)}")

# ---------------------------------------------------------------- group tracks into lines
for w in rail:
    w["key"] = w["key0"] = line_key(w["n"], w["g"], *w["co"][0]) if w["n"] else None
# Very short "lines" are mostly tracks named after a bridge, tunnel or junction; like unnamed
# track they should follow the line they sit in rather than form a line of their own.
key_km = Counter()
for w in rail:
    if w["key"]:
        key_km[w["key"]] += w["km"]
for w in rail:
    if w["key"] and (key_km[w["key"]] < MINOR_LINE_KM or STRUCTURE.search(w["n"])) and (w["g"], w["n"]) not in KNOWN_LINES:
        w["key"] = None

# Unnamed stretches follow the line they join: the same line at both ends, or a short spur off one line.
ends = defaultdict(list)
for i, w in enumerate(rail):
    ends[w["co"][0]].append(i)
    ends[w["co"][-1]].append(i)
adopted = 0
for _ in range(4):
    for i, w in enumerate(rail):
        if w["key"]:
            continue
        a = {rail[j]["key"] for j in ends[w["co"][0]] if j != i and rail[j]["key"]}
        b = {rail[j]["key"] for j in ends[w["co"][-1]] if j != i and rail[j]["key"]}
        both = a & b
        pick = next(iter(both)) if len(both) == 1 else next(iter(a | b)) if len(a | b) == 1 and w["km"] < 5 else None
        if pick:
            w["adopt"] = pick
            adopted += 1
    for w in rail:
        if "adopt" in w:
            w["key"] = w.pop("adopt")
for w in rail:           # short named lines that joined nothing keep their own identity
    if not w["key"] and w["key0"]:
        w["key"] = w["key0"]
orphans = sum(w["km"] for w in rail if not w["key"])
print(f"unnamed stretches attached to a neighbouring line: {adopted}; still unnamed: {orphans:.0f} km of {sum(w['km'] for w in rail):.0f}")

stats = defaultdict(lambda: {"total": 0.0, "fast": 0.0, "cls": Counter(), "conv": Counter(), "names": Counter(),
                             "grades": Counter(), "ungraded_fast": 0.0,
                             "gba": 0.0, "gba_rel": 0.0, "mop": 0.0, "mcol": Counter()})
for w in rail:
    if not w["key"]:
        continue
    st = stats[w["key"]]
    st["total"] += w["km"]
    st["conv"][w["conv"]] += w["km"]
    if w["n"]:
        st["names"][w["n"]] += w["km"]
    if w["fast"]:
        st["fast"] += w["km"]
        if w["sp"]:
            st["cls"][speed_class(w["sp"])] += w["km"]
            st["grades"][speed_class(w["sp"])] += w["km"]
        else:
            st["ungraded_fast"] += w["km"]
    else:
        st["grades"][w["conv"]] += w["km"]
    if w["gba"]:
        st["gba"] += w["km"]
        if w["id"] in ic_rel_ways:
            st["gba_rel"] += w["km"]
    if w["g"] == "cn" and w["id"] in way_metro_op:
        st["mop"] += w["km"]
        if way_metro_op[w["id"]]:
            st["mcol"][way_metro_op[w["id"]]] += w["km"]

# ---------------------------------------------------------------- one class per line
line_cls, line_name, ic_keys = {}, {}, set()
classification_audit = []
for key, st in stats.items():
    line_name[key] = st["names"].most_common(1)[0][0]
    in_gba = st["gba"] >= 0.5 * st["total"]
    known = KNOWN_LINES.get((key[0], line_name[key]))
    display = DISPLAY_CLASSES.get(key)
    if known:
        line_name[key], line_cls[key] = known[0], known[1]
    elif display:
        line_cls[key] = display
    elif in_gba and (any(IC_NAME.search(n) for n in st["names"]) or st["gba_rel"] >= IC_SHARE * st["gba"]):
        line_cls[key] = "hsr200"
        ic_keys.add(key)
    else:
        line_cls[key] = principal_class(st["grades"], st["ungraded_fast"])
    if st["fast"] >= 0.5 * st["total"]:
        previous = st["cls"].most_common(1)[0][0] if st["cls"] else "hsr250"
    else:
        previous = st["conv"].most_common(1)[0][0]
    if known or key in ic_keys:
        previous = line_cls[key]  # Verified overrides are independent of the voting policy.
    classification_audit.append({"name": line_name[key], "country": key[0], "track_km": st["total"],
                                 "grades_km": dict(grade_votes(st["grades"], st["ungraded_fast"])),
                                 "ungraded_fast_km": st["ungraded_fast"], "previous": previous,
                                 "class": line_cls[key], "override": bool(known or display or key in ic_keys),
                                 "override_reason": "user map policy 2026-10-07" if display else None})
audit_dir = ROOT / "output" / "classification"
audit_dir.mkdir(parents=True, exist_ok=True)
(audit_dir / "line-grades.json").write_text(json.dumps(classification_audit, ensure_ascii=False, indent=2))
print("principal grade changes:", [(row["name"], row["previous"], row["class"])
                                    for row in classification_audit if row["previous"] != row["class"]], flush=True)
changed = Counter()
for w in rail:
    own = (speed_class(w["sp"]) or "hsr250") if w["fast"] else w["conv"]
    if w["key"]:
        w["c"], w["n"] = line_cls[w["key"]], line_name[w["key"]]
        if w["c"] != own and w["key"] not in ic_keys:
            changed[f"{own} -> {w['c']}"] += w["km"]
    else:
        w["c"] = own
print("Bay Area intercity lines:", sorted(line_name[k] for k in ic_keys))
print("classes:", dict(Counter((w["g"], w["c"]) for w in rail)))
print("track km whose own tags differ from their line's class:", {k: round(v) for k, v in changed.most_common()})

# ---------------------------------------------------------------- a second line over the same track
# A route=railway relation lists the track a named line runs over. Track in it that carries another
# line's name and class is shared: it keeps its own line, and the relation's line (an intercity or
# high-speed line) is drawn beside it.
# When each of two relations includes track named after the other, the names are one railway
# (拉林线 is a section of 川藏铁路), not two lines, and nothing is added.
by_id = {w["id"]: w for w in rail if w["g"] == "cn"}
claims = defaultdict(lambda: defaultdict(list))      # guest line -> host line -> shared ways
overlap = defaultdict(Counter)                       # relation's line -> line named on the track -> km
for nm, wids in rail_rels:
    ws = [by_id[i] for i in wids if i in by_id]
    if not ws or GENERIC.search(nm) or SHARED_SKIP.search(nm):
        continue
    key = line_key(nm, "cn", *ws[0]["co"][0])
    if line_cls.get(key) is None or stats[key]["total"] < SHARED_LINE_KM:
        continue
    for w in ws:
        host = w["key"]
        if host and host != key:
            overlap[key][host] += w["km"]
        if not host or host == key or w["c"] == line_cls[key] or not line_cls[key].startswith("hsr"):
            continue
        if stats[host]["total"] < SHARED_LINE_KM or SHARED_SKIP.search(line_name[host]) or GENERIC.search(line_name[host]):
            continue
        claims[key][host].append(w)
shared = []          # (guest line, class, host names, track, True when the track is already one path)
for key, hosts in claims.items():
    ws, on = [], []
    for host, hw in hosts.items():
        if overlap[host][key] >= 1:
            continue                                  # mutual: one railway under two names
        if sum(w["km"] for w in hw) >= SHARED_MIN_KM:
            ws += hw
            on.append(line_name[host])
    # the shared stretch has to carry on from the line's own track; a relation that lists track
    # somewhere else altogether is a mapping slip
    if ws and any(rail[j]["key"] == key for w in ws for end in (w["co"][0], w["co"][-1]) for j in ends[end]):
        shared.append((key, line_cls[key], on, [w["co"] for w in ws], False))
names = {(k[0], n): k for k, n in line_name.items()}
for guest, host, a, b in SHARED_KNOWN:
    key, hkey = names.get(("cn", guest)), names.get(("cn", host))
    path = track_between([w for w in rail if w["key"] == hkey], a, b) if key and hkey else None
    if path:
        path = carry_on(path, [w for w in rail if w["key"] == hkey], [w for w in rail if w["key"] == key])
    if not path:
        print("known shared stretch not found in the data:", guest, "on", host)
    elif line_cls[key] != line_cls[hkey] and all(k != key for k, *_ in shared):
        shared.append((key, line_cls[key], [host], [path], True))
print("lines drawn beside another line where they share its track:",
      {f"{line_name[k]} ({c})": f"{'、'.join(on)} {sum(km(co) for co in lines) / (1 if one else 2):.0f} km" for k, c, on, lines, one in shared})

# ---------------------------------------------------------------- one operator per UK line
op_cover = defaultdict(Counter)      # line -> brand -> km of its track served
op_score = defaultdict(Counter)
line_total = Counter()
for i, w in enumerate(rail):
    if w["g"] != "uk":
        continue
    lk = w["key"] or ("way", i)
    line_total[lk] += w["km"]
    for brand, weight in (w["ops"] or {}).items():
        op_cover[lk][brand] += w["km"]
        op_score[lk][brand] += w["km"] * weight
line_op = {}
for lk, score in op_score.items():
    brand = score.most_common(1)[0][0]
    if op_cover[lk][brand] >= OP_SHARE * line_total[lk]:
        line_op[lk] = brand
op_km = Counter()
for i, w in enumerate(rail):
    w["o"] = line_op.get(w["key"] or ("way", i)) if w["g"] == "uk" else None
    if w["o"]:
        op_km[w["o"]] += w["km"]

# ---------------------------------------------------------------- lines run by metro companies
metro_run = {key: (st["mcol"].most_common(1)[0][0] if st["mcol"] else None)
             for key, st in stats.items() if st["mop"] >= METRO_OP_SHARE * st["total"] and st["mop"] > 3}
print("lines shown with the metros because a metro company runs them:", sorted(line_name[k] for k in metro_run))
print("used in part by metro-run trains, left as rail lines:",
      {line_name[k]: f"{st['mop'] / st['total']:.0%} of {st['total']:.0f} km" for k, st in stats.items() if k not in metro_run and st["mop"] > 10})
metro_whole = {key for key in metro_run if stats[key]["mop"] >= METRO_OP_WHOLE * stats[key]["total"]}
print("of these, only the stretch the trains run on:", sorted(line_name[k] for k in metro_run if k not in metro_whole))
moved = []           # (name, colour, coords) for the metro layer

# ---------------------------------------------------------------- rail layers
groups = defaultdict(list)
for w in rail:
    by_metro = w["key"] in metro_whole or (w["key"] in metro_run and w["id"] in way_metro_op)
    w["m"] = metro_run[w["key"]] or METRO_DEFAULT if by_metro else None
    groups[(w["c"], w["n"], w["g"], w["o"], by_metro)].append(w)
# Classified tracks for scripts/build_graph.py, which builds the routing network: (class, line,
# country, coordinates, colour). Track a metro company runs its trains on is class "mrail": it
# keeps its place in the railway network, but is timed and boarded like the urban service it is.
with open(RAW / "routing_input.pkl", "wb") as f:
    pickle.dump([("mrail" if w["m"] else w["c"], w["n"], w["g"], w["co"], w["m"]) for w in rail]
                + [("svc", "", "", co, None) for co in yard_tracks], f, protocol=pickle.HIGHEST_PROTOCOL)
feats = defaultdict(list)
track_km = Counter()
line_info = {}
fast_geoms, all_geoms = [], []
tracks = {k: runs_of([w["co"] for w in ws]) for k, ws in groups.items()}
once = drawn_once({k: runs for k, runs in tracks.items() if not k[4]},      # lines moved to the metro layer are drawn there
                  every=[w["co"] for w in rail if w["g"] == "cn"] + yard_tracks)
stubs = []           # (line name, geometry): track laid ahead of a line that has not reached it yet
for (cls, nm, country, op, by_metro), ws in groups.items():
    parts = tracks[(cls, nm, country, op, by_metro)]
    drawn = [] if by_metro else once[(cls, nm, country, op, by_metro)]
    if nm and cls.startswith("hsr") and len(drawn) > 1:
        # Platforms and approach tracks are often built years before a new line arrives (怀兴城际线
        # inside 北京通州 station). A short piece far from the rest of its line is drawn as under construction.
        drawn = runs_of(drawn)
        alone = [g for g in drawn if g.length < STUB_DEG and all(g.distance(h) > STUB_DEG for h in drawn if h is not g)]
        stubs += [(nm, g) for g in alone]
        drawn = [g for g in drawn if not any(g is a for a in alone)]
    simp = rounded(drawn, TOL[cls], curve=CURVE[cls])
    length = sum(w["km"] for w in ws)
    track_km[(country, cls)] += length
    listed = cls.startswith("hsr")
    all_geoms += parts               # stations on these lines stay rail stations either way
    if listed:
        fast_geoms += parts
    if by_metro:
        moved += [(nm, metro_run[ws[0]["key"]], w["co"]) for w in ws]
        continue
    if not simp:
        continue
    speeds = Counter()
    for w in ws:
        if w["sp"] and speed_class(w["sp"]) == cls:
            speeds[w["sp"]] += w["km"]
    sp = speeds.most_common(1)[0][0] if speeds and listed else None
    if (country, nm) in KNOWN_LINES:
        sp = KNOWN_LINES[(country, nm)][2]
    props = {"c": cls}
    if nm:
        props["n"] = nm
    if sp:
        props["s"] = sp
    if op:
        props["o"] = op
    feats["hsr" if listed else "conv"].append({"type": "Feature", "properties": props, "geometry": geometry(simp)})
    if nm and (listed or (length >= LISTED_KM and not GENERIC.search(nm))):     # lines.json: what can be searched and framed
        xs = [p[0] for line in simp for p in line]
        ys = [p[1] for line in simp for p in line]
        li = line_info.setdefault(nm, {"n": nm, "g": country, "bbox": [180, 90, -180, -90], "tk": 0, "by": {}})
        li["bbox"] = [min(li["bbox"][0], min(xs)), min(li["bbox"][1], min(ys)), max(li["bbox"][2], max(xs)), max(li["bbox"][3], max(ys))]
        li["tk"] += length
        prev = li["by"].get(cls, (0, None))
        li["by"][cls] = (prev[0] + length, sp or prev[1])
        if op:
            li["o"] = op

build_groups = defaultdict(list)
for nm, hs, co in build:
    build_groups[(nm, hs)].append(co)
for nm, g in stubs:
    build_groups[(nm, True)].append(list(g.coords))
print("pieces of fast lines drawn as under construction (laid ahead of the line):", sorted(Counter(nm for nm, _ in stubs).items()))
for (nm, hs), lines in build_groups.items():
    simp, _ = merge_simplify(lines, TOL["build"], curve=CURVE["build"])
    if simp:
        props = {"c": "build"}
        if nm:
            props["n"] = nm
        if hs:
            props["h"] = 1
        feats["build"].append({"type": "Feature", "properties": props, "geometry": geometry(simp)})
for key, cls, on, lines, one in shared:
    if key in metro_run:
        continue
    out = [[[round(x, 6), round(y, 6)] for x, y in curved(list(g.simplify(TOL[cls], preserve_topology=False).coords), *CURVE[cls], within=TOL[cls])]
           for g in ([LineString(lines[0])] if one else single_path([lines], one_way=False))]
    if out:
        feats["shared"].append({"type": "Feature", "properties": {"c": cls, "n": line_name[key], "on": "、".join(on)},
                                "geometry": geometry(out)})
        li = line_info.get(line_name[key])
        if li:                   # selecting the line frames this stretch as well
            xs, ys = [p[0] for line in out for p in line], [p[1] for line in out for p in line]
            li["bbox"] = [min(li["bbox"][0], min(xs)), min(li["bbox"][1], min(ys)), max(li["bbox"][2], max(xs)), max(li["bbox"][3], max(ys))]
for bucket in ("hsr", "conv", "build", "shared"):
    write(f"rail_{bucket}.geojson", feats[bucket])

# ---------------------------------------------------------------- metro lines
# A metro line is drawn as a line, not as track. A route relation lists, in order, the track one
# direction of a line runs over from end to end, so the longest relation of a line is the line: one
# continuous path. Its other relations (the other direction, short workings, branches) only add
# what leaves that path. This is how a transit map is made from operators' route shapes, and it
# means a line cannot come out drawn twice or with a hole where its two tracks are mapped unevenly.
# Lines are then compared with each other: where one runs along another, on the same track or
# beside it in the same corridor, the two are drawn side by side along one of them.
RIDE = 0.0005        # ~55 m: a line this close to another one and running the same way is in its corridor
RIDE_LOOSE = 0.0016  # ~175 m: once in a corridor a line stays in it while it is this close (tracks spread at stations)
RIDE_MIN = 0.006     # ~650 m: shorter company (a crossing, a shared station) is not drawn side by side
RIDE_STEP = 0.0004
RIDE_SLIVER = 0.0012 # ~130 m: a shorter piece between two shared stretches, off to the side of both, is noise at a junction
BARE = re.compile(r"[\dA-Za-z]+号?[线綫線]?")       # "15号线" names a line only within its city


def heading(g, at, d=0.0002):
    a, b = g.interpolate(max(at - d, 0)), g.interpolate(min(at + d, g.length))
    d = math.hypot(b.x - a.x, b.y - a.y)
    return ((b.x - a.x) / d, (b.y - a.y) / d) if d else (0, 0)


metro_co = {wid: co for wid, t, co in metro_ways}
metro_light = {wid for wid, t, co in metro_ways if t.get("railway") in ("light_rail", "tram")}
raw = defaultdict(lambda: {"col": Counter(), "rels": [], "extra": []})      # line name as the relations give it
for nm, col, wids in metro_rels:
    ws = [w for w in dict.fromkeys(wids) if w in metro_co]
    if ws:
        raw[nm]["rels"].append(ws)
        if col:
            raw[nm]["col"][col] += len(ws)
in_rel = {w for d in raw.values() for ws in d["rels"] for w in ws}
line_regs = defaultdict(Counter)        # line -> provinces its track lies in
touch = defaultdict(set)                # track end -> lines that end or pass there
for nm, d in raw.items():
    for ws in d["rels"]:
        for w in ws:
            co = metro_co[w]
            line_regs[nm][region_of(*co[0])] += len(co)
            touch[co[0]].add(nm)
            touch[co[-1]].add(nm)
# Track in no relation (a newly opened stretch, a turnback) follows the line it carries the name of or
# is attached to: the same line at both ends, or a longer piece hanging off one line. What is left
# under a name of its own is a line without a relation yet; unnamed leftovers are not drawn.
known = {re.sub(r"\s+", "", nm): nm for nm in raw}
loose = defaultdict(list)
for wid, t, co in metro_ways:
    if wid in in_rel:
        continue
    own, reg = zh(t.get("name:zh") or t.get("name") or ""), region_of(*co[0])
    nm = known.get(own)
    if nm is None and len(own) >= 3:
        full = {v for k, v in known.items() if k.endswith(own) and line_regs[v].get(reg)}
        nm = next(iter(full)) if len(full) == 1 else None
    if nm:
        raw[nm]["extra"].append(co)
        touch[co[0]].add(nm)
        touch[co[-1]].add(nm)
    elif reg:
        loose[(reg, own)].append(co)
adopted_metro = 0
# A named stretch that is attached to one line only is a part of that line under another spelling
# or not yet in its relation (金华轨道交通义东线 inside 金义东线义东段): it goes to that line whole, so
# the line does not change colour partway.
for key in [k for k in loose if k[1]]:
    at = defaultdict(list)
    for i, co in enumerate(loose[key]):
        at[co[0]].append(i)
        at[co[-1]].append(i)
    group = list(range(len(loose[key])))

    def root(i):
        while group[i] != i:
            group[i] = group[group[i]]
            i = group[i]
        return i
    for ids in at.values():
        for i in ids[1:]:
            group[root(i)] = root(ids[0])
    stretches = defaultdict(list)
    for i in range(len(group)):
        stretches[root(i)].append(i)
    rest = []
    for ids in stretches.values():
        met = set().union(*(touch.get(c, set()) for i in ids for c in (loose[key][i][0], loose[key][i][-1])))
        if len(met) == 1:
            line = next(iter(met))
            for i in ids:
                raw[line]["extra"].append(loose[key][i])
                touch[loose[key][i][0]].add(line)
                touch[loose[key][i][-1]].add(line)
            adopted_metro += len(ids)
        else:
            rest += [loose[key][i] for i in ids]
    loose[key] = rest
for _ in range(3):
    for key in list(loose):
        rest = []
        for co in loose[key]:
            a, b = touch.get(co[0], set()), touch.get(co[-1], set())
            # the one line at both ends, or a longer piece hanging off one line; track between two
            # ends that several lines share, in no relation, is not any one line's (a crossover)
            both = a & b
            pick = next(iter(both)) if len(both) == 1 else next(iter(a | b)) if not both and len(a | b) == 1 and km(co) >= 1 else None
            if pick is None:
                rest.append(co)
                continue
            raw[pick]["extra"].append(co)
            touch[co[0]].add(pick)
            touch[co[-1]].add(pick)
            adopted_metro += 1
        loose[key] = rest
# What is still left under a name of its own but lies along a single line for most of its length is
# that line's other track, not yet in its relation and named differently (金华轨道交通义东线 beside
# 金义东线义东段). It joins that line, so no second line in another colour appears beside it.
rel_geoms, rel_owner = [], []
for nm, d in raw.items():
    for co in [metro_co[w] for ws in d["rels"] for w in ws] + d["extra"]:
        rel_geoms.append(LineString(co))
        rel_owner.append(nm)
rel_tree = STRtree(rel_geoms) if rel_geoms else None
beside_metro = []
for key in [k for k in loose if k[1] and loose[k]] if rel_tree is not None else []:
    if NOT_METRO.search(key[1]) or sum(km(c) for c in loose[key]) < 3:
        continue                 # not drawn in any case
    at = defaultdict(list)       # stretch by stretch: what is left under the name can be in several places
    for i, co in enumerate(loose[key]):
        at[co[0]].append(i)
        at[co[-1]].append(i)
    group = list(range(len(loose[key])))

    def root(i):
        while group[i] != i:
            group[i] = group[group[i]]
            i = group[i]
        return i
    for ids in at.values():
        for i in ids[1:]:
            group[root(i)] = root(ids[0])
    stretches = defaultdict(list)
    for i in range(len(group)):
        stretches[root(i)].append(i)
    rest = []
    for ids in stretches.values():
        along, total = Counter(), 0
        for i in ids:
            g = LineString(loose[key][i])
            for k in range(max(2, int(g.length / 0.001) + 1)):
                pt = g.interpolate(k * 0.001)
                total += 1
                for nm in {rel_owner[int(j)] for j in rel_tree.query(pt, predicate="dwithin", distance=0.0006)}:
                    along[nm] += 1
        best = along.most_common(2)
        if best and best[0][1] >= 0.6 * total and (len(best) == 1 or best[1][1] < 0.3 * total):
            raw[best[0][0]]["extra"] += [loose[key][i] for i in ids]
            beside_metro.append((key[1], best[0][0], round(sum(km(loose[key][i]) for i in ids), 1)))
        else:
            rest += [loose[key][i] for i in ids]
    loose[key] = rest
print("named metro track lying along one line, taken as that line's other track:", beside_metro)
print(f"metro track outside relations attached to its line: {adopted_metro} pieces; "
      f"left undrawn: {sum(km(c) for k, v in loose.items() if not k[1] for c in v):.0f} km unnamed")

# Lines by province and final name. Where a province has a single system (贵阳轨道交通, 重庆轨道交通...),
# a bare "2号线" takes that system's name; elsewhere it stays as it is.
systems = defaultdict(Counter)
for nm in raw:
    g = re.match(r"(.+?(?:地铁|轨道交通))[\dA-Za-z]+号线$", nm)
    reg = line_regs[nm].most_common(1)[0][0] if line_regs[nm] else None
    if g and reg:
        systems[reg][g.group(1)] += 1


def final_name(nm, reg):
    return next(iter(systems[reg])) + nm if nm and BARE.fullmatch(nm) and len(systems.get(reg, ())) == 1 else nm


metro_lines = {}     # (province, name) -> {"col", "groups": track of each relation, longest first, "bag": track of no known order}
for nm, d in raw.items():
    regs = Counter({r: n for r, n in line_regs[nm].items() if r})
    if not regs:
        continue
    reg = regs.most_common(1)[0][0]
    line = metro_lines.setdefault((reg, final_name(nm, reg)), {"col": Counter(), "groups": [], "bag": []})
    line["col"].update(d["col"])
    line["groups"] += [[metro_co[w] for w in ws] for ws in d["rels"]]
    line["bag"] += d["extra"]
    for ws in d["rels"]:
        for w in ws:
            line.setdefault("track", Counter())[w in metro_light] += km(metro_co[w])
for (reg, own), cos in loose.items():       # a named line with no relation yet, in the default colour
    if own and not NOT_METRO.search(own) and sum(km(c) for c in cos) >= 3:
        metro_lines.setdefault((reg, final_name(own, reg)), {"col": Counter(), "groups": [], "bag": []})["bag"] += cos

metro_feats, metro_km, metro_geoms = [], Counter(), []
metro_routing = []       # (line name, colour, tracks) for scripts/build_graph.py: every track of the line
paths = {}               # line -> the line as continuous pieces
loop_report = []
metro_anchors = [(x,y) for _,x,y in ex['stations']]
for key, line in metro_lines.items():
    reg, nm = key
    line["colour"] = line["col"].most_common(1)[0][0] if line["col"] else METRO_DEFAULT
    line["light"] = line.get("track", Counter())[True] > line.get("track", Counter())[False]
    every = line["every"] = [co for g in line["groups"] for co in g] + line["bag"]
    runs = runs_of(every)
    metro_geoms += runs
    metro_km[reg] += sum(km(list(g.coords)) for g in runs)
    metro_routing.append((nm, line["colour"], list({tuple(co): co for co in every}.values())))
    groups = sorted(line["groups"], key=lambda g: -sum(km(co) for co in g))
    display_bag = []
    for co in line['bag']:
        kept, record = trim_unowned_loop(co, metro_anchors)
        display_bag.append(kept)
        if record:
            loop_report.append(dict(record, line=nm, kind='unowned_stationless_terminal_loop'))
    if groups:
        pieces = single_path(groups + ([display_bag] if display_bag else []), keep=0.004)      # a metro branch can be half a kilometre long
    else:
        pieces = runs_of(display_bag) if display_bag else runs
    # one_track() takes out what is still there twice (a relation that lists both tracks, a line known
    # only by its track); stitch() joins what belongs together.
    paths[key] = [g.simplify(0.00002, preserve_topology=False) for g in stitch(one_track([g for g in pieces if g.length > 0]), bends=True)]
print(f"metro lines as continuous paths: {len(paths)} lines, {sum(g.length for v in paths.values() for g in v) * 100:.0f} (degrees x 100)", flush=True)

# Lines moved here from the rail classes (run by a metro company) are known by their track only.
moved_tracks, majority = defaultdict(list), defaultdict(Counter)
for nm, col, co in moved:
    moved_tracks[(nm, col)].append(co)
    majority[nm][region_of(*co[0]) or "00"] += len(co)
for (nm, col), cos in moved_tracks.items():
    key = (majority[nm].most_common(1)[0][0], nm)
    runs = runs_of(cos)
    metro_km[key[0]] += sum(km(list(g.coords)) for g in runs)
    metro_geoms += runs
    metro_lines[key] = {"colour": col or METRO_DEFAULT, "kind": "m", "every": cos}
    paths[key] = [g.simplify(0.00002, preserve_topology=False) for g in stitch(one_track(runs), bends=True)]
metro_paths = paths          # each line's own track, as one path: what the drawing is measured against below

# Lines in each other's company. Longest lines first: each line is laid along the lines already
# there wherever it runs with one of them, and is its own reference everywhere else.
by_reg = defaultdict(list)
for key in paths:
    by_reg[key[0]].append(key)
solo = defaultdict(list)         # line -> pieces it has to itself
shared = defaultdict(list)       # (lines) -> pieces they are drawn side by side on
for reg, keys in by_reg.items():
    refs, rides = [], defaultdict(list)          # reference pieces [(geometry, line)], ref -> [(from, to, line)]
    for key in sorted(keys, key=lambda k: (-sum(g.length for g in paths[k]), k[1])):
        tree = STRtree([g for g, _ in refs]) if refs else None
        fresh = []
        light = metro_lines[key].get("light")

        def width(r):                             # how close this line and the owner of a reference have to be
            return TRACK if light or metro_lines[refs[r][1]].get("light") else RIDE
        for piece in paths[key]:
            n = max(2, int(piece.length / RIDE_STEP) + 1)
            at = [piece.length * i / (n - 1) for i in range(n)]
            hit, close, riding = [], [], None     # per sample: (reference, position on it) or None; and whether it is properly close
            for pos in at if tree is not None else []:
                pt, cands = piece.interpolate(pos), {}
                for j in tree.query(pt, predicate="dwithin", distance=RIDE_LOOSE):
                    ref, near = refs[int(j)][0], width(int(j))
                    on, d = ref.project(pt), ref.distance(pt)
                    # not in its company: too far to the side, or past the end of it (the nearest
                    # point of a reference that has ended is its end, however far the line has gone on)
                    if d > (RIDE_LOOSE if near == RIDE else 2 * TRACK) or (d > 0.00003 and not 0 < on < ref.length):
                        continue
                    h, k = heading(piece, pos), heading(ref, on)
                    if abs(h[0] * k[0] + h[1] * k[1]) > 0.85:
                        cands[int(j)] = (d < near, on)
                # The reference being ridden is kept for as long as it is there; otherwise the first one
                # laid here, a properly close one before a loosely close one. So every line in a corridor
                # rides the same reference, and none rides two side by side.
                if riding not in cands:
                    riding = max(cands, key=lambda j: (cands[j][0], -j)) if cands else None
                hit.append((riding, cands[riding][1]) if riding is not None else None)
                close.append(bool(riding is not None and cands[riding][0]))
            taken, i = [], 0                      # stretches of the piece that ride on references: (from, to, reference)
            while i < len(hit):
                if hit[i] is None:
                    i += 1
                    continue
                first, last, k = i, i, i + 1      # a run in company, whichever references it passes along
                # Platform fans can spread for several hundred metres. A brief loss of the
                # reference inside a long corridor does not mean the line leaves that corridor.
                # Light rail has no such corridor: where it is not on another line's track it is alone.
                while k < len(hit) and k - last <= (1 if light else 20):
                    if hit[k] is not None:
                        last = k
                    k += 1
                # in company for long enough, and properly close for a good part of it (loosely close
                # alone is two lines in neighbouring streets)
                if light or (at[last] - at[first] >= RIDE_MIN and sum(close[first:last + 1]) >= 0.5 * (last - first + 1)):
                    passed = []                   # the references passed along, in order: [reference, first sample, last sample]
                    for m in range(first, last + 1):
                        if hit[m] is None:
                            continue
                        if passed and passed[-1][0] == hit[m][0] and (not light or passed[-1][2] == m - 1):
                            passed[-1][2] = m
                        else:
                            passed.append([hit[m][0], m, m])
                    # Where the line comes onto each reference and leaves it is found exactly: a line
                    # that turns off at a junction is drawn on its own curve from the points on, not
                    # carried along the reference to the next sample and cut across from there.
                    for q, (r, m0, m1) in enumerate(passed):
                        ref = refs[r][0]
                        floor = max(taken[-1][1] if taken else 0.0, at[max(m0 - 1, 0)])
                        ceiling = at[passed[q + 1][1]] if q + 1 < len(passed) else at[min(m1 + 1, n - 1)]
                        span = exactly(piece, ref, at[m0], at[m1], width(r), floor, ceiling)
                        if span is not None and width(r) == TRACK:
                            span = settled(piece, ref, *span)
                        if span is None or span[1] - span[0] < (TRACK_MIN if light else 2 * FINE):
                            continue
                        where = ([ref.project(piece.interpolate(span[0]))]
                                 + [hit[m][1] for m in range(m0, m1 + 1) if hit[m] is not None and hit[m][0] == r and span[0] <= at[m] <= span[1]]
                                 + [ref.project(piece.interpolate(span[1]))])
                        # A reference that is a ring (a circle line) begins and ends at one place. A line
                        # passing that place rides the end of the ring and then its beginning: two
                        # stretches, not everything between the lowest position and the highest.
                        legs = [[where[0]]]
                        for v in where[1:]:
                            if abs(v - legs[-1][-1]) > 0.5 * ref.length:
                                onward = legs[-1][-1] > v
                                legs[-1].append(ref.length if onward else 0.0)
                                legs.append([0.0 if onward else ref.length])
                            legs[-1].append(v)
                        for leg in legs:
                            rides[r].append((min(leg), max(leg), key))
                        taken.append((span[0], span[1], r))
                i = last + 1
            # What is left is the line's own track. A short piece between two shared stretches is
            # noise at a junction when it lies off to the side of both (the line's own tunnel for
            # 100 m, 30 m from the path it is drawn along before and after), and the line's way
            # from one to the other when it meets both: the curve at a junction.
            edges = [0.0] + [v for span in taken for v in span[:2]] + [piece.length]
            for q, (a, b) in enumerate(zip(edges[::2], edges[1::2])):
                met = [refs[taken[x][2]][0].distance(piece.interpolate(v)) < TRACK
                       for x, v in ((q - 1, a), (q, b)) if 0 <= x < len(taken)]
                if b - a > RIDE_SLIVER or not taken or (b - a > 2 * FINE and all(met)):
                    own = substring(piece, a, b)
                    if light and own.geom_type == "LineString" and own.length > 0:
                        own = meeting(own, refs[taken[q - 1][2]][0] if q >= 1 else None, refs[taken[q][2]][0] if q < len(taken) else None)
                    fresh.append(own)
        refs += [(g, key) for g in fresh if g.geom_type == "LineString" and g.length > 0]
    # every reference is cut where a line joins or leaves it
    stretches = []                               # (reference, from, to, lines on it)
    for r, (g, owner) in enumerate(refs):
        cuts = [0.0]
        for v in sorted({v for a, b, _ in rides[r] for v in (a, b)}):
            if v - cuts[-1] > 0.00002 and g.length - v > 0.00002:      # no stretch of a metre or two with a set of lines of its own
                cuts.append(v)
        cuts.append(g.length)
        for a, b in zip(cuts, cuts[1:]):
            if b - a > 1e-7:
                on = sorted({owner} | {k for x, y, k in rides[r] if x <= (a + b) / 2 <= y}, key=lambda k: k[1])
                stretches.append((r, a, b, tuple(on)))
    # references that carry more than one line are turned the same way, so the lines keep their sides
    busy = sorted({r for r, _, _, on in stretches if len(on) > 1})
    turned = dict(zip(busy, same_way([refs[r][0] for r in busy]))) if busy else {}
    for r, a, b, on in stretches:
        g = refs[r][0]
        piece = substring(g, a, b)
        if r in turned and turned[r].coords[0] != g.coords[0]:
            piece = LineString(list(piece.coords)[::-1])
        if piece.geom_type == "LineString" and piece.length > 0:
            (solo[on[0]] if len(on) == 1 else shared[on]).append(piece)

def metro_props(key):
    props = {"r": key[0], "col": metro_lines[key]["colour"], "n": key[1]}
    if metro_lines[key].get("kind"):
        props["k"] = metro_lines[key]["kind"]
    return props


display_parts = defaultdict(list, {key: list(pieces) for key, pieces in solo.items()})
direction_guides = defaultdict(list)
# Shared stretches: every line on one is drawn along the same path. side_by_side() gives each its
# slot there at the very end, once the whole line has been joined and smoothed.
shared_km = Counter()
for on, pieces in shared.items():
    lines = [[[round(x, 6), round(y, 6)] for x, y in g.simplify(TOL["metro"], preserve_topology=False).coords] for g in pieces]
    lines = [co for co in lines if len(co) > 1]
    if not lines:
        continue
    slots = []
    for key in on:
        if not any(same_colour(metro_lines[key]["colour"], other) for other in slots):
            slots.append(metro_lines[key]["colour"])
    if len(slots) > 1:
        shared_km[" + ".join(key[1] for key in on)] += sum(km(co) for co in lines)
    for i, key in enumerate(on):
        display_parts[key].extend(pieces)
        direction_guides[key].extend(pieces)

# Join the entire line first: it is cut again only where its slot changes, in the middle of a
# straight stretch, where the two offset ends meet on screen.
for key, pieces in display_parts.items():
    # The corridor sampler drops short solo slivers (< RIDE_SLIVER). Their two neighbouring
    # reference ends can be up to twice that distance apart; carry the same line across them.
    light = metro_lines[key].get("light")
    runs = stitch(runs_of(pieces), reach=4 * TRACK if light else 3 * RIDE_SLIVER, ease=0.00002 if light else 0.00006, bends=True)
    guides = direction_guides[key]
    oriented = []
    for g in runs:
        if guides:
            guide = max(guides, key=lambda h: h.length)
            middle = guide.interpolate(guide.length / 2)
            a, b = heading(g, g.project(middle)), heading(guide, guide.length / 2)
            if a[0] * b[0] + a[1] * b[1] < 0:
                g = LineString(list(g.coords)[::-1])
        oriented.append(g)
    simp = rounded(oriented, TOL["light" if light else "metro"], join=False)      # curved last of all, in finish_metro()
    if simp:
        metro_feats.append({"type": "Feature", "properties": metro_props(key), "geometry": geometry(simp)})
print("metro lines drawn side by side (km):", {k: round(v, 1) for k, v in shared_km.most_common(16)},
      f"... {len(shared_km)} combinations, {sum(shared_km.values()):.0f} km")

# Bureau-run suburban services: one path each. A double line has a track per direction and a route
# relation per direction, so the longest relation gives the path; other relations only add what
# lies away from it (branches, short workings). Every piece is turned to run the same way.
suburb_co = dict(suburb_ways)
suburb_names = []
for name, rels in suburb_rels.items():
    paths = []
    for col, wids in rels:
        lines = [suburb_co[w] for w in dict.fromkeys(wids) if w in suburb_co]
        if lines:
            paths.append((sum(km(l) for l in lines), col, lines))
    if not paths:
        continue
    paths.sort(key=lambda t: -t[0])
    col = next((c for _, c, _ in paths if c and c != "#000000"), None)
    out = rounded(stitch(single_path([lines for _, _, lines in paths])), TOL["metro"], join=False)
    if not out:
        continue
    reg = Counter(filter(None, (region_of(*line[0]) for line in out))).most_common(1)
    if not reg:
        continue
    suburb_names.append(name)
    metro_feats.append({"type": "Feature", "properties": {"r": reg[0][0], "col": readable_on_dark(col) or METRO_DEFAULT, "n": name, "k": "s"},
                        "geometry": geometry(out)})
# ---------------------------------------------------------------- one metro line, one continuous line
# A line is written as several features: its own track, and one for every stretch it shares with a
# different set of lines. Where one stops just short of the next, it is carried on to it, so the
# line is continuous on the ground; what remains on screen is only the sideways shift of the slot.
def reach_out(feats, reach=0.0012):
    lists = []                      # (feature, index of the line in its geometry, geometry)
    for f in feats:
        g = f["geometry"]
        f["geometry"] = g = {"type": "MultiLineString", "coordinates": [list(map(list, line)) for line in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]])]}
        lists += [(f, i, LineString(line)) for i, line in enumerate(g["coordinates"])]
    for n, (f, i, g) in enumerate(lists):
        line = f["geometry"]["coordinates"][i]
        for at_start in (True, False):
            end = Point(line[0] if at_start else line[-1])
            d, k = min(((o.distance(end), k) for k, (_, _, o) in enumerate(lists) if k != n), default=(None, None))
            if d is None or not 1e-7 < d < reach:
                continue
            other = lists[k][2]
            at = other.project(end)
            seam = min(at, other.length - at) < 2 * d + 0.0001       # the other piece ends here too
            if seam and k < n:
                continue                                              # it has reached out to this one already
            mine = LineString(line)
            back = min(3 * d, mine.length / 3) if seam else 0.0        # give way a little, so the join is a slant
            if back:
                kept = substring(mine, back, mine.length) if at_start else substring(mine, 0, mine.length - back)
                if kept.geom_type == "LineString" and len(kept.coords) > 1:
                    line[:] = [[round(x, 5), round(y, 5)] for x, y in kept.coords]
            if seam:
                q = Point(other.coords[0] if at < other.length / 2 else other.coords[-1])
            else:                   # onto the side of the other piece: further along it, the way this one is heading
                inner = Point(line[1] if at_start else line[-2])
                q = max((other.interpolate(min(max(at + way * 3 * d, 0), other.length)) for way in (1, -1)), key=lambda c: c.distance(inner))
            pt = [round(q.x, 5), round(q.y, 5)]
            line.insert(0, pt) if at_start else line.append(pt)
    for f in feats:
        co = f["geometry"]["coordinates"]
        f["geometry"] = geometry(co)


same_line = defaultdict(list)
for f in metro_feats:
    if f["properties"].get("k") != "s" and f["properties"].get("n"):
        same_line[(f["properties"]["r"], f["properties"]["n"])].append(f)
# Whole-line geometry above already has shared and solo pieces joined. Reaching individual
# features out to their neighbours here used to add duplicate crossbars and station loops.
# and no sudden changes of direction: spikes and sharp corners left by the joins are taken out
for f in metro_feats:
    g = f["geometry"]
    lines = [[[round(x, 6), round(y, 6)] for x, y in smooth(line, reverse=181)] for line in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]])]
    lines = [line for line in lines if len(line) > 1]
    if lines:
        f["geometry"] = geometry(lines)

bend_report = finish_metro(metro_feats, metro_routing + [(nm, col, cos) for (nm, col), cos in moved_tracks.items()], curve=CURVE["metro"], within=TOL["metro"],
             light={key for key, line in metro_lines.items() if line.get("light")}, light_curve=CURVE["light"], light_within=TOL["light"],
             anchors=metro_anchors)
bend_report += loop_report
bend_file = ROOT / 'output' / 'geometry' / 'metro-bend-repairs.json'
bend_file.parent.mkdir(parents=True, exist_ok=True)
bend_file.write_text(json.dumps(bend_report, ensure_ascii=False, indent=1))
print(f'final metro bends: {len(bend_report)} source restorations/refits/terminal-loop reductions; report {bend_file}', flush=True)
# How well the drawing lies on the track: lines carried across a junction, track left undrawn.
fit_report = metro_fit(metro_feats, {key: line.get("every", ()) for key, line in metro_lines.items()}, metro_paths,
                       {key for key, line in metro_lines.items() if line.get("light")})
print(metro_fit_summary(fit_report), flush=True)
fit_file = ROOT / "output" / "metro_fit.json"
fit_file.parent.mkdir(exist_ok=True)
fit_file.write_text(json.dumps(fit_report, ensure_ascii=False, indent=1))

# ---------------------------------------------------------------- metro lines by city
def spread(f):
    g = f["geometry"]
    lines = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
    xs, ys = [p[0] for line in lines for p in line], [p[1] for line in lines for p in line]
    return sum(km(line) for line in lines), [min(xs), min(ys), max(xs), max(ys)]


for f in metro_feats:
    nm, pr = f["properties"].get("n", ""), f["properties"]
    hit = METRO_CITY.match(nm)
    pr["ct"] = next((c for k, c in CITY_OF.items() if nm.startswith(k)), None) or (hit.group(1).translate(SIMPLIFIED) if hit else None)
    if not pr["ct"] and pr.get("k") == "m":
        pr["ct"] = INTERCITY_GROUP.get(pr["r"])
    f["km"], f["box"] = spread(f)
    f["at"] = ((f["box"][0] + f["box"][2]) / 2, (f["box"][1] + f["box"][3]) / 2)


def city_table():
    table = defaultdict(lambda: {"km": 0.0, "lines": set(), "x": 0.0, "y": 0.0})
    for f in metro_feats:
        if f["properties"]["ct"]:
            c = table[f["properties"]["ct"]]
            c["km"] += f["km"]
            c["lines"].add(f["properties"].get("n"))       # a line can have several pieces
            c["x"] += f["at"][0] * f["km"]
            c["y"] += f["at"][1] * f["km"]
    return {k: (c["x"] / c["km"], c["y"] / c["km"], c["km"], len(c["lines"])) for k, c in table.items() if c["km"]}


def nearest_city(at, cities, skip=None, limit=None):
    best = min(((math.hypot(at[0] - x, at[1] - y), k) for k, (x, y, _, _) in cities.items() if k != skip), default=None)
    return best[1] if best and (limit is None or best[0] < limit) else None


# A name that is not a city (高雄環狀, 大王山, 坪山: one line each) joins the city it lies in; a line
# with no city in its name goes to the nearest one.
cities = city_table()
for f in metro_feats:
    ct = f["properties"]["ct"]
    if ct and ct not in INTERCITY_GROUP.values() and cities[ct][3] == 1:
        bigger = {k: v for k, v in cities.items() if v[3] > 1 and k not in INTERCITY_GROUP.values()}
        f["properties"]["ct"] = nearest_city(f["at"], bigger, limit=CITY_MERGE_DEG) or ct
cities = {k: v for k, v in city_table().items() if k not in INTERCITY_GROUP.values()}
for f in metro_feats:
    if not f["properties"]["ct"]:
        f["properties"]["ct"] = nearest_city(f["at"], cities, limit=1.2) or f["properties"].get("n", "")[:2] or "其他"
city_list = defaultdict(lambda: {"km": 0.0, "bbox": [180, 90, -180, -90], "lines": {}})
grow = lambda box, other: [min(box[0], other[0]), min(box[1], other[1]), max(box[2], other[2]), max(box[3], other[3])]
for f in metro_feats:
    pr, c = f["properties"], city_list[f["properties"]["ct"]]
    if not f.pop("also", False):        # shared track counts once towards the city's total
        c["km"] += f["km"]
    c["bbox"] = grow(c["bbox"], f["box"])
    line = c["lines"].setdefault(pr.get("n", ""), {"n": pr.get("n", ""), "col": pr["col"], "km": 0.0, "bbox": f["box"], **({"k": pr["k"]} if pr.get("k") else {})})
    line["km"] += f["km"]               # a line has one piece per stretch it shares, plus its own track
    line["bbox"] = grow(line["bbox"], f["box"])
    for extra in ("km", "box", "at"):
        del f[extra]
for c in city_list.values():
    c["lines"] = [{**line, "km": round(line["km"]), "bbox": [round(v, 3) for v in line["bbox"]]} for line in c["lines"].values()]


def line_order(d):
    num = re.search(r"(\d+)号线", d["n"])
    return (bool(d.get("k")), 0 if num else 1, int(num.group(1)) if num else 0, d["n"])


(OUT / "metro_cities.json").write_text(json.dumps(
    [{"n": k, "km": round(c["km"]), "bbox": [round(v, 3) for v in c["bbox"]], "lines": sorted(c["lines"], key=line_order)}
     for k, c in sorted(city_list.items(), key=lambda kv: -kv[1]["km"])], ensure_ascii=False, separators=(",", ":")))
print("metro cities:", {k: f"{len(c['lines'])} lines {c['km']:.0f} km" for k, c in sorted(city_list.items(), key=lambda kv: -kv[1]["km"])})
# Lines drawn along one path are moved apart there, and only there: a line that runs alone stays
# on its track. A line becomes a few features, one per slot (see scripts/side_by_side.py).
metro_lines_drawn = len(metro_feats)
metro_feats = side_by_side(metro_feats)
print(f"metro lines side by side: {metro_lines_drawn} lines written as {len(metro_feats)} features, "
      f"{sum(1 for f in metro_feats if f['properties'].get('off'))} of them moved to a side")
write("metro.geojson", metro_feats)
with open(RAW / "routing_metro.pkl", "wb") as f:
    pickle.dump(metro_routing, f, protocol=pickle.HIGHEST_PROTOCOL)
print("bureau-operated suburban services:", sorted(suburb_names))
print("metro lines per region:", dict(Counter(r for r, _ in {(f["properties"]["r"], f["properties"].get("n")) for f in metro_feats})),
      "| track km:", {k: round(v) for k, v in metro_km.items()},
      "| without official colour:", sorted({f["properties"].get("n", "?") for f in metro_feats if f["properties"]["col"] == METRO_DEFAULT}))

# ---------------------------------------------------------------- yards and depots
yard_simp, yard_parts = merge_simplify(yard_tracks, 0.00004, single=False)
CHUNK = 400      # a few large MultiLineStrings tile and render faster than one huge feature
write("yards.geojson", [{"type": "Feature", "properties": {}, "geometry": geometry(yard_simp[i:i + CHUNK])}
                        for i in range(0, len(yard_simp), CHUNK)])
print(f"yard and siding track: {sum(km(list(g.coords)) for g in yard_parts):.0f} km")
yard_tree = STRtree(yard_parts)
depots, seen_depot = [], set()
for kind, t, lon, lat, country in places_raw:
    nm = name_of(t, country)
    if not nm or (kind == "land" and not DEPOT_NAME.search(nm)):
        continue
    k = (nm, round(lon, 2), round(lat, 2))
    if k in seen_depot or not len(yard_tree.query(Point(lon, lat), predicate="dwithin", distance=0.01)):
        continue
    seen_depot.add(k)
    depots.append({"type": "Feature", "properties": {"n": nm}, "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}})
write("depots.geojson", depots)

# ---------------------------------------------------------------- stations
rail_tree, fast_tree, metro_tree = STRtree(all_geoms), STRtree(fast_geoms), STRtree(metro_geoms)
st_feats, metro_st, seen, seen_metro = [], [], set(), set()
dropped = 0
for t, lon, lat, country in stations_raw:
    nm = name_of(t, country)
    if not nm:
        continue
    pt = Point(lon, lat)
    is_metro = t.get("station") in METRO_RAIL | {"funicular", "tram"} or t.get("subway") == "yes" or t.get("light_rail") == "yes"
    on_metro = country == "cn" and len(metro_tree.query(pt, predicate="dwithin", distance=0.0025))
    if is_metro or (on_metro and not len(rail_tree.query(pt, predicate="dwithin", distance=0.002))):
        if on_metro:
            k = (nm, round(lon / 0.006), round(lat / 0.006))   # one dot per interchange
            if k not in seen_metro:
                seen_metro.add(k)
                metro_st.append({"type": "Feature", "properties": {"n": nm}, "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}})
        continue
    k = (nm, round(lon, 2), round(lat, 2))
    if k in seen:
        continue
    seen.add(k)
    if not len(rail_tree.query(pt, predicate="dwithin", distance=0.006)):
        dropped += 1          # heritage, industrial or closed lines that are not drawn
        continue
    props = {"n": nm}
    if len(fast_tree.query(pt, predicate="dwithin", distance=0.004)):
        props["h"] = 1
    st_feats.append({"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}})
write("stations.geojson", st_feats)
write("metro_stations.geojson", metro_st)
print(f"stations on fast lines: {sum(1 for f in st_feats if f['properties'].get('h'))}; dropped (no drawn line nearby): {dropped}")

lines = []
for d in line_info.values():
    cls, (length, sp) = max(d.pop("by").items(), key=lambda kv: kv[1][0])
    lines.append({**d, "c": cls, "s": sp, "bbox": [round(v, 3) for v in d["bbox"]], "tk": round(d["tk"])})
lines.sort(key=lambda d: -d["tk"])
(OUT / "lines.json").write_text(json.dumps(lines, ensure_ascii=False, separators=(",", ":")))
print("listed lines:", len(lines), dict(Counter((d["g"], d["c"]) for d in lines)))
print("track km (double track counted twice):", {f"{k[0]}:{k[1]}": round(v) for k, v in sorted(track_km.items())})

# Keep routing_input.pkl nominal classes separate from section design speeds.
from design_speeds import apply as apply_design_speeds, keep_base
keep_base(ROOT)          # so that scripts/design_speeds.py can be run again on its own
apply_design_speeds(ROOT)
