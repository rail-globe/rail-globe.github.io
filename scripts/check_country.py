"""Checks on the layers of a country abroad, one for every kind of fault met so far.
Run after the country's script; a line marked !! needs a look.

    python3 scripts/check_country.py jp|uk|kr [...]

Writes output/check_<code>.json with what it found.
"""
import json
import math
import pickle
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from shapely import STRtree
from shapely.geometry import LineString, Point
from shapely.ops import linemerge, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from process_jp import MINI, with_a_line
from depots import check as depot_check
from names import check as names_check

ROOT = Path(__file__).resolve().parents[1]
DATA, RAW, OUT = ROOT / "data", ROOT / "data" / "raw", ROOT / "output"
FAST = ("hsr400", "hsr350", "hsr300", "hsr250", "hsr200", "hsr160", "hsrslow")
MINI_LINES = {"jp": 2}       # Japan's mini-Shinkansen, 山形 and 秋田: in the Shinkansen class, outside its speed band
FILES = ("rail.geojson", "metro.geojson", "stations.geojson", "lines.json", "metro_cities.json", "facts.json", "yards.geojson", "depots.geojson")
NEAR, FAR = 0.0003, 0.02          # ends closer than about 30 m are joined; a break is a gap of up to about 2 km
# names that say which track, not which line
TRACK_NAME = re.compile(r"^(Up|Down)\b|\b(Up|Down) (&|and) (Up|Down)\b|\b(Up|Down) (Goods )?Loop$|\bGoods( Loop)?$|\b(Fast|Slow|Relief|Sidings?|Reception|Headshunt)$|^\d+번선|^[上下]り|番線$")


def km(co):
    return sum(math.hypot((x2 - x1) * math.cos(math.radians((y1 + y2) / 2)), y2 - y1) * 111.32 for (x1, y1), (x2, y2) in zip(co, co[1:]))


def parts_of(f):
    g = f["geometry"]
    return [co for co in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]) if len(co) > 1]


def breaks(by_line, track):
    """Two loose ends of one line that face each other across a gap where there is track but
    nothing is drawn: the line is cut. (Ends with no track between them are just two branches.)"""
    drawn = STRtree([LineString(co) for parts in by_line.values() for co in parts])
    found = []
    for name, parts in by_line.items():
        geoms = [LineString(co) for co in parts]
        tree = STRtree(geoms)
        ends = [(i, Point(co[k])) for i, co in enumerate(parts) for k in (0, -1)]
        loose = [(i, p) for i, p in ends if not [j for j in tree.query(p, predicate="dwithin", distance=NEAR) if j != i]]
        used = set()
        for a, (i, p) in enumerate(loose):
            if a in used:
                continue
            near = sorted((p.distance(q), b, q) for b, (j, q) in enumerate(loose) if b > a and j != i and b not in used and NEAR < p.distance(q) < FAR)
            if not near:
                continue
            d, b, q = near[0]
            mids = [Point(p.x + (q.x - p.x) * k, p.y + (q.y - p.y) * k) for k in (0.25, 0.5, 0.75)]
            bare = sum(not len(drawn.query(m, predicate="dwithin", distance=0.0012)) for m in mids)
            on_track = sum(bool(len(track.query(m, predicate="dwithin", distance=0.0008))) for m in mids)
            if bare >= 2 and on_track >= 2:
                used.update((a, b))
                found.append({"line": name, "km": round(d * 111, 2), "from": [round(p.x, 4), round(p.y, 4)], "to": [round(q.x, 4), round(q.y, 4)]})
    return found


def twice(by_line, step=0.002, near=0.00035):
    """Stretches where two pieces of one line run side by side: the line is drawn twice there."""
    found = []
    for name, parts in by_line.items():
        if len(parts) < 2:
            continue
        geoms = [LineString(co) for co in parts]
        tree = STRtree(geoms)
        beside = 0.0
        for i, g in enumerate(geoms):
            n = int(g.length / step)
            for k in range(2, n - 1):                # away from the ends, where pieces meet anyway
                p = g.interpolate(k * step)
                if any(j != i and geoms[j].distance(p) < near and min(geoms[j].project(p), geoms[j].length - geoms[j].project(p)) > 2 * step
                       for j in tree.query(p, predicate="dwithin", distance=near)):
                    beside += step
        if beside * 111 / 2 >= 1:
            found.append({"line": name, "km": round(beside * 111 / 2, 1)})
    return sorted(found, key=lambda r: -r["km"])


def check(code):
    report, flags = {"country": code}, []
    say = lambda bad, text: (flags.append(text) if bad else None, print(("!! " if bad else "   ") + text, flush=True))
    print(f"==== {code}", flush=True)

    # ---- every layer is there (a country was once added without its trams, and two without their yards)
    missing = [f for f in FILES if not (DATA / f"{code}_{f}").exists() or (DATA / f"{code}_{f}").stat().st_size < 3]
    say(missing, f"layers written: {len(FILES) - len(missing)} of {len(FILES)}" + (f"; missing {missing}" if missing else ""))
    if "rail.geojson" in missing:
        return report
    load = lambda f: json.loads((DATA / f"{code}_{f}").read_text())
    rail, metro, stations = load("rail.geojson")["features"], load("metro.geojson")["features"], load("stations.geojson")["features"]
    lines, cities, facts = load("lines.json"), load("metro_cities.json"), load("facts.json")
    build = load("build.geojson")["features"] if (DATA / f"{code}_build.geojson").exists() else []
    yards, depots = (load(f)["features"] if f not in missing else [] for f in ("yards.geojson", "depots.geojson"))
    say(not build, f"lines being built: {len(build)}" + ("" if build else " (none drawn: say so if the country has some)"))
    say(not yards or not depots, f"yards: {len(yards)} features, named yards and depots: {len(depots)}")

    # ---- every feature says which country and which class it is (one left out is not drawn at all, or drawn in another country)
    stray = [f["properties"].get("n") for fs in (rail, metro, stations, build, yards, depots) for f in fs if f["properties"].get("g") != code]
    say(stray, f"features not marked g = {code}: {len(stray)}")
    kinds = Counter(f["properties"].get("jk") for f in rail)
    say(None in kinds, f"railway classes: {dict(kinds.most_common())}")
    mk = Counter(f["properties"].get("jk") for f in metro)
    say(set(mk) - {"subway", "urban"}, f"metro classes: {dict(mk.most_common())}")
    split = defaultdict(set)
    for f in rail:
        split[f["properties"]["n"]].add(f["properties"]["jk"])
    both = sorted(n for n, ks in split.items() if len(ks) > 1)
    say(both, f"lines in two classes at once: {len(both)} {both[:6]}")

    # ---- the lines themselves
    by_line = defaultdict(list)
    for f in rail:
        by_line[f["properties"]["n"]].extend(parts_of(f))
    drawn_km = sum(km(co) for parts in by_line.values() for co in parts)
    say(abs(drawn_km - facts["km"]) > 0.01 * facts["km"], f"railway drawn: {drawn_km:.0f} km in {len(by_line)} lines (the card says {facts['km']})")
    # written locally by scripts/extract_osm.py, so loading it is safe here
    ex = pickle.load(open(RAW / f"extract_{code}.pkl", "rb"))
    running = [(t, co) for _, t, co in ex["ways"] if t.get("railway") in ("rail", "narrow_gauge") and not t.get("service") and len(co) > 1]
    track = STRtree([LineString(co) for _, co in running])
    cut = breaks(by_line, track)
    say(len(cut) > 5, f"breaks (track in the gap, nothing drawn): {len(cut)}, {sum(c['km'] for c in cut):.1f} km " + str([(c["line"], c["km"], c["from"]) for c in sorted(cut, key=lambda c: -c["km"])[:5]]))
    double = twice(by_line)
    say(sum(d["km"] for d in double) > 0.01 * drawn_km, f"drawn twice (two pieces of a line side by side): {len(double)} lines, {sum(d['km'] for d in double):.0f} km " + str([(d["line"], d["km"]) for d in double[:5]]))
    tiny = [l["n"] for l in lines if l["tk"] < 2]
    say(False, f"lines with under 2 km of track: {len(tiny)} of {len(lines)}")
    odd = sorted(l["n"] for l in lines if TRACK_NAME.search(l["n"]))
    say(len(odd) > 0.02 * len(lines), f"names of tracks rather than lines: {len(odd)} {odd[:8]}")
    other = [l for l in lines if l["jk"] == "unknown"]
    say(sum(l["tk"] for l in other) > 0.01 * sum(l["tk"] for l in lines), f"lines of no known class: {len(other)}, {sum(l['tk'] for l in other)} km of track")

    # ---- colours
    fast = [f["properties"] for f in rail if "d" in f["properties"] and not f["properties"].get("mini")]       # the bands; a mini-Shinkansen's is a top speed
    bands = Counter((p["n"], p["c"], p["d"], "top speed, to verify" if p.get("e") else "design speed", (p.get("ref") or "no source")[:60]) for p in fast)
    bad = [k for k in bands if k[1] not in FAST or (k[4] == "no source" and k[3] == "design speed")]
    say(bad, f"lines coloured by speed: {len({k[0] for k in bands})}; bands {sorted({k[1] for k in bands})}; " + ("without a source: " + str(bad) if bad else "each has a source or is marked to verify"))
    for k in sorted(bands, key=lambda k: -k[2]):
        print(f"        {k[0]}: {k[2]} km/h -> {k[1]} ({k[3]}; {k[4]})", flush=True)
    say(sorted(facts.get("bands", [])) != sorted({k[1] for k in bands}), f"bands the card is told of: {facts.get('bands')}")
    clash = [p["n"] for p in fast if "lc" in p and not p.get("mini")]
    say(clash, f"fast lines that also carry a line colour (speed must win): {len(clash)}")
    # Japan's mini-Shinkansen: of the Shinkansen class, outside its speed band (process_jp.MINI)
    if code in MINI_LINES:
        sh = [l for l in lines if l["jk"] == "shinkansen"]
        mini = sorted(l["n"] for l in sh if l.get("mini"))
        band_km = sum(km(co) for f in rail if f["properties"].get("jk") == "shinkansen" and not f["properties"].get("mini") for co in parts_of(f))
        speeded = sorted({f["properties"]["n"] for f in rail if f["properties"].get("mini") and "d" in f["properties"] and not f["properties"].get("e")})
        say(len(mini) != MINI_LINES[code] or abs(band_km - facts.get("fast_km", 0)) > 1 or speeded,
            f"Shinkansen class: {len(sh)} lines, {len(mini)} of them mini-Shinkansen {mini} (expected {MINI_LINES[code]}), none with a design speed "
            f"{'' if not speeded else speeded}; the speed band {band_km:.0f} km (the card says {facts.get('fast_km')}), the class {facts.get('shinkansen_km')} km")
        tops = sorted({(f["properties"]["n"], f["properties"].get("d"), f["properties"].get("e"), f["properties"].get("ref")) for f in rail if f["properties"].get("mini")})
        say(any(d is None or not e or not ref for _, d, e, ref in tops), f"mini-Shinkansen top speeds (d with e, not a band): {tops}")
        # each is one path from one terminus to the other: no gap, nothing beyond either end
        dots = defaultdict(list)
        for f in stations:
            dots[f["properties"]["n"]].append(Point(f["geometry"]["coordinates"]))
        for name, rule in MINI.items():
            pieces = unary_union([LineString(co) for f in rail if f["properties"]["n"] == name for co in parts_of(f) if len(co) > 1])
            merged = linemerge(pieces) if not pieces.is_empty else pieces
            lines_ = [g for g in getattr(merged, "geoms", [merged]) if not g.is_empty]
            joined = unary_union([g.buffer(0.00015) for g in lines_])          # pieces less than about 30 m apart are one
            groups = len(getattr(joined, "geoms", [joined]))
            path = unary_union(lines_)
            ends = [Point(c) for g in lines_ for c in (g.coords[0], g.coords[-1])]
            loose = [e for e in ends if sum(1 for h in lines_ if h.distance(e) < 0.00015) == 1]       # an end that meets no other piece
            termini = {t: min((p.distance(path) for p in dots.get(t, [])), default=1) * 111320 for t in rule["ends"]}
            far = [(round(e.x, 4), round(e.y, 4)) for e in loose if min((e.distance(p) for t in rule["ends"] + rule["via"] for p in dots.get(t, [])), default=1) * 111320 > 500]
            length = sum(km(list(g.coords)) for g in lines_)
            say(groups != 1 or max(termini.values()) > 300 or far,
                f"{name}: {length:.1f} km drawn, {groups} connected piece(s); its termini " + ", ".join(f"{t} {m:.0f} m" for t, m in termini.items())
                + f" from the line; ends away from the termini{' and ' + '、'.join(rule['via']) if rule['via'] else ''}: {far}")
    own = Counter()
    for f in rail:
        if "lc" in f["properties"]:
            own[f["properties"]["lc"]] += sum(km(co) for co in parts_of(f))
    top = own.most_common(1)[0] if own else ("", 0)
    say(own and top[1] > 0.3 * sum(own.values()), f"railway with a line colour: {sum(own.values()):.0f} km ({sum(own.values()) / drawn_km:.0%}) in {len(own)} colours; "
        f"the commonest covers {top[1] / max(sum(own.values()), 1):.0%}" + (" (one colour on so much is likely a brand)" if own and top[1] > 0.3 * sum(own.values()) else ""))
    plain = Counter(l["n"] for c in cities for l in c["lines"] if l["col"].lower() == "#5cc8ff")
    say(len(plain) > 0.2 * max(sum(len(c["lines"]) for c in cities), 1), f"metro lines: {sum(len(c['lines']) for c in cities)} in {len(cities)} cities; without a colour of their own: {len(plain)} {sorted(plain)[:6]}")
    nowhere = [l["n"] for c in cities if c["n"].endswith("其他") for l in c["lines"]]
    say(False, f"metro lines outside the listed cities: {len(nowhere)} {nowhere[:8]}")

    # ---- stations
    say(not stations, f"stations: {len(stations)} ({sum(1 for f in stations if f['properties'].get('m'))} on metros and trams)")
    # a station with no drawn line passing it is a dot in the middle of nothing (Tokyo's 都電 stops, before the tramways were drawn)
    served = {id(f) for f in with_a_line(stations, [co for f in rail for co in parts_of(f)], [co for f in metro for co in parts_of(f)])}
    alone = [f for f in stations if id(f) not in served]
    say(alone, f"stations with no drawn line passing them: {len(alone)} ({sum(1 for f in alone if f['properties'].get('m'))} of them metro stations or tram stops) "
        + str([f["properties"]["n"] for f in alone[:8]]))

    # ---- the names on the yards and depots layer (scripts/depots.py)
    found, depot_audit = depot_check(code, DATA, ex)
    for bad, text in found:
        say(bad, text)

    # ---- the names beside n: nz and ne (scripts/names.py)
    found, names_audit = names_check(code, DATA)
    for bad, text in found:
        say(bad, text)

    report.update({"flags": flags, "breaks": cut, "twice": double, "track_names": odd, "bands": [list(k) for k in bands], "metro_without_colour": sorted(plain),
                   "depots": depot_audit, "names": names_audit,
                   "stations_without_a_line": [{"n": f["properties"]["n"], "at": f["geometry"]["coordinates"], "metro": bool(f["properties"].get("m"))} for f in alone]})
    print(f"   -> {len(flags)} to look at", flush=True)
    return report


if __name__ == "__main__":
    codes = sys.argv[1:] or ["jp", "uk", "kr"]
    OUT.mkdir(exist_ok=True)
    for code in codes:
        (OUT / f"check_{code}.json").write_text(json.dumps(check(code), ensure_ascii=False, indent=1))
