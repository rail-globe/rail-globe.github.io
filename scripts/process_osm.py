"""Stage 2: classify the extracted OSM objects and write the map layers.

Inputs : data/raw/extract.pkl     (scripts/extract_osm.py: China, Hong Kong, Macao, Taiwan)
         data/raw/extract_uk.pkl  (scripts/extract_osm.py uk: United Kingdom)
Outputs: data/rail_hsr.geojson, rail_conv.geojson, rail_build.geojson, stations.geojson,
         metro.geojson, metro_stations.geojson, yards.geojson, depots.geojson,
         uk_operators.json, lines.json
Line classes (property c):
  hsr350  high-speed, maxspeed >= 300 km/h
  hsr250  high-speed, 250-299 (or unknown speed on a high-speed line)
  hsr200  intercity and fast lines below 250; Greater Bay Area intercity lines belong here
          whatever their speed tags say
  main    conventional, usage=main
  branch  conventional, other usages / untagged
  build   under construction (property h marks high-speed)

Every line has exactly one class along its whole length, so its colour never changes partway.
Tracks are grouped into lines by name (spelling variants such as 京沪高铁 / 京沪高速线 or
广深Ⅰ线 / 广深Ⅱ线 are one line); the line takes the class that most of its track has, and
unnamed connecting stretches follow the line they join.

Metro lines keep their official colour (property col) from the OSM route relations.
UK lines carry their main passenger operator (property o).
"""
import json
import math
import pickle
import re
from collections import Counter, defaultdict
from pathlib import Path

from shapely.geometry import MultiLineString, Point
from shapely.ops import linemerge
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"
TOL = {"hsr350": 0.00012, "hsr250": 0.00012, "hsr200": 0.0001,
       "main": 0.0002, "branch": 0.0003, "build": 0.0002, "metro": 0.00006}
SKIP_USAGE = {"industrial", "military", "tourism", "test", "freight;industrial"}
METRO_RAIL = {"subway", "light_rail", "monorail"}
METRO_DEFAULT = "#5cc8ff"
# Not metro: trams, airport people movers, theme-park and company-campus lines.
NOT_METRO = re.compile(r"有轨|华为|比亚迪|世界之窗|旅客捷运|旅客捷運|旅客自动|APM T\d|People Mover|旅游专线|云轨|车辆段|联络线|付线")
# Greater Bay Area intercity network: lines named 城际 plus branches that carry another name,
# and lines mostly used by the intercity train services (route relations of the 城际 operators).
IC_NAME = re.compile(r"城际|琶洲支线|^江门线$|^广深[ⅠⅡⅢⅣ]?线$")
IC_NETWORK = re.compile(r"城际")
IC_SHARE = 0.4      # share of a line's Bay Area track used by intercity services
MINOR_LINE_KM = 10  # track km below which a named "line" is treated as a fragment of its neighbour
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


def line_key(name, country, lon, lat):
    """Identity of the line a named track belongs to, tolerant of spelling variants."""
    if (country, name) in KNOWN_LINES:
        return (country, KNOWN_LINES[(country, name)][0])
    if country == "uk":
        return (country, name)
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


def merge_simplify(lines, tol):
    """Join touching segments, simplify, and return (rounded coordinate lists, original parts)."""
    merged = linemerge(MultiLineString(lines))
    parts = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
    out = []
    for g in parts:
        s = g.simplify(tol, preserve_topology=False)
        if s.length > 0:
            out.append([[round(x, 5), round(y, 5)] for x, y in s.coords])
    return out, parts


def geometry(lines):
    return {"type": "MultiLineString", "coordinates": lines} if len(lines) > 1 else {"type": "LineString", "coordinates": lines[0]}


def write(name, feats):
    p = OUT / name
    p.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":")))
    print(f"{name}: {len(feats)} features, {p.stat().st_size / 1e6:.2f} MB")


# ---------------------------------------------------------------- load
# The pickles are written locally by scripts/extract_osm.py, so loading them is safe here.
ex = pickle.load(open(RAW / "extract.pkl", "rb"))
REGIONS = ex["regions"]
ways = [(wid, t, co, "cn") for wid, t, co in ex["ways"]]
stations_raw = [(t, lon, lat, "cn") for t, lon, lat in ex["stations"]]
places_raw = [(kind, t, lon, lat, "cn") for kind, t, lon, lat in ex.get("places", [])]
uk_file = RAW / "extract_uk.pkl"
uk = pickle.load(open(uk_file, "rb")) if uk_file.exists() else {"ways": [], "stations": [], "relations": [], "places": []}
if not uk["ways"]:
    print("no UK data yet (run scripts/extract_osm.py uk)")
ways += [(wid, t, co, "uk") for wid, t, co in uk["ways"]]
stations_raw += [(t, lon, lat, "uk") for t, lon, lat in uk["stations"]]
places_raw += [(kind, t, lon, lat, "uk") for kind, t, lon, lat in uk.get("places", [])]


def region_of(lon, lat):
    for k, (w, s, e, n) in REGIONS.items():
        if w <= lon <= e and s <= lat <= n:
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
    s = re.split(r"[:：(（]|→|=>|-->|⇒", s or "")[0].strip()
    if re.search(r"[一-鿿]", s):
        s = re.sub(r"\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'\-]*$", "", s)
        s = re.sub(r"\s+", "", s)
    return s


def colour_of(*tags):
    for t in tags:
        c = (t or {}).get("colour", "").strip()
        if re.fullmatch(r"#[0-9a-fA-F]{6}", c):
            return c.lower()
        if re.fullmatch(r"#[0-9a-fA-F]{3}", c):
            return "#" + "".join(ch * 2 for ch in c[1:]).lower()
    return None


def metro_line_name(m, t):
    """'广州地铁3号线' from master/route tags; the network disambiguates 'Line 3' of different cities."""
    cands = [m.get("name:zh"), m.get("name"), t.get("name:zh"), t.get("name")]
    raw = next((c for c in cands if c and re.search(r"[一-鿿]", c)), None) or next((c for c in cands if c), "")
    line = re.sub(r"^(地铁|轻轨|磁悬浮)(?=.)", "", zh(raw))
    net = zh(m.get("network") or t.get("network") or "")
    if not line:
        return ""
    return line if (not net or net in line or line.startswith(net[:2])) else net + line


way_metro = {}       # way id -> (line name, colour)
ic_rel_ways = set()  # ways used by Greater Bay Area intercity train services
for rid, t, members in ex["relations"]:
    if t.get("type") != "route":
        continue
    m = masters.get(rid, {})
    if t.get("route") in METRO_RAIL:
        info = (metro_line_name(m, t), colour_of(m, t))
        for mtype, ref in members:
            if mtype == "w":
                way_metro.setdefault(ref, info)
    elif t.get("route") == "train":
        net = " ".join(filter(None, (m.get("network"), t.get("network"), t.get("operator"), m.get("name"), t.get("name"))))
        if IC_NETWORK.search(net):
            ic_rel_ways.update(ref for mtype, ref in members if mtype == "w")

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
rail, build, metro_ways, yard_tracks = [], [], [], []
for wid, t, co, country in ways:
    r = t.get("railway")
    if (r == "rail" or r in METRO_RAIL) and t.get("service"):
        if t["service"] in YARD_SERVICE:
            yard_tracks.append(co)
    elif r in METRO_RAIL or (r == "rail" and wid in way_metro and country == "cn"):
        metro_ways.append((wid, t, co))       # includes heavy-rail metro such as MTR East Rail, Guangzhou 18/22
    elif r == "rail":
        if t.get("usage") in SKIP_USAGE:
            continue
        sp = speed_of(t)
        rail.append({"id": wid, "n": name_of(t, country), "sp": sp, "g": country, "co": co, "km": km(co),
                     "ops": uk_way_ops.get(wid) if country == "uk" else None,
                     "fast": sp >= 200 if sp else t.get("highspeed") == "yes",
                     "conv": "main" if t.get("usage") == "main" else "branch",
                     "gba": country == "cn" and region_of(*co[0]) == "gba"})
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
    if w["key"] and key_km[w["key"]] < MINOR_LINE_KM and (w["g"], w["n"]) not in KNOWN_LINES:
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
                             "gba": 0.0, "gba_rel": 0.0})
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
    if w["gba"]:
        st["gba"] += w["km"]
        if w["id"] in ic_rel_ways:
            st["gba_rel"] += w["km"]

# ---------------------------------------------------------------- one class per line
line_cls, line_name, ic_keys = {}, {}, set()
for key, st in stats.items():
    line_name[key] = st["names"].most_common(1)[0][0]
    in_gba = st["gba"] >= 0.5 * st["total"]
    known = KNOWN_LINES.get((key[0], line_name[key]))
    if known:
        line_name[key], line_cls[key] = known[0], known[1]
    elif in_gba and (any(IC_NAME.search(n) for n in st["names"]) or st["gba_rel"] >= IC_SHARE * st["gba"]):
        line_cls[key] = "hsr200"
        ic_keys.add(key)
    elif st["fast"] >= 0.5 * st["total"]:
        line_cls[key] = st["cls"].most_common(1)[0][0] if st["cls"] else "hsr250"
    else:
        line_cls[key] = st["conv"].most_common(1)[0][0]
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

# Classified tracks for scripts/build_graph.py, which builds the routing network.
with open(RAW / "routing_input.pkl", "wb") as f:
    pickle.dump([(w["c"], w["n"], w["g"], w["co"]) for w in rail] + [("svc", "", "", co) for co in yard_tracks],
                f, protocol=pickle.HIGHEST_PROTOCOL)

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
op_colour = {brand: colour for _, brand, colour, _ in UK_OPERATORS}
(OUT / "uk_operators.json").write_text(json.dumps(
    [{"n": b, "col": op_colour[b], "km": round(k)} for b, k in op_km.most_common()], ensure_ascii=False))
print("UK operators (track km):", {b: round(k) for b, k in op_km.most_common()},
      "| no passenger operator:", round(sum(w["km"] for w in rail if w["g"] == "uk" and not w["o"])))

# ---------------------------------------------------------------- rail layers
groups = defaultdict(list)
for w in rail:
    groups[(w["c"], w["n"], w["g"], w["o"])].append(w)
feats = defaultdict(list)
track_km = Counter()
line_info = {}
fast_geoms, all_geoms = [], []
for (cls, nm, country, op), ws in groups.items():
    simp, parts = merge_simplify([w["co"] for w in ws], TOL[cls])
    length = sum(w["km"] for w in ws)
    track_km[(country, cls)] += length
    listed = cls.startswith("hsr")
    all_geoms += parts
    if listed:
        fast_geoms += parts
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
    if listed and nm:
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
for (nm, hs), lines in build_groups.items():
    simp, _ = merge_simplify(lines, TOL["build"])
    if simp:
        props = {"c": "build"}
        if nm:
            props["n"] = nm
        if hs:
            props["h"] = 1
        feats["build"].append({"type": "Feature", "properties": props, "geometry": geometry(simp)})
for bucket, fs in feats.items():
    write(f"rail_{bucket}.geojson", fs)

# ---------------------------------------------------------------- metro lines
known_lines = {}
for nm, col in way_metro.values():
    if nm:
        known_lines.setdefault(re.sub(r"\s+", "", nm), (nm, col))
metro_groups = defaultdict(list)
loose = defaultdict(list)       # tracks that belong to no route relation
for wid, t, co in metro_ways:
    reg = region_of(*co[0])
    if not reg:
        continue
    if wid in way_metro:
        nm, col = way_metro[wid]
    else:
        own = zh(t.get("name:zh") or t.get("name") or "")
        nm, col = known_lines.get(own, (None, None))
        if nm is None:
            loose[(reg, own)].append(co)
            continue
    if NOT_METRO.search(nm or ""):
        continue
    metro_groups[(reg, nm or "")].append((co, col or colour_of(t)))
for (reg, own), lines in loose.items():      # keep longer unmatched tracks, in the default colour
    if not NOT_METRO.search(own) and sum(km(c) for c in lines) >= 3:
        metro_groups[(reg, own)] += [(co, None) for co in lines]
metro_feats, metro_km, metro_geoms = [], Counter(), []
for (reg, nm), items in metro_groups.items():
    cols = Counter()
    for co, col in items:
        if col:
            cols[col] += len(co)
    col = cols.most_common(1)[0][0] if cols else METRO_DEFAULT
    simp, parts = merge_simplify([co for co, _ in items], TOL["metro"])
    metro_km[reg] += sum(km(list(g.coords)) for g in parts)
    metro_geoms += parts
    if simp:
        props = {"r": reg, "col": col}
        if nm:
            props["n"] = nm
        metro_feats.append({"type": "Feature", "properties": props, "geometry": geometry(simp)})
write("metro.geojson", metro_feats)
print("metro lines per region:", dict(Counter(f["properties"]["r"] for f in metro_feats)),
      "| track km:", {k: round(v) for k, v in metro_km.items()},
      "| without official colour:", sorted(f["properties"].get("n", "?") for f in metro_feats if f["properties"]["col"] == METRO_DEFAULT))

# ---------------------------------------------------------------- yards and depots
yard_simp, yard_parts = merge_simplify(yard_tracks, 0.00004)
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
    on_metro = country == "cn" and region_of(lon, lat) and len(metro_tree.query(pt, predicate="dwithin", distance=0.0025))
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
print("named fast lines:", len(lines), dict(Counter((d["g"], d["c"]) for d in lines)))
print("track km (double track counted twice):", {f"{k[0]}:{k[1]}": round(v) for k, v in sorted(track_km.items())})
