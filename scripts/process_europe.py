"""European countries through the shared country pipeline.

    python3 scripts/process_europe.py de fr ch es nl be it at hu

Railways keep their local OSM infrastructure names, including unique names on
route=railway relations, never long-distance route=train service names. Class
and speed are read from each track's own tags after unnamed track is adopted:
neither a line's majority nor an adjacent track supplies a design standard.
OSM design tags and operating limits are separate evidence, linked to source ways.
Regular narrow-gauge railways remain ordinary railways; preserved and tourist
railways form the heritage class. S-Bahn, RER and Cercanias infrastructure remains
railway coverage; no unverified train-service overlay or company colour is added.
Unresolved infrastructure is retained without a name or a searchable line identity.
"""
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from country import Country, run
from europe_urban_policy import policy
from station_capsules import annotate as annotate_capsules
from europe_urban_colours import match_colour, colour_for
from europe_short_routes import minimum as short_route_minimum
from europe_build import construction_features
from process_jp import colour_of

STRUCTURE = re.compile(
    r"\b(?:Tunnel|Túnel|Tunel|Viadukt|Viaduc|Viaduct|Brücke|Pont|Puente|Ponte|"
    r"Flyover|Unterführung|Passage inférieur|Paso inferior)\b", re.I)
TRACK = re.compile(
    r"^(?:Gleis|Voie|Vía|Via|Binario|Track|Spoor)\s*[A-Z]?\d+(?:bis|ter)?[A-Z]?\b|"
    r"^(?:Up|Down)\b|\b(?:Up|Down)\s+(?:Fast|Slow|Goods|Relief)\b", re.I)
DIRECTIONAL_TRACK_SUFFIX = re.compile(
    r"(?:(?:\s*:\s*|\s+)(?:"
    r"(?:Gleis|Voie|Vía|Via|Binario|Track|Spoor)\s*[A-Z]?\d+(?:bis|ter)?[A-Z]?(?:\s*/.*)?|"
    r"(?:Voie|Vía|Via|Binario)\s+(?:pair(?:e)?|impair(?:e)?|pari|dispari)|"
    r")|\s+(?:Ost|West)(?:rohr|gleis))\s*$", re.I)
DESIGN_TAGS = ("maxspeed:design", "design_speed")
EVIDENCE_TAGS = ("railway", "railway:preserved", "usage", "highspeed", "maxspeed") + DESIGN_TAGS
URBAN_SOURCES = json.loads((Path(__file__).resolve().parents[1] / "data/europe_urban_sources.json").read_text())


def plain_name(name):
    name = re.sub(r"\s*[\[(（].*?[\])）]", "", name or "")
    name = re.split(r"\s*;\s*", name)[0]
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"^(Verbindungsgleis)\s*[12]$", r"\1", name, flags=re.I)
    before_suffix = name
    name = DIRECTIONAL_TRACK_SUFFIX.sub("", name).strip()
    if name != before_suffix:
        name = re.sub(r"\s*[-–—:]\s*$", "", name)
        if re.search(r"\b(?:al|alla|au|à|de|du|via|to|vers)$", name, re.I):
            return ""
    return "" if STRUCTURE.search(name) or TRACK.search(name) else name


def speed_values(value):
    """Only explicit positive speeds; country codes, signals and conditionals are not numbers."""
    found = []
    for part in re.split(r"[;,|]", value or ""):
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(mph|km/h|kmh|kph)?\s*", part, re.I)
        if not match:
            return ()
        number = float(match.group(1))
        if not 0 < number < 1000:
            return ()
        found.append(round(number * 1.609344 if (match.group(2) or "").lower() == "mph" else number))
    return tuple(sorted(set(found)))


def speed(value):
    """Highest explicit numeric value for inspection, not proof of a uniform design standard."""
    found = speed_values(value)
    return max(found) if found else None


def speed_evidence(tags):
    """(value, only an operating limit?, tag). Conflicting design tags remain unresolved."""
    design = [(key, speed_values(tags[key])) for key in DESIGN_TAGS if tags.get(key)]
    if design and all(len(values) == 1 for _, values in design):
        values = {values[0] for _, values in design}
        if len(values) == 1:
            return next(iter(values)), False, design[0][0]
    limit = speed_values(tags.get("maxspeed"))
    return (limit[0], True, "maxspeed") if len(limit) == 1 else None


def track_kind(tags):
    if tags.get("railway") == "preserved" or tags.get("railway:preserved") == "yes" or tags.get("usage") == "tourism":
        return "heritage"
    evidence = speed_evidence(tags)
    if evidence and (evidence[0] >= 200 or tags.get("highspeed") == "yes"):
        return "hs"
    return "main" if tags.get("usage") == "main" else "branch"


def stretch_of(name, tags, co):
    """An evidence discriminator, not a new line identity or a guessed geographic range."""
    return "osm:" + json.dumps({key: tags[key] for key in EVIDENCE_TAGS if tags.get(key)},
                              sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def uniform_tags(tags_km):
    rows = set()
    for row, length in tags_km.items():
        if length > 0:
            tags = dict(row)
            rows.add(tuple((key, tags[key]) for key in EVIDENCE_TAGS if tags.get(key)))
    if len(rows) > 1:
        raise ValueError("European classification requires track evidence stretches, not whole-line votes")
    return dict(next(iter(rows))) if rows else {}


def top_speed(tags_km):
    evidence = speed_evidence(uniform_tags(tags_km))
    return evidence[0] if evidence else None


def kind_of(name, tags_km):
    return track_kind(uniform_tags(tags_km))


def speed_of(name, kind, tags_km):
    evidence = speed_evidence(uniform_tags(tags_km))
    if kind == "hs" and evidence:
        value, estimate, tag = evidence
        return value, estimate, "OSM:" + tag
    return None


def rail_properties(tags_by_way):
    """Raw tags and all source way IDs bind the evidence scope in GeoJSON and the line index."""
    if not tags_by_way:
        return {"speed_basis": "unknown"}
    first = min(tags_by_way)
    tags = tags_by_way[first]
    evidence = speed_evidence(tags)
    props = {"source_way_ids": ",".join(str(wid) for wid in sorted(tags_by_way)),
             "osm_tags": json.dumps({key: tags[key] for key in EVIDENCE_TAGS if tags.get(key)},
                                    sort_keys=True, separators=(",", ":"), ensure_ascii=True),
             "speed_basis": "osm_maxspeed" if evidence and evidence[1] else "osm_design" if evidence else "unknown"}
    if evidence:
        value, estimate, tag = evidence
        props["ref"] = f"https://www.openstreetmap.org/way/{first}#{tag}"
        if not estimate:
            props["osm_design_speed"] = value
    limit = speed_values(tags.get("maxspeed"))
    if len(limit) == 1:
        props["osm_maxspeed"] = limit[0]
        props["maxspeed_ref"] = f"https://www.openstreetmap.org/way/{first}#maxspeed"
    if any(tags.get(key) for key in DESIGN_TAGS) and (not evidence or evidence[1]):
        props["design_unresolved"] = 1
    return props


def urban_line_of_route(tags, master):
    """Master/ref identifies a city line; a network prefix alone does not."""
    network = tags.get("network") or master.get("network") or tags.get("operator") or master.get("operator") or ""
    if (tags.get("operator") or master.get("operator")) == "Europa-Park Rust":
        # OSM r5504331/r5504333 are rides inside the park, regardless of length.
        # https://www.europapark.de/de/freizeitpark/attraktionen/ep-express-station-hotels
        return network.strip(), "", None
    if tags.get("name") == "Monorraíl T4":
        # OSM r11589012 is the airside T4–T4S shuttle, not a public urban line.
        # https://www.aena.es/en/adolfo-suarez-madrid-barajas/airport-services/transport-between-terminals.html
        return network.strip(), "", None
    name = master.get("name") or ""
    ref = master.get("ref") or tags.get("ref")
    if not name and ref:
        name = f"{network} {ref}".strip()
    if not name:
        # Without a master or ref, retain the full name. Truncating at ':' can merge a network.
        name = tags.get("name") or ""
    if network == "MetroTenerife":
        # Both directions of r1286854/r20281470 are explicitly Línea 2; only
        # one direction has ref=T2 and neither has a route_master in this source.
        match = re.match(r"^Tranv[ií]a Línea ([12])(?:\s*:|$)", tags.get("name") or "")
        if match:
            name = f"Tranvía Línea {match[1]}"
    col = colour_of(tags.get("colour") or master.get("colour"))
    for source in URBAN_SOURCES:
        if not source.get("g") and not source.get("osm_relations") and source.get("network") == network and source["n"] == name and source.get("colour"):
            col = source["colour"]
    return (network.strip(), re.sub(r"\s+", " ", name).strip(),
            col)


def dutch_urban_city(network, name, midpoint, fallback):
    # Actual route tags distinguish the overlapping Hague/Rotterdam areas,
    # including Rotterdam Metro E, which terminates at Den Haag Centraal.
    city = {
        "Rail Rotterdam": "鹿特丹", "Rail Haaglanden": "海牙",
        "Stadsvervoer Amsterdam": "阿姆斯特丹", "Utrecht Binnen": "乌得勒支",
    }.get(network)
    if city:
        return city
    # OSM r18501559 is the Rotterdam museum's circular tram, with network=no.
    return "鹿特丹" if (network, name) == ("no", "Tram 10") else fallback


def belgian_urban_line(tags, master):
    if (tags.get("network") or master.get("network")) == "Ilévia":
        # r449485/r7786749 are Lille Métro 2, included at the PBF clipping edge.
        return "Ilévia", "", None
    return urban_line_of_route(tags, master)


def hungarian_urban_line(tags, master):
    """A Hungarian city line is known by its number: M1, H5, 12 (BKK, Szeged, Debrecen, Miskolc).
    Most of Budapest's tram routes have no route_master name and network=local, which read
    "local 12"; Budapest's M1 has the name of its old company (Millenniumi Földalatti Vasút)."""
    network, name, col = urban_line_of_route(tags, master)
    ref = master.get("ref") or tags.get("ref")
    return network, (re.sub(r"\s+", " ", ref).strip() if name and ref else name), col


def austrian_urban_line(tags, master):
    """An Austrian city line without the ends written after it: "U1 Oberlaa <=> Leopoldau" is U1,
    "Linie 1: Universität – Auwiesen" Linie 1, "Tram 1: Innsbruck Bergisel <=> ..." Tram 1 (as
    Vienna's and Graz's own route masters write theirs: Tram 1)."""
    network, name, col = urban_line_of_route(tags, master)
    ref = master.get("ref") or tags.get("ref")
    if name and ":" in name:
        name = name.split(":")[0].strip()
    elif name and "<=>" in name and ref:
        name = ref
    return network, name, col


def station_display(stations, metro, extract):
    selected = [f for f in stations if f['properties'].get('m')]
    annotated = iter(annotate_capsules(selected, metro, stopping=extract.get('stops'),
                                     relations=extract.get('relations', ())))
    result = [next(annotated) if f['properties'].get('m') else f for f in stations]
    if stations and all(f['properties'].get('g') == 'it' for f in stations):
        # Source stop names remain intact for capsule evidence. The correction
        # changes only the final display label, with a pinned native-ID proof.
        import hashlib
        from station_display_names import correct_generated_station_names
        root = Path(__file__).resolve().parents[1]
        proof = json.loads((root / 'data/europe_station_display/it.json').read_text())
        extract_sha = hashlib.sha256((root / 'data/raw/extract_it.pkl').read_bytes()).hexdigest()
        result = correct_generated_station_names('it', result, extract_sha256=extract_sha, proof=proof)
    return result


COMMON = dict(
    plain_name=plain_name,
    minor_km=0,                                 # a short explicit infrastructure name is still evidence
    stretch_of=stretch_of,
    track_stretches=True,
    rail_seats=False,
    railway_relation_names=True,
    keep_unnamed_rail=True,
    construction_of=construction_features,
    rail_properties=rail_properties,
    urban_line_of=urban_line_of_route,
    merge_urban_by_colour=False,
    many_colours=None,                          # no sourced infrastructure line-colour networks yet
    kind_of=kind_of,
    speed_of=speed_of,
    fast_kinds=("hs",),
    main_kinds=("main",),
    rail=frozenset({"rail", "narrow_gauge", "preserved"}),
    urban=frozenset({"subway", "light_rail", "monorail", "tram"}),
    skip_usage=frozenset({"industrial", "military", "test", "freight", "crane", "siding", "training", "education", "science"}),
    skip_stations=("funicular", "miniature"),
    tag_keys=EVIDENCE_TAGS,
    urban_bundles=True,                         # every city's light rail and trams along shared centre lines (scripts/line_bundles.py)
    urban_policy=policy,
    urban_nearest_city=True,
    urban_station_display=station_display,
)

COUNTRIES = {
    "de": Country(code="de", cities=[
        ("柏林", 13.40, 52.52, 0.48), ("汉堡", 9.99, 53.55, 0.38),
        ("慕尼黑", 11.58, 48.14, 0.38), ("法兰克福", 8.68, 50.11, 0.42),
        ("科隆", 6.96, 50.94, 0.30), ("杜塞尔多夫", 6.78, 51.23, 0.25),
        ("鲁尔", 7.01, 51.46, 0.42), ("斯图加特", 9.18, 48.78, 0.32),
        ("纽伦堡", 11.08, 49.45, 0.28), ("汉诺威", 9.73, 52.37, 0.28),
        ("莱比锡", 12.37, 51.34, 0.25), ("德累斯顿", 13.74, 51.05, 0.25),
        ("不来梅", 8.80, 53.08, 0.24),
        ("卡尔斯鲁厄", 8.404, 49.010, 0.34),
        ("哈勒", 11.970, 51.483, 0.24),
    ], elsewhere="德国其他", **COMMON),
    "fr": Country(code="fr", cities=[
        ("巴黎", 2.35, 48.86, 0.82), ("里昂", 4.84, 45.76, 0.34),
        ("马赛", 5.37, 43.30, 0.34), ("里尔", 3.06, 50.63, 0.30),
        ("图卢兹", 1.44, 43.60, 0.32), ("波尔多", -0.58, 44.84, 0.32),
        ("斯特拉斯堡", 7.75, 48.58, 0.28), ("南特", -1.55, 47.22, 0.28),
        ("尼斯", 7.27, 43.70, 0.24), ("蒙彼利埃", 3.88, 43.61, 0.24),
        ("雷恩", -1.68, 48.11, 0.22), ("鲁昂", 1.10, 49.44, 0.22),
        ("格勒诺布尔", 5.72, 45.19, 0.20),
    ], elsewhere="法国其他", **COMMON),
    "ch": Country(code="ch", cities=[
        ("苏黎世", 8.54, 47.38, 0.34), ("日内瓦", 6.14, 46.20, 0.24),
        ("巴塞尔", 7.59, 47.56, 0.24), ("伯尔尼", 7.45, 46.95, 0.22),
        ("洛桑", 6.63, 46.52, 0.20), ("卢塞恩", 8.31, 47.05, 0.18),
        ("圣加仑", 9.38, 47.42, 0.18), ("卢加诺", 8.95, 46.00, 0.18),
    ], elsewhere="瑞士其他", **COMMON),
    "es": Country(code="es", cities=[
        ("马德里", -3.70, 40.42, 0.62), ("巴塞罗那", 2.17, 41.39, 0.48),
        ("瓦伦西亚", -0.38, 39.47, 0.34), ("塞维利亚", -5.99, 37.39, 0.32),
        ("毕尔巴鄂", -2.94, 43.26, 0.28), ("马拉加", -4.42, 36.72, 0.28),
        ("阿利坎特", -0.49, 38.35, 0.24), ("萨拉戈萨", -0.88, 41.65, 0.24),
        ("格拉纳达", -3.60, 37.18, 0.20), ("帕尔马", 2.65, 39.57, 0.24),
        ("圣克鲁斯-德特内里费", -16.25, 28.46, 0.28),
        ("拉斯帕尔马斯", -15.43, 28.12, 0.24),
    ], elsewhere="西班牙其他", **COMMON),
    "nl": Country(code="nl", cities=[
        ("海牙", 4.31, 52.08, 0.22), ("乌得勒支", 5.12, 52.09, 0.24),
        ("阿姆斯特丹", 4.90, 52.37, 0.34), ("鹿特丹", 4.48, 51.92, 0.34),
    ], elsewhere="荷兰其他", urban_city_of=dutch_urban_city, **COMMON),
    "be": Country(code="be", cities=[
        ("布鲁塞尔", 4.35, 50.85, 0.28), ("安特卫普", 4.40, 51.22, 0.28),
        ("根特", 3.72, 51.05, 0.24), ("沙勒罗瓦", 4.44, 50.41, 0.24),
        ("列日", 5.58, 50.63, 0.24), ("奥斯坦德", 2.92, 51.23, 0.44),
    ], elsewhere="比利时其他", **{**COMMON, "urban_line_of": belgian_urban_line}),
    "it": Country(code="it", cities=[
        ("布雷西亚", 10.21, 45.54, 0.22), ("贝加莫", 9.67, 45.70, 0.26),
        ("帕多瓦", 11.87, 45.41, 0.22),
        ("巴里", 16.869, 41.126, 0.26), ("波坦察", 15.8022077, 40.6384046, 0.24),
        ("卡塔尼亚", 15.0873718, 37.5023612, 0.22),
        ("科森扎", 16.2501929, 39.3099931, 0.20),
        ("萨莱诺", 14.7594542, 40.6803601, 0.20),
        ("罗马", 12.50, 41.90, 0.48), ("米兰", 9.19, 45.46, 0.48),
        ("那不勒斯", 14.25, 40.85, 0.32), ("都灵", 7.68, 45.07, 0.32),
        ("佛罗伦萨", 11.25, 43.77, 0.26), ("威尼斯", 12.33, 45.44, 0.30),
        ("热那亚", 8.93, 44.41, 0.30),
        ("博洛尼亚", 11.34, 44.49, 0.26), ("巴勒莫", 13.36, 38.12, 0.28),
        ("卡利亚里", 9.11, 39.22, 0.28), ("墨西拿", 15.55, 38.19, 0.20),
        ("萨萨里", 8.56, 40.73, 0.20), ("的里雅斯特", 13.77, 45.65, 0.22),
    ], elsewhere="意大利其他", **COMMON),
    # Austria and Hungary (2026-10-21, "加一下匈牙利奥地利"): the cities with metro, light rail or
    # trams (output/at-hu-research/findings.md, section 2). Innsbruck reaches Fulpmes (Stubaitalbahn),
    # Szeged Hódmezővásárhely (the tram-train); Gmunden's Traunseetram is 奥地利其他.
    "at": Country(code="at", cities=[
        ("维也纳", 16.37, 48.21, 0.30), ("格拉茨", 15.44, 47.07, 0.20),
        ("林茨", 14.29, 48.31, 0.20), ("因斯布鲁克", 11.40, 47.24, 0.22),
    ], elsewhere="奥地利其他", **{**COMMON, "urban_line_of": austrian_urban_line}),
    "hu": Country(code="hu", cities=[
        ("布达佩斯", 19.05, 47.50, 0.35), ("德布勒森", 21.63, 47.53, 0.15),
        ("米什科尔茨", 20.78, 48.10, 0.15), ("塞格德", 20.15, 46.25, 0.30),
    ], elsewhere="匈牙利其他", **{**COMMON, "urban_line_of": hungarian_urban_line}),
}

# Countries drawn on their own land alone. Geofabrik's extract of a country holds whole ways across
# its border (Austria's runs into Bavaria, South Tyrol and Slovenia; Hungary's into Slovakia,
# Romania and Serbia), and the countries around are drawn from their own extracts: each of these
# is cut at its own admin_level=2 boundary, which scripts/extract_osm.py keeps from the same file
# (iso=), as South-East Asia is (scripts/process_sea.py). The neighbours already drawn are cut at
# the same boundary (scripts/clip_neighbours.py), so both end on one line.
OWN_LAND = ("at", "hu")
VIEW_TOL = 0.01       # degrees: the outline the page tells the country by


def own_land(code):
    def prepare(ex):
        from process_sea import land_of
        from shapely.geometry import LineString, Point
        from shapely.prepared import prep
        land = land_of(ex["territory"])
        inside = prep(land)
        ways, cut, dropped = [], 0, 0
        for wid, t, co in ex["ways"]:
            line = LineString(co)
            if inside.contains(line):
                ways.append((wid, t, co))
                continue
            if not inside.intersects(line):
                dropped += 1
                continue
            part = line.intersection(land)
            pieces = [g for g in (part.geoms if hasattr(part, "geoms") else [part]) if g.geom_type == "LineString" and g.length > 0]
            cut += 1
            # (a sliver of a way that only grazes the border is one point once rounded: left out)
            pieces = [co for co in ([(round(x, 7), round(y, 7)) for x, y in piece.coords] for piece in pieces) if len(set(co)) > 1]
            for k, co in enumerate(pieces):
                # (a way that leaves and comes back: its second piece gets a number no OSM way has)
                ways.append((wid if k == 0 else wid * 1000 + k, t, co))
        keep = lambda lon, lat: inside.covers(Point(lon, lat))
        stations = [s for s in ex["stations"] if keep(s[1], s[2])]
        named = [o for o in ex.get("named") or [] if keep(*o["at"])]
        places = [p for p in ex.get("places") or [] if keep(p[2], p[3])]
        print(f"{code}: clipped to relation {ex['territory']['relation']} ({ex['territory']['name']}): "
              f"{len(ex['ways'])} ways -> {len(ways)} ({cut} cut at the border, {dropped} outside); "
              f"stations {len(ex['stations'])} -> {len(stations)}; named ground {len(ex.get('named') or [])} -> {len(named)}", flush=True)
        return {**ex, "ways": ways, "stations": stations, "named": named, "places": places}
    return prepare


def write_view(code):
    """The country's outline for the page (which country a place is in), simplified: data/<code>_view.json."""
    import pickle
    from shapely.geometry import MultiPolygon
    from process_sea import land_of
    from country import OUT
    with (OUT / "raw" / f"extract_{code}.pkl").open("rb") as stream:     # written locally by scripts/extract_osm.py
        territory = pickle.load(stream)["territory"]
    land = land_of(territory).simplify(VIEW_TOL, preserve_topology=True)
    polys = list(land.geoms) if isinstance(land, MultiPolygon) else [land]
    coords = [[[[round(x, 6), round(y, 6)] for x, y in poly.exterior.coords]] + [[[round(x, 6), round(y, 6)] for x, y in hole.coords] for hole in poly.interiors]
              for poly in polys]
    view = {"type": "MultiPolygon", "coordinates": coords,
            "source": {"relation": territory["relation"], "iso": territory["iso"], "tolerance_deg": VIEW_TOL}}
    (OUT / f"{code}_view.json").write_text(json.dumps(view, separators=(",", ":")))
    print(f"{code}_view.json: {sum(len(r) for p in coords for r in p)} points", flush=True)


for _code in OWN_LAND:
    COUNTRIES[_code].prepare = own_land(_code)

# The countries already drawn around each, whose lines it meets at the border.
DRAWN_AROUND = {"at": ("de", "ch", "it", "hu"), "hu": ("at",)}
MEET_M = 150          # metres: an own line end on the border this near a neighbour's line end is drawn on to it


def meet_neighbours(code):
    """Where a neighbour's railway line ends on the border and one of this country's drawn lines
    ends near it, but not on it, the line is drawn on to that point (as in South-East Asia,
    process_sea.meet_neighbours): both cut the track at the same border, but each draws one track
    of a double line, and at Hegyeshalom Hungary's line ended 4.5 m from Austria's."""
    import pickle
    from shapely.geometry import Point
    from process_sea import land_of
    from country import OUT
    from owned_output import atomic_json
    with (OUT / "raw" / f"extract_{code}.pkl").open("rb") as stream:     # written locally by scripts/extract_osm.py
        edge = land_of(pickle.load(stream)["territory"]).boundary
    metres = lambda a, b: math.hypot((a[0] - b[0]) * math.cos(math.radians((a[1] + b[1]) / 2)), a[1] - b[1]) * 111320
    parts_of = lambda f: f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]]
    on_border = lambda p: edge.distance(Point(p)) * 111320 < 2
    theirs = [(g, tuple(co[k])) for g in DRAWN_AROUND[code] if (OUT / f"{g}_rail.geojson").exists()
              for f in json.loads((OUT / f"{g}_rail.geojson").read_text())["features"] for co in parts_of(f) for k in (0, -1)
              if on_border(co[k])]
    path = OUT / f"{code}_rail.geojson"
    data = json.loads(path.read_text())
    met = []
    for f in data["features"]:
        for co in parts_of(f):
            for k in (0, -1):
                if not on_border(co[k]) or not theirs:
                    continue
                g, p = min(theirs, key=lambda e: metres(e[1], co[k]))
                d = metres(p, co[k])
                if 1.0 <= d <= MEET_M:
                    co.insert(0, list(p)) if k == 0 else co.append(list(p))
                    met.append({"line": f["properties"].get("n"), "neighbour": g, "at": list(p), "drawn_on_m": round(d, 1)})
    if met:
        atomic_json(path, data)
    print(f"{code}: lines drawn on to a neighbour's line end on the border: {met or 'none'}", flush=True)
    return met

# Every city of these countries, for a line of one country's "elsewhere" that is another's: the
# metro cities above and the city labels (capitals of regions, cantons and provinces).
PLACES = sorted({(lon, lat, code, name) for code, cfg in COUNTRIES.items() for name, lon, lat, _ in cfg.cities}
                | {(c["at"][0], c["at"][1], c["g"], c["n"]) for c in json.loads((Path(__file__).resolve().parents[1] / "data" / "cities.json").read_text())
                   if c.get("g") in COUNTRIES})
for cfg in COUNTRIES.values():
    cfg.urban_places = PLACES


def route_relations(code):
    """The ids of the route relations in a country's extract, from a small list kept beside it
    (data/raw/extract_<code>.pkl.routes.json), made again whenever the extract's SHA-256 changes."""
    import hashlib, pickle
    raw = Path(__file__).resolve().parents[1] / "data" / "raw"
    pkl = raw / f"extract_{code}.pkl"
    cache = Path(__file__).resolve().parents[1] / "data" / "cache" / "routes"
    kept = cache / f"extract_{code}.pkl.routes.json"
    if not pkl.exists():
        return set()
    sha = hashlib.sha256(pkl.read_bytes()).hexdigest()
    if kept.exists():
        old = json.loads(kept.read_text())
        if old.get("extract_sha256") == sha:
            return set(old["routes"])
    with pkl.open("rb") as stream:                # written locally by scripts/extract_osm.py
        ex = pickle.load(stream)
    routes = sorted(rid for rid, t, _ in ex["relations"] if t.get("type") == "route")
    del ex
    cache.mkdir(parents=True, exist_ok=True)
    kept.write_text(json.dumps({"extract": pkl.name, "extract_sha256": sha, "routes": routes}))
    return set(routes)

from ch_tram_seats import apply_ch_verified_profiles
from fr_tram_seats import apply_fr_tram_seats, canonical_route_key, validate_alias_sources

COUNTRIES["ch"].urban_seats = (
    lambda features, extract, sources:
    apply_ch_verified_profiles(features, sources=sources)
)
COUNTRIES["fr"].urban_preflight = validate_alias_sources
COUNTRIES["fr"].urban_route_key = canonical_route_key
COUNTRIES["fr"].urban_seats = (
    lambda features, extract, sources:
    apply_fr_tram_seats(features, extract=extract, sources=sources)
)
COUNTRIES['de'].urban_geographic_cities = ('鲁尔', '杜塞尔多夫')
COUNTRIES['ch'].urban_source_bound_cities = ('苏黎世','伯尔尼')
COUNTRIES['nl'].urban_source_bound_cities = ('海牙','阿姆斯特丹','鹿特丹')
COUNTRIES['fr'].urban_source_bound_cities = ('蒙彼利埃',)
COUNTRIES['es'].urban_source_bound_cities = ('瓦伦西亚','阿利坎特','马德里','毕尔巴鄂','巴塞罗那')
COUNTRIES['es'].urban_source_bound_identities = (
    ('es','Euskotren Tranbia','T1 (Ibaiondo - Salburua)','6601065,6601066'),
    ('es','Euskotren Tranbia','T2 (Unibertsitatea - Abetxuko)','6679948,6679966'),
)

from europe_directional_paths import directional_paths, approved_service_way as directional_service_way
from europe_terminal_paths import terminal_paths, approved_service_way as terminal_service_way

def reviewed_urban_paths(code, network, name, rids, ways, relations, drawn):
    selected = directional_paths(code, network, name, rids, ways, relations, drawn)
    return terminal_paths(code, network, name, rids, ways, relations, selected)

def reviewed_service_way(code, rid, wid, ways, relations):
    return (directional_service_way(code,rid,wid,ways,relations)
            or terminal_service_way(code,rid,wid,ways,relations))

for cfg in COUNTRIES.values():
    cfg.urban_drawn = reviewed_urban_paths
    cfg.urban_service_way = reviewed_service_way

from europe_hsr import install as install_hsr
from europe_identity_candidates import build_matcher, CANDIDATES

def install_service_identity(cfg):
    previous_preflight, previous_key = cfg.urban_preflight, cfg.urban_route_key
    def preflight(extract):
        if previous_preflight:
            previous_preflight(extract)
        masters = {rid:tags for rid,tags,_ in extract['relations'] if tags.get('type')=='route_master'}
        reviewed = {}
        for candidate in CANDIDATES:
            if candidate.country != cfg.code or candidate.master not in masters:
                continue
            tags = masters[candidate.master]
            official = colour_for(cfg.code,tags.get('network'),tags.get('name'),candidate.routes)
            if official:
                reviewed[candidate.master] = official
        aliases, audit = build_matcher(extract, cfg.code, reviewed_colours=reviewed)
        cfg.urban_route_key = lambda key, rid: aliases(previous_key(key, rid) if previous_key else key, rid)
        from country import OUT
        destination = OUT / 'audit' / 'service-identities'
        destination.mkdir(parents=True, exist_ok=True)
        (destination / f'{cfg.code}_service_identity.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    cfg.urban_preflight = preflight

for cfg in COUNTRIES.values():
    previous_key = cfg.urban_route_key
    def coloured_key(key, rid, code=cfg.code, previous=previous_key):
        return match_colour(code, previous(key, rid) if previous else key, rid)
    cfg.urban_route_key = coloured_key
    cfg.urban_minimum = lambda network, name, ids, default, code=cfg.code: short_route_minimum(code, network, name, ids, default)
    install_hsr(cfg)
    install_service_identity(cfg)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('codes',nargs='*',help='de fr ch es nl be it at hu (default: all)')
    parser.add_argument('--rail-only',action='store_true',help='rebuild native rail stages while retaining generated urban/station/yard products')
    args = parser.parse_args()
    codes = args.codes or list(COUNTRIES)
    if any(code not in COUNTRIES for code in codes):
        sys.exit("usage: python3 scripts/process_europe.py [de|fr|ch|es|nl|be|it|at|hu ...]")
    for code in codes:
        COUNTRIES[code].urban_abroad = {g: route_relations(g) for g in COUNTRIES if g != code}
        run(COUNTRIES[code],rail_only=args.rail_only)
        if code in OWN_LAND:
            write_view(code)
            meet_neighbours(code)
        from clip_neighbours import NEIGHBOURS, main as clip_neighbours
        if code in NEIGHBOURS:            # (its extract reaches into Austria: cut at Austria's border)
            clip_neighbours(code)
