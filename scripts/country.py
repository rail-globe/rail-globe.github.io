"""The shared pipeline of the countries outside China (not Japan yet: scripts/process_jp.py came
first and has rules of its own for companies): from data/raw/extract_<code>.pkl to the layers
data/<code>_*.json that the page adds to its own. A country is a Country below plus a few
functions of its own; see scripts/process_uk.py and scripts/process_kr.py.

Colours follow the one rule for every country (user, 2026-10-08):
- a high-speed line is drawn in the band of its design speed, the same seven bands everywhere
  (property c = the band, d = the speed, e where the speed is only a top speed);
- any other railway is drawn in its own line colour where it has one (property lc), otherwise in
  the neutral colour of conventional lines (no lc);
- metros, light rail and trams are drawn in their official line colour.
A train company's brand colour is not a line colour and is not used. Route relations carry both
kinds, so they are told apart by what the company does with colour (line_colours below): a
company that gives its routes many different colours is colouring lines (ScotRail: North Clyde
blue, Argyle pink, Cathcart Circle yellow, 24 in all), one whose routes are all in one or two
colours is showing its brand (Great Western, South Western, Avanti), and so is the one colour
that most of a company's routes share.

A railway line is the track that carries its name in OSM, drawn once (scripts/single_track.py).
A metro or tram line is a route relation (or the relations of one route_master): its track
seldom carries the line's name (all of Manchester's Metrolink is "Metrolink").
"""
import json
import math
import pickle
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parent))
from design_speeds import grade
from process_jp import CURVE, TOL, adopt_unnamed, bbox_of, being_built, colour_of, geometry, km, readable_on_dark, rounded, runs_of
from side_by_side import abreast, side_by_side
from yards import write_yards
from single_track import join_up, one_track, stitch

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data"


@dataclass
class Country:
    code: str                                   # "uk": the extract, the files written and property g
    plain_name: Callable                        # a track's name -> the name of its line ("" for a structure)
    kind_of: Callable                           # (line name, track km by tags) -> the line's class (property jk)
    speed_of: Callable                          # (line name, class, track km by tags) -> (km/h, only a top speed?, source) or None
    cities: list                                # metro lines are listed by city: (name shown, lon, lat, reach in degrees)
    elsewhere: str                              # the "city" of metro lines outside all of those
    fast_kinds: tuple = ("hs",)                 # the classes counted as high-speed in the country's figures
    main_kinds: tuple = ("main",)               # the classes drawn at the width of a main line
    rail: frozenset = frozenset({"rail", "narrow_gauge"})
    urban: frozenset = frozenset({"subway", "light_rail", "tram"})
    skip_usage: frozenset = frozenset({"industrial", "military", "test", "freight", "crane", "siding", "training", "education", "science"})
    skip_stations: tuple = ("funicular", "miniature", "monorail")
    tag_keys: tuple = ("railway", "railway:preserved", "usage")     # the tags of a line's track that its class is read from
    minor_km: float = 1.5                       # a name on less track than this is a chord or a curve: it joins the line it connects
    metro_min_km: float = 2.0                   # shorter "lines" are airport shuttles and rides
    colour_networks: object = None              # networks of a few lines with official colours, however few colours that makes
    many_colours: int = 5                       # a company with this many colours on its routes is colouring lines, not showing a brand
    brand_share: float = 1 / 4                  # ... except for a colour on more than this share of its routes
    build_name: Callable = field(default=lambda name: name)        # the name of a line being built, from its track's name
    build_fast: Callable = field(default=lambda name: False)       # whether a line being built is a high-speed line


def line_colours(routes, networks=None, many=5, brand=1 / 4):
    """Which (company, colour) pairs on train routes are colours of lines, not of brands. routes:
    (company, colour, text naming the route's network) for every coloured route. A company with
    `many` colours on its routes is colouring lines, except for a colour on more than the share
    `brand` of its routes; `networks` matches networks of a few lines with official colours."""
    by = defaultdict(Counter)
    for firm, col, _ in routes:
        by[firm][col] += 1
    good = set()
    for firm, col, text in routes:
        lines = len(by[firm]) >= many and by[firm][col] <= brand * sum(by[firm].values())
        if firm and lines or (networks and networks.search(text)):
            good.add((firm, col))
    return good


def line_of_route(tags, master):
    """(network, line name, colour) of a metro or tram route relation."""
    network = tags.get("network") or master.get("network") or tags.get("operator") or master.get("operator") or ""
    name = master.get("name") or re.split(r":\s", tags.get("name") or "")[0] or tags.get("ref") or network
    if network and name.startswith(network + ":"):
        name = name[len(network) + 1:].strip()
    return network.strip(), re.sub(r"\s+", " ", name).strip(), colour_of(tags.get("colour") or master.get("colour"))


def run(cfg):
    """Everything for one country, from its extract to its data files. cfg: see Country."""
    # written locally by scripts/extract_osm.py, so loading it is safe here
    ex = pickle.load(open(RAW / f"extract_{cfg.code}.pkl", "rb"))
    ways = {wid: (t, co) for wid, t, co in ex["ways"]}
    length = {wid: km(co) for wid, (t, co) in ways.items()}
    relations = {rid: (t, members) for rid, t, members in ex["relations"]}

    # ---------------------------------------------------------------- railways: which line every track belongs to
    running = [wid for wid, (t, co) in ways.items() if t.get("railway") in cfg.rail and not t.get("service") and t.get("usage") not in cfg.skip_usage]
    named_km = Counter()
    for wid in running:
        named_km[cfg.plain_name(ways[wid][0].get("name"))] += length[wid]
    line_of, unnamed = {}, []
    for wid in running:
        name = cfg.plain_name(ways[wid][0].get("name"))
        if name and named_km[name] >= cfg.minor_km:
            line_of[wid] = ("rail", None, name)
        else:
            unnamed.append((wid, name))
    # A structure named for itself, a chord, and track with no name joins the line it connects,
    # stretch by stretch (process_jp.adopt_unnamed). What meets no line keeps its own name if it
    # has one, and is otherwise left undrawn.
    name_of = dict(unnamed)
    unnamed = [(wid, name_of[wid]) for wid in adopt_unnamed(line_of, [wid for wid, _ in unnamed], ways)]
    for wid, name in unnamed:
        if name:
            line_of[wid] = ("rail", None, name)
    lost = sum(length[w] for w, name in unnamed if not name)
    print(f"{cfg.code}: {len(line_of)} ways on named lines, {sum(length[w] for w in line_of):.0f} km of track; "
          f"{lost:.0f} km of running track left without a line", flush=True)
    tracks = defaultdict(list)                     # (layer, None, name) -> ways
    for wid, key in line_of.items():
        tracks[key].append(wid)

    # ---------------------------------------------------------------- the colour of a railway line
    votes = defaultdict(Counter)
    coloured = [(t, members, colour_of(t.get("colour"))) for t, members in relations.values()
                if t.get("type") == "route" and t.get("route") == "train" and colour_of(t.get("colour"))]
    text_of = lambda t: " ".join(filter(None, (t.get("network"), t.get("name"))))
    of_lines = line_colours([(t.get("operator") or "", col, text_of(t)) for t, _, col in coloured], cfg.colour_networks, cfg.many_colours, cfg.brand_share)
    print(f"{cfg.code}: companies whose route colours are line colours:",
          dict(Counter(firm for firm, _ in of_lines).most_common()), flush=True)
    # All the routes a company runs in one colour are taken together: a route relation holds one
    # direction only, half the track of a double line, and a line is often served by several.
    served = defaultdict(set)                      # (company, colour) -> track
    for t, members, col in coloured:
        firm = t.get("operator") or ""
        if (firm, col) in of_lines:
            served[(firm or t.get("network") or "", col)].update(ref for kind, ref in members if kind == "w" and ref in line_of)
    source = {}
    for (firm, col), wids in sorted(served.items()):
        on = Counter()
        for w in wids:
            on[line_of[w]] += length[w]
        for key, part in on.items():
            cover = part / sum(length[w] for w in tracks[key])
            if cover >= 0.6 and cover > votes[key][col]:      # these routes run over most of this line: the line is theirs
                votes[key][col] = cover
                source[(key, col)] = firm
    chosen = {key: max(cols.items(), key=lambda kv: (kv[1], kv[0]))[0] for key, cols in votes.items()}
    line_colour = {key: readable_on_dark(col) for key, col in chosen.items()}
    by_firm = Counter()
    for key, col in chosen.items():
        by_firm[source[(key, col)]] += sum(length[w] for w in tracks[key])
    print(f"{cfg.code}: track km of lines with a colour of their own, by the company of the route that gives it:",
          {k: round(v) for k, v in by_firm.most_common()}, flush=True)

    # ---------------------------------------------------------------- railways: each line drawn once
    rail_keys = sorted(tracks)
    once = {}
    for key in rail_keys:
        runs = runs_of([ways[w][1] for w in tracks[key]])
        once[key] = [runs, one_track(runs, keep=0.05, apart=0.004, apart_min=0.01)]
    closed = join_up(list(once.values()))
    print(f"{cfg.code} rail drawn once: {sum(g.length for r, _ in once.values() for g in r) * 100:.0f} -> "
          f"{sum(g.length for _, d in once.values() for g in d) * 100:.0f} (degrees x 100); gaps closed at junctions: {closed}", flush=True)
    rail_feats, lines_json = [], []
    for key in rail_keys:
        name = key[2]
        drawn = once[key][1]
        if not drawn:
            continue
        tags_km = Counter()
        for w in tracks[key]:
            t = ways[w][0]
            tags_km[tuple(sorted((k, t[k]) for k in cfg.tag_keys if t.get(k)))] += length[w]
        total = sum(length[w] for w in tracks[key])
        jk = cfg.kind_of(name, tags_km)
        fast = cfg.speed_of(name, jk, tags_km)       # (design speed, only a top speed?, source) of a high-speed line
        simp = rounded(stitch(runs_of([list(g.coords) for g in drawn])), TOL["fast" if fast else "rail"], CURVE["fast" if fast else "rail"], places=5)
        if not simp:
            continue
        props = {"c": "main" if jk in cfg.main_kinds else "branch", "n": name, "g": cfg.code, "jk": jk}
        if fast:                                     # speed before everything else
            speed, estimate, source = fast
            props.update({"c": grade(speed), "d": speed})
            if source:
                props["ref"] = source
            if estimate:
                props["e"] = 1
        elif key in line_colour:
            props["lc"] = line_colour[key]
        for seg_co in simp:
            rail_feats.append({"type": "Feature", "properties": dict(props), "geometry": geometry([seg_co])})
        row = {"n": name, "g": cfg.code, "jk": jk, "bbox": bbox_of(simp), "tk": round(total), "c": props["c"]}
        for k in ("lc", "d", "e", "ref"):
            if k in props:
                row[k] = props[k]
        lines_json.append(row)
    # The lines of one corridor each lie on their own track, a few metres apart: each gets its
    # place in the corridor (property off), as in Japan.
    whole = len(rail_feats)
    rail_feats = side_by_side(rail_feats, skip=lambda props: False, slots_of=abreast, min_run=0.006)
    print(f"{cfg.code} rail side by side: {whole} features written as {len(rail_feats)}, "
          f"{sum(1 for f in rail_feats if f['properties'].get('off'))} of them moved to a side", flush=True)

    # ---------------------------------------------------------------- metros, light rail and trams: by route relation
    master_of = {}
    for rid, (t, members) in relations.items():
        if t.get("type") == "route_master":
            for kind, ref in members:
                if kind == "r":
                    master_of[ref] = t
    routes = defaultdict(lambda: {"ways": set(), "kinds": Counter()})     # (network, line, colour) -> its track
    for rid, (t, members) in relations.items():
        if t.get("type") != "route" or t.get("route") not in cfg.urban:
            continue
        line = routes[line_of_route(t, master_of.get(rid, {}))]
        for kind, ref in members:
            if kind == "w" and ref in ways and ways[ref][0].get("railway") in cfg.urban | cfg.rail and not ways[ref][0].get("service"):
                line["ways"].add(ref)
                line["kinds"][t.get("route")] += length[ref]
    # The services of one network in one colour are one line (the five DLR services, both
    # directions of a circle): named after the network where there are several.
    merged = defaultdict(list)
    for (network, name, col), line in routes.items():
        merged[(network or name, col)].append((name, line))
    covered = set()
    metro_feats, metro_rows = [], []
    for (network, col), parts in sorted(merged.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        names = sorted({n for n, _ in parts})
        name = names[0] if len(names) == 1 else network
        wids = sorted(set().union(*(line["ways"] for _, line in parts)))
        kinds = sum((line["kinds"] for _, line in parts), Counter())
        if not wids:
            continue
        light = kinds["subway"] < sum(v for k, v in kinds.items() if k != "subway")
        drawn = stitch(one_track(runs_of([ways[w][1] for w in wids])), bends=True)
        simp = rounded(drawn, TOL["light" if light else "metro"], (6, 6, 0.00004) if light else (5, 4, 0.0003), adaptive=True)
        if not simp or sum(km(co) for co in simp) < cfg.metro_min_km:
            continue
        covered.update(wids)
        jk = "urban" if light else "subway"
        mid = LineString(max(simp, key=len)).interpolate(0.5, normalized=True)
        city = next((c[0] for c in cfg.cities if math.hypot((c[1] - mid.x) * math.cos(math.radians(mid.y)), c[2] - mid.y) < c[3]), cfg.elsewhere)
        shown = readable_on_dark(col) if col else "#5cc8ff"
        metro_feats.append({"type": "Feature", "properties": {"r": cfg.code.upper(), "g": cfg.code, "col": shown, "n": name, "ct": city, "jk": jk}, "geometry": geometry(simp)})
        metro_rows.append((city, {"n": name, "col": shown, "jk": jk, "km": round(sum(km(co) for co in simp)), "bbox": bbox_of(simp)}))
    metro_feats = side_by_side(metro_feats)
    urban_km = sum(length[w] for w, (t, co) in ways.items() if t.get("railway") in cfg.urban and not t.get("service"))
    print(f"{cfg.code} metro and tram: {len(metro_rows)} lines; {sum(length[w] for w in covered if ways[w][0].get('railway') in cfg.urban):.0f} "
          f"of {urban_km:.0f} km of their track is on a line drawn", flush=True)
    cities = {}
    for city, row in metro_rows:
        c = cities.setdefault(city, {"n": city, "km": 0, "bbox": list(row["bbox"]), "lines": []})
        c["km"] += row["km"]
        c["bbox"] = [min(c["bbox"][0], row["bbox"][0]), min(c["bbox"][1], row["bbox"][1]), max(c["bbox"][2], row["bbox"][2]), max(c["bbox"][3], row["bbox"][3])]
        c["lines"].append(row)
    for c in cities.values():
        c["lines"].sort(key=lambda r: r["n"])

    # ---------------------------------------------------------------- lines being built
    build_feats = being_built(ways, cfg.code, cfg.plain_name, cfg.build_name, cfg.build_fast)

    # ---------------------------------------------------------------- stations
    seen, stations = set(), []
    for t, lon, lat in ex["stations"]:
        name = re.sub(r"\s+", " ", t.get("name") or "").strip()
        kind = t.get("station") or ("subway" if t.get("subway") == "yes" else "light_rail" if t.get("light_rail") == "yes" else "")
        if not name or kind in cfg.skip_stations:
            continue
        metro = t.get("railway") == "tram_stop" or bool(set(re.split(r"[;,]", kind)) & cfg.urban)
        spot = (name, metro, round(lon * 300), round(lat * 300))          # one dot for the platforms of one station
        if spot in seen:
            continue
        seen.add(spot)
        props = {"n": name, "g": cfg.code}
        if metro:
            props["m"] = 1
        stations.append({"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}})

    # ---------------------------------------------------------------- write
    def write(name, obj):
        p = OUT / name
        p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        print(f"{name}: {p.stat().st_size / 1e6:.2f} MB", flush=True)

    def feat_km(f):
        return sum(km(co) for co in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]]))
    by_kind = Counter()
    for f in rail_feats:
        by_kind[f["properties"]["jk"]] += feat_km(f)
    write(f"{cfg.code}_rail.geojson", {"type": "FeatureCollection", "features": rail_feats})
    write(f"{cfg.code}_metro.geojson", {"type": "FeatureCollection", "features": metro_feats})
    write(f"{cfg.code}_build.geojson", {"type": "FeatureCollection", "features": build_feats})
    write(f"{cfg.code}_stations.geojson", {"type": "FeatureCollection", "features": stations})
    write(f"{cfg.code}_lines.json", sorted(lines_json, key=lambda r: -r["tk"]))
    write(f"{cfg.code}_metro_cities.json", sorted(cities.values(), key=lambda c: -c["km"]))
    write(f"{cfg.code}_facts.json", {"km": round(sum(by_kind.values())), "fast_km": round(sum(by_kind[k] for k in cfg.fast_kinds)), "bands": sorted({f["properties"]["c"] for f in rail_feats if "d" in f["properties"]})})
    print(f"{cfg.code} rail km drawn by kind:", {k: round(v) for k, v in by_kind.most_common()},
          "| with a line colour:", round(sum(feat_km(f) for f in rail_feats if "lc" in f["properties"])), flush=True)
    print(f"{cfg.code}: {len(lines_json)} railway lines, {sum(by_kind.values()):.0f} km drawn; {len(metro_rows)} metro and tram lines in {len(cities)} cities, "
          f"{sum(r['km'] for _, r in metro_rows)} km; {len(build_feats)} lines being built; {len(stations)} stations")
    write_yards(ex, cfg.code)

