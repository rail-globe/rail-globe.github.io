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

Every name stays the country's own (n); its Chinese and English names go beside it, as nz and ne
(scripts/names.py), and a metro city's own name as nl.
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
from process_jp import CURVE, TOL, adopt_unnamed, bbox_of, being_built, colour_of, geometry, km, readable_on_dark, rounded, runs_of, with_a_line
from side_by_side import abreast, side_by_side
from names import Names, city_names, name_city
from yards import write_yards
from single_track import join_up, one_copy, one_track, stitch

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data"


def filter_urban_display(features, rows, excluded_rids):
    """Remove verified event identities after layout without moving regular services.

    Mixed identities stay visible. The caller must supply source-verified route
    IDs, and every relation of a displayed identity must be excluded.
    """
    def hidden(props):
        try:
            ids = {int(value) for value in props.get('rid', '').split(',') if value}
        except (TypeError, ValueError):
            return False
        return bool(ids) and ids <= excluded_rids
    return ([f for f in features if not hidden(f['properties'])],
            [(city, row) for city, row in rows if not hidden(row)])


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
    stretch_of: Callable = field(default=lambda name, tags, co: None)     # (line name, a track's tags, its coordinates) -> the stretch
                                                # of the line it is on, where one line is classed in stretches (else None)
    urban_minimum: Callable = None              # network, name, source route IDs, default -> verified minimum
    metro_min_km: float = 2.0                   # shorter "lines" are airport shuttles and rides
    colour_networks: object = None              # networks of a few lines with official colours, however few colours that makes
    many_colours: int = 5                       # number of distinct line colours; None disables the company heuristic
    brand_share: float = 1 / 4                  # ... except for a colour on more than this share of its routes
    build_name: Callable = field(default=lambda name: name)        # the name of a line being built, from its track's name
    build_fast: Callable = field(default=lambda name: False)       # whether a line being built is a high-speed line
    railway_relation_names: bool = False        # unnamed track may take a unique route=railway infrastructure name
    track_stretches: bool = False               # adopt identities first, then read each track's own stretch evidence
    rail_seats: bool = True                     # move distinct railways apart where their selected paths overlap
    rail_properties: Callable = None            # tags by way ID -> additional sourced properties of a stretch
    urban_line_of: Callable = None              # an optional alternative to line_of_route
    merge_urban_by_colour: bool = True          # legacy UK/KR network-and-colour grouping
    keep_unnamed_rail: bool = False             # unassigned infrastructure is drawn, never named after a train service
    construction_of: Callable = None           # optional complete source coverage for construction
    urban_city_of: Callable = None             # network, name, midpoint, default city -> sourced city
    urban_preflight: Callable = None            # complete extract -> fail before route accumulation
    urban_route_key: Callable = None           # key, actual relation ID -> explicit identity correction
    urban_seats: Callable = None               # final features, extract, source rows -> features, ledger
    urban_bundles: object = ()                 # cities (or True: all) whose light rail is drawn along shared centre lines (scripts/line_bundles.py)
    urban_geographic_cities: tuple = ()         # explicitly reviewed cross-city bundle groups only
    urban_source_bound_identities: tuple = ()   # complete reviewed native services in a shared fallback ct
    urban_source_bound_cities: tuple = ()       # reviewed legacy cities using bidirectional source-safe graph reuse
    urban_places: object = ()                  # (lon, lat, country, name) of the cities of every country drawn: see below
    urban_abroad: object = None                # country -> the route relations in its extract (a line across a border is in both)
    urban_policy: Callable = None              # source-way European classification and exclusion policy
    urban_nearest_city: bool = False           # choose the nearest eligible city, preserving legacy defaults elsewhere
    urban_station_display: Callable = None      # stations, drawn metro, extract -> source-supported display metadata
    rail_capsules: bool = False                 # capsules at railway stations across the parallel railway lines that stop there
    urban_drawn: Callable = None               # code/network/name/rids/ways/relations/default drawn -> reviewed native paths
    urban_service_way: Callable = None         # exact source-qualified passenger service-track exception
    prepare: Callable = None                   # the extract as loaded -> the extract the pipeline reads (South-East Asia:
                                               # clipped to the country's own land, scripts/process_sea.py)
    urban_trains: Callable = None              # (route=train relation's tags, its route_master's) -> drawn as a metro line?
    urban_train_kind: str = "subway"           # ... and its class: a metro line's ("subway"), or one of its own
    urban_one_copy: bool = False               # a city line drawn out on one track and back on the other kept once (single_track.one_copy)
    urban_one_copy_left_out: tuple = ()        # ... but not in these cities, where the comparison with the drawing without it failed


PLATFORM_SIDING_KM = 2.0     # a station's platform track, not a yard
PLATFORM_GAP_M = 30          # the route has no running track of its own this near the siding's middle


def platform_siding(code, rid, wid, ways, relations, _taken={}):
    """Whether a siding a city line's route relation runs over is that line's platform track at a
    station (country.Country.urban_service_way). Bangkok's Dark Red Line stops at Don Mueang on
    two tracks tagged service=siding, and leaving them out cut the line for 790 m (2026-10-19).
    Only where the relation itself would otherwise break. The relation's siding members that meet
    end to end away from its running track are one run (Medan's Srilelawangsa line passes a station
    on two, 87 m and 717 m); a run is taken when both its outer ends are on the relation's own running
    track, it is under PLATFORM_SIDING_KM, and none of the relation's running track passes within
    PLATFORM_GAP_M of its middle (a platform loop beside a through track the route also uses is left
    out, as are crossovers, yards and spurs)."""
    key = (code, rid)
    if key not in _taken:
        _taken[key] = set()
        if rid in relations:
            from shapely.geometry import MultiLineString
            from shapely.ops import linemerge
            members = [w for kind, w in relations[rid][1] if kind == "w" and w in ways and len(ways[w][1]) > 1]
            lines = [ways[w][1] for w in members if not ways[w][0].get("service")]
            if lines:
                nodes, running = {tuple(p) for line in lines for p in line}, MultiLineString(lines)
                sidings = sorted({w for w in members if ways[w][0].get("service") == "siding"})
                group = {w: w for w in sidings}
                def root(w):
                    while group[w] != w:
                        w = group[w]
                    return w
                at = defaultdict(list)
                for w in sidings:
                    for end in (tuple(ways[w][1][0]), tuple(ways[w][1][-1])):
                        at[end].append(w)
                for end, ws in at.items():
                    if end not in nodes:                 # sidings meeting off the running track are one run
                        for w in ws[1:]:
                            group[root(w)] = root(ws[0])
                runs = defaultdict(list)
                for w in sidings:
                    runs[root(w)].append(w)
                for run in runs.values():
                    count = Counter(end for w in run for end in (tuple(ways[w][1][0]), tuple(ways[w][1][-1])))
                    outer = [end for end, n in count.items() if n == 1]
                    if len(outer) != 2 or not all(end in nodes for end in outer) \
                            or sum(km(ways[w][1]) for w in run) > PLATFORM_SIDING_KM:
                        continue
                    merged = linemerge([ways[w][1] for w in run])
                    if merged.geom_type != "LineString":
                        continue
                    if running.distance(merged.interpolate(0.5, normalized=True)) * 111320 > PLATFORM_GAP_M:
                        _taken[key].update(run)
    return wid in _taken[key]


def capsule_display(stations, metro, extract):
    """Capsules at a country's metro stations (scripts/station_capsules.py station_display)."""
    from station_capsules import station_display
    return station_display(stations, metro, extract)


# How a country is drawn since Europe, in one place ("处理欧洲的经验要沉淀下来", 2026-10-19).
# South-East Asia had been set up like the UK and Korea, the older way: Bangkok's Northern line
# was moved across the Dark Red Line and back and drawn on both sides of it, and no station had a
# capsule. Every country added from now on is Country(**LIKE_EUROPE, ...); the UK, Korea and
# Japan keep their own settings (tests/test_country_pipeline.py).
# - rail_seats off: every railway is drawn on its own track. Abroad each line is its own track a
#   few metres from the next; moving them apart by seats put one line on both sides of another.
# - merge_urban_by_colour off: each city line is its own, seated by class (jk), continuously; a
#   tram does not take part in the seats of the metro under it.
# - urban_bundles: light rail and trams on shared centre lines, the far view folded into one
#   corridor (scripts/line_bundles.py); the order kept at junctions only in the cities listed in
#   scripts/endpoint_sources.py ENDPOINT_CITIES, each once compared with its drawing without the order.
# - urban_station_display: capsules across the lines that stop at a metro station, the name
#   beside the capsule, one capsule for two same-named stations of one interchange.
# - urban_one_copy: a city line that a run drew out on one track of a double track and back on
#   the other is drawn once (single_track.one_copy; Budapest 59B, Vienna 27, Bremen 1: 2026-10-22).
# A country whose train services are drawn as city lines over its railways (Korea's 首都圈电铁,
# Bangkok's Red Lines, KTM Komuter, Jakarta's KRL) also sets rail_capsules=True.
LIKE_EUROPE = dict(rail_seats=False, merge_urban_by_colour=False, urban_bundles=True,
                   urban_station_display=capsule_display, urban_one_copy=True)


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
        lines = many is not None and len(by[firm]) >= many and by[firm][col] <= brand * sum(by[firm].values())
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


def english_of_route(tags, master):
    """The English name of a metro or tram route relation's line, read as line_of_route reads its name."""
    if master.get("name"):
        return {"name:en": master.get("name:en")}
    return {"name:en": re.split(r":\s", tags.get("name:en") or "")[0]}


def railway_tracks(cfg, ways, relations, length):
    """Assign infrastructure identities without letting adopted track inherit speed evidence."""
    running = [wid for wid, (t, co) in ways.items() if t.get("railway") in cfg.rail and not t.get("service") and t.get("usage") not in cfg.skip_usage]
    candidates = defaultdict(lambda: defaultdict(set))
    if cfg.railway_relation_names:
        running_set = set(running)
        for rid, (tags, members) in relations.items():
            if tags.get("type") != "route" or tags.get("route") != "railway":
                continue
            name = cfg.plain_name(tags.get("name"))
            if name:
                for kind, ref in members:
                    if kind == "w" and ref in running_set:
                        candidates[ref][name].add(rid)
    names, name_refs, ambiguous = {}, {}, set()
    for wid in running:
        name = cfg.plain_name(ways[wid][0].get("name"))
        choices = candidates.get(wid, {})
        if not name and len(choices) == 1:
            name = next(iter(choices))
            name_refs[wid] = choices[name]
        elif not name and len(choices) > 1:
            ambiguous.add(wid)                   # two physical identities are not a vote
        names[wid] = name
    named_km = Counter()
    for wid in running:
        named_km[names[wid]] += length[wid]
    line_of, unnamed = {}, []
    for wid in running:
        name = names[wid]
        if name and (named_km[name] >= cfg.minor_km or name in candidates.get(wid, {})):
            stretch = None if cfg.track_stretches else cfg.stretch_of(name, *ways[wid])
            line_of[wid] = ("rail", stretch, name)
        else:
            unnamed.append((wid, name))
    name_of = dict(unnamed)
    if cfg.track_stretches:
        from rail_sections import adopt_track_gaps
        adopt = adopt_track_gaps
    else:
        adopt = adopt_unnamed
    left = adopt(line_of, [wid for wid, _ in unnamed if wid not in ambiguous], ways)
    unnamed = [(wid, name_of[wid]) for wid in left + sorted(ambiguous)]
    for wid, name in unnamed:
        if name:
            line_of[wid] = ("rail", cfg.stretch_of(name, *ways[wid]), name)
    if cfg.track_stretches:
        for wid, key in line_of.items():
            line_of[wid] = ("rail", cfg.stretch_of(key[2], *ways[wid]), key[2])
    if cfg.keep_unnamed_rail:
        # Connected unresolved track is coverage, not proof of a named entity. A component ID
        # keeps separate unlabelled networks apart; speeds still come from individual track.
        bare = {wid for wid, name in unnamed if not name}
        at = defaultdict(list)
        for wid in sorted(bare):
            for end in (ways[wid][1][0], ways[wid][1][-1]):
                at[end].append(wid)
        for root in sorted(bare):
            if root not in bare:
                continue
            pending = [root]
            bare.remove(root)
            while pending:
                wid = pending.pop()
                stretch = cfg.stretch_of("", *ways[wid])
                line_of[wid] = ("rail", f"unnamed:w{root}:{stretch or ''}", "")
                for end in (ways[wid][1][0], ways[wid][1][-1]):
                    for other in at.pop(end, ()):
                        if other in bare:
                            bare.remove(other)
                            pending.append(other)
    tracks = defaultdict(list)
    for wid, key in line_of.items():
        tracks[key].append(wid)
    return tracks, line_of, unnamed, name_refs


def railway_properties(cfg, key, wids, ways, length, line_colour=None, name_refs=None):
    """The same class, speed and source properties for geometry and its index row."""
    name = key[2]
    tags_km = Counter()
    for wid in wids:
        tags = ways[wid][0]
        tags_km[tuple(sorted((k, tags[k]) for k in cfg.tag_keys if tags.get(k)))] += length[wid]
    jk = cfg.kind_of(name, tags_km)
    fast = cfg.speed_of(name, jk, tags_km)
    props = {"c": "main" if jk in cfg.main_kinds else "branch", "n": name, "g": cfg.code, "jk": jk}
    if not name and cfg.keep_unnamed_rail:
        props["unnamed"] = 1
    if key[1]:
        props["st"] = key[1]
    if fast:
        speed, estimate, source = fast
        props.update({"c": grade(speed), "d": speed})
        if source:
            props["ref"] = source
        if estimate:
            props["e"] = 1
    elif line_colour:
        props["lc"] = line_colour
    if cfg.rail_properties:
        props.update(cfg.rail_properties({wid: ways[wid][0] for wid in wids}))
    refs = sorted({rid for wid in wids for rid in (name_refs or {}).get(wid, ())})
    if refs:
        props["name_ref"] = " ".join(f"https://www.openstreetmap.org/relation/{rid}#name" for rid in refs)
    return props, fast


def whole_line_rows(cfg, rows, track_km=None):
    """Keep a selectable whole-line row, without assigning a mixed line one design speed."""
    if not cfg.track_stretches:
        return rows
    rows = [row for row in rows if row.get("n")]
    by_name = defaultdict(list)
    for row in rows:
        by_name[row["n"]].append(row)
    result = list(rows)
    for parts in by_name.values():
        if len(parts) == 1:
            result.append({k: v for k, v in parts[0].items() if k != "st"})
            continue
        # The list class means "contains this class", not a class propagated back to track.
        order = cfg.fast_kinds + cfg.main_kinds + ("branch", "heritage")
        first = min(parts, key=lambda p: order.index(p["jk"]) if p["jk"] in order else len(order))
        row = {k: first[k] for k in ("n", "g", "jk", "c", "nz", "ne") if k in first}
        row.update({
            "bbox": [min(p["bbox"][0] for p in parts), min(p["bbox"][1] for p in parts),
                     max(p["bbox"][2] for p in parts), max(p["bbox"][3] for p in parts)],
            "tk": round(track_km[parts[0]["n"]]) if track_km is not None else sum(p["tk"] for p in parts),
            "grades": sorted({p["c"] for p in parts}),
            "kinds": sorted({p["jk"] for p in parts}),
            "speed_sections": [{k: v for k, v in p.items() if k not in ("n", "g", "nz", "ne", "tk")}
                               for p in parts],
        })
        result.append(row)
    return result


def urban_groups(cfg, routes):
    """Europe keeps line identities even without colours; default grouping is unchanged."""
    merged = defaultdict(list)
    for (network, name, col), line in routes.items():
        key = (network or name, col) if cfg.merge_urban_by_colour else (network, name, col)
        merged[key].append((name, line))
    return merged


def run(cfg, *, rail_only=False):
    """Everything for one country, from its extract to its data files. cfg: see Country."""
    from owned_output import require_owned, atomic_json
    require_owned(OUT, [f'{cfg.code}_{suffix}' for suffix in (
        'rail.geojson', 'metro.geojson', 'build.geojson', 'stations.geojson',
        'lines.json', 'metro_cities.json', 'facts.json', 'yards.geojson', 'depots.geojson')])
    # written locally by scripts/extract_osm.py, so loading it is safe here
    extract_path = RAW / f"extract_{cfg.code}.pkl"
    with extract_path.open("rb") as stream:
        ex = pickle.load(stream)
    if cfg.prepare:
        ex = cfg.prepare(ex)
    if cfg.urban_preflight:
        cfg.urban_preflight(ex)
    ways = {wid: (t, co) for wid, t, co in ex["ways"]}
    length = {wid: km(co) for wid, (t, co) in ways.items()}
    relations = {rid: (t, members) for rid, t, members in ex["relations"]}
    urban_policy_audit = {"routes_excluded": [], "lines": []}
    if cfg.urban_policy:
        from europe_urban_policy import load_relations, route_exclusion
        relations = load_relations(cfg.code, extract_path, relations, ex.get("relation_tag_schema", ()))
    namer = Names(cfg.code)

    # ---------------------------------------------------------------- railways: which line every track belongs to
    tracks, line_of, unnamed, name_refs = railway_tracks(cfg, ways, relations, length)
    lost = sum(length[w] for w, name in unnamed if not name and w not in line_of)
    coverage = "ways on railway coverage" if cfg.keep_unnamed_rail else "ways on named lines"
    print(f"{cfg.code}: {len(line_of)} {coverage}, {sum(length[w] for w in line_of):.0f} km of track; "
          f"{lost:.0f} km of running track left without a line", flush=True)
    if cfg.keep_unnamed_rail:
        print(f"{cfg.code}: {sum(length[w] for w, key in line_of.items() if not key[2]):.0f} km "
              "of unresolved track retained as unlabelled railway coverage", flush=True)
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
    rail_keys = sorted(tracks, key=lambda key: (key[0], key[2], key[1] or ""))
    chosen_sources = None
    if cfg.track_stretches:
        from rail_sections import draw_sections
        once, chosen_sources, closed = draw_sections(tracks, ways, line_of)
        for key in once:
            tracks.setdefault(key, [])
        rail_keys = sorted(once, key=lambda key: (key[0], key[2], key[1] or ""))
    else:
        once = {}
        for key in rail_keys:
            runs = runs_of([ways[w][1] for w in tracks[key]])
            once[key] = [runs, one_track(runs, keep=0.05, apart=0.004, apart_min=0.01)]
        closed = join_up(list(once.values()))
    print(f"{cfg.code} rail drawn once: {sum(g.length for r, _ in once.values() for g in r) * 100:.0f} -> "
          f"{sum(g.length for _, d in once.values() for g in d) * 100:.0f} (degrees x 100); gaps closed at junctions: {closed}", flush=True)
    rail_feats, lines_json = [], []
    line_km = Counter()
    for key in rail_keys:
        name = key[2]
        drawn = once[key][1]
        if not drawn:
            continue
        total = sum(length[w] for w in tracks[key])
        if name:
            for w in tracks[key]:
                namer.add(name, ways[w][0], length[w])
                for rid in sorted(name_refs.get(w, ())):
                    namer.add(name, relations[rid][0], length[w])
        source_wids = sorted(chosen_sources[key]) if chosen_sources is not None else tracks[key]
        props, fast = railway_properties(cfg, key, source_wids, ways, length, line_colour.get(key), name_refs)
        if chosen_sources is not None and not source_wids:
            props["display_join"] = 1
        paths = drawn if cfg.track_stretches else stitch(runs_of([list(g.coords) for g in drawn]))
        simp = rounded(paths, TOL["fast" if fast else "rail"], CURVE["fast" if fast else "rail"], places=5)
        if not simp:
            continue
        namer.line(props)
        for seg_co in simp:
            rail_feats.append({"type": "Feature", "properties": dict(props), "geometry": geometry([seg_co])})
        row = {"n": name, "g": cfg.code, "jk": props["jk"], "bbox": bbox_of(simp), "tk": round(total), "c": props["c"]}
        for k in ("lc", "d", "e", "ref", "st"):
            if k in props:
                row[k] = props[k]
        if cfg.rail_properties or cfg.railway_relation_names:
            row.update({k: v for k, v in props.items() if k not in row and k not in ("nz", "ne")})
        if name:                                    # unnamed coverage is not a fabricated searchable line
            lines_json.append(namer.copy(row, props))
            line_km[name] += total
    lines_json = whole_line_rows(cfg, lines_json, line_km)
    # The lines of one corridor each lie on their own track, a few metres apart: each gets its
    # place in the corridor (property off), as in Japan.
    whole = len(rail_feats)
    if cfg.rail_seats:
        rail_feats = side_by_side(rail_feats, skip=lambda props: False, slots_of=abreast,
                                 min_run=0.006)
    print(f"{cfg.code} rail side by side: {whole} features written as {len(rail_feats)}, "
          f"{sum(1 for f in rail_feats if f['properties'].get('off'))} of them moved to a side", flush=True)

    if rail_only:
        # Rebuild rail from native ways and the same normal stages. Urban output,
        # station Points and yards remain the separately generated products.
        build_feats = cfg.construction_of(cfg, ways, namer) if cfg.construction_of else []
        by_kind = Counter()
        for f in rail_feats:
            co = f['geometry']['coordinates']
            by_kind[f['properties']['jk']] += sum(km(p) for p in co) if f['geometry']['type']=='MultiLineString' else km(co)
        products = {
            f'{cfg.code}_rail.geojson': {'type':'FeatureCollection','features':rail_feats},
            f'{cfg.code}_build.geojson': {'type':'FeatureCollection','features':build_feats},
            f'{cfg.code}_lines.json': sorted(lines_json, key=lambda r:-r['tk']),
            f'{cfg.code}_facts.json': {'km':round(sum(by_kind.values())),
                                     'fast_km':round(sum(by_kind[k] for k in cfg.fast_kinds)),
                                     'bands':sorted({f['properties']['c'] for f in rail_feats if 'd' in f['properties']})},
        }
        for filename, obj in products.items():
            atomic_json(OUT / filename, obj)
        print(f'{cfg.code}: native rail rebuild complete; {len(rail_feats)} features, urban products retained',flush=True)
        return

    # ---------------------------------------------------------------- metros, light rail and trams: by route relation
    master_of = {}
    for rid, (t, members) in relations.items():
        if t.get("type") == "route_master":
            for kind, ref in members:
                if kind == "r":
                    master_of[ref] = t
    routes = defaultdict(lambda: {"ways": set(), "kinds": Counter(), "en": [], "relations": []})     # (network, line, colour) -> its track
    post_layout_exclusions = set()
    for rid, (t, members) in relations.items():
        # A train route may be an urban line of its own (cfg.urban_trains: Kuala Lumpur's KTM
        # Komuter, the airport lines): drawn over the railway it runs on, as a metro line.
        as_metro = (cfg.urban_trains is not None and t.get("type") == "route" and t.get("route") == "train"
                    and cfg.urban_trains(t, master_of.get(rid, {})))
        if t.get("type") != "route" or t.get("route") not in cfg.urban and not as_metro:
            continue
        if cfg.urban_policy:
            excluded = route_exclusion(cfg.code, rid, t, master_of.get(rid, {}),
                                       ways=ways, relations=relations)
            if excluded:
                deferred = excluded == 'verified-feyenoord-event-service'
                urban_policy_audit["routes_excluded"].append({
                    "rid": rid, "reason": excluded,
                    "stage": "after-layout" if deferred else "before-grouping"})
                if deferred:
                    post_layout_exclusions.add(rid)
                else:
                    continue
        key = (cfg.urban_line_of or line_of_route)(t, master_of.get(rid, {}))
        if cfg.urban_line_of and not key[1]:
            continue
        if cfg.urban_route_key:
            key = cfg.urban_route_key(key, rid)
        line = routes[key]
        line["relations"].append(rid)
        master = master_of.get(rid, {})
        if not cfg.urban_line_of or master.get("name") or t.get("name") == key[1]:
            line["en"].append(english_of_route(t, master))
        for kind, ref in members:
            if (kind == "w" and ref in ways and ways[ref][0].get("railway") in cfg.urban | cfg.rail
                    and (not ways[ref][0].get("service") or cfg.urban_service_way
                         and cfg.urban_service_way(cfg.code,rid,ref,ways,relations))):
                line["ways"].add(ref)
                line["kinds"][cfg.urban_train_kind if as_metro else t.get("route")] += length[ref]
    # The services of one network in one colour are one line (the five DLR services, both
    # directions of a circle): named after the network where there are several.
    merged = urban_groups(cfg, routes)

    def city_at(network, name, mid):
        """The city a line belongs to, by the middle of its longest piece."""
        if cfg.urban_nearest_city:
            from europe_urban_policy import nearest_city
            city = nearest_city(cfg.cities, mid, cfg.elsewhere)
        else:
            city = next((c[0] for c in cfg.cities if math.hypot((c[1] - mid.x) * math.cos(math.radians(mid.y)), c[2] - mid.y) < c[3]), cfg.elsewhere)
        if cfg.urban_city_of:
            city = cfg.urban_city_of(network, name, mid, city)
        return city
    covered = set()
    metro_feats, metro_rows, urban_sources = [], [], []
    applied_geometry = set()
    for group_key, parts in sorted(merged.items(), key=lambda kv: tuple(v or "" for v in kv[0])):
        network, col = group_key[0], group_key[-1]
        names = sorted({n for n, _ in parts})
        name = names[0] if len(names) == 1 else network
        wids = sorted(set().union(*(line["ways"] for _, line in parts)))
        kinds = sum((line["kinds"] for _, line in parts), Counter())
        if not wids:
            continue
        light = kinds["subway"] < sum(v for k, v in kinds.items() if k != "subway")
        # train routes drawn as a class of their own (Jakarta's KRL: cfg.urban_train_kind "commuter")
        own_class = cfg.urban_train_kind if cfg.urban_train_kind != "subway" and kinds[cfg.urban_train_kind] * 2 >= sum(kinds.values()) else None
        if own_class:
            light = False
        source_relations = sorted({rid for _, line in parts for rid in line["relations"]})
        if cfg.urban_policy:
            decision = cfg.urban_policy(cfg.code, wids, ways, length, source_relations,
                                        relations, "urban" if light else "subway")
            urban_policy_audit["lines"].append({"name": name, "network": network,
                                               "relations": source_relations, **decision})
            if not decision["keep"]:
                continue
            light = decision["jk"] == "urban"
        drawn = stitch(one_track(runs_of([ways[w][1] for w in wids])), bends=True)
        if cfg.urban_one_copy:
            # after stitch(): it joins ends up to 120 m apart, and would draw a short removed copy again
            once = one_copy(drawn)
            if once is not drawn and cfg.urban_one_copy_left_out:
                # a city left out keeps the line as it was: its city as the line is drawn without it
                kept = cfg.urban_drawn(cfg.code, network, name, source_relations, ways, relations, drawn) if cfg.urban_drawn else drawn
                rough = rounded(kept, TOL["light" if light else "metro"], (6, 6, 0.00004) if light else (5, 4, 0.0003), adaptive=True)
                if rough and city_at(network, name, LineString(max(rough, key=len)).interpolate(0.5, normalized=True)) in cfg.urban_one_copy_left_out:
                    once = drawn
            drawn = once
        if cfg.urban_drawn:
            original_drawn = drawn
            drawn = cfg.urban_drawn(cfg.code, network, name, source_relations, ways, relations, drawn)
            if drawn is not original_drawn:
                applied_geometry.add((network, name, tuple(source_relations)))
        simp = rounded(drawn, TOL["light" if light else "metro"], (6, 6, 0.00004) if light else (5, 4, 0.0003), adaptive=True)
        minimum = cfg.urban_minimum(network, name, source_relations, cfg.metro_min_km) if cfg.urban_minimum else cfg.metro_min_km
        if not simp or sum(km(co) for co in simp) < minimum:
            continue
        covered.update(wids)
        jk = own_class or ("urban" if light else "subway")
        mid = LineString(max(simp, key=len)).interpolate(0.5, normalized=True)
        city = city_at(network, name, mid)
        if city == cfg.elsewhere and cfg.urban_places and cfg.urban_abroad:
            # A tram line across a border, or near one, is in both countries' extracts whole
            # (Basel's in France's and Germany's, Geneva's in France's). Outside this country's
            # cities, a line whose relations another country's extract has too, and whose nearest
            # city of the two countries is that one's, is that country's to draw: it is left out
            # here. A line only this extract has stays, however near a foreign city (Mulhouse's
            # trams are nearer Basel than any French city in the list).
            mine = {rid for _, line in parts for rid in line["relations"]}
            both = {g for g, ids in cfg.urban_abroad.items() if mine & ids}
            if both:
                near = min((p for p in cfg.urban_places if p[2] in both | {cfg.code}),
                           key=lambda p: math.hypot((p[0] - mid.x) * math.cos(math.radians(mid.y)), p[1] - mid.y))
                if near[2] != cfg.code:
                    print(f"{cfg.code}: urban line {network} / {name} is left to {near[2]}, nearest {near[3]}", flush=True)
                    continue
        shown = readable_on_dark(col) if col else "#5cc8ff"
        for part_name, line in parts:
            if part_name == name:                    # a line named after its network has no English name of its own here
                for tags in line["en"]:
                    namer.add(name, tags)
        props = namer.line({"r": cfg.code.upper(), "g": cfg.code, "col": shown, "n": name, "ct": city, "jk": jk})
        if not cfg.merge_urban_by_colour:
            # Same-named services in different networks (e.g. Basel Tram 8)
            # keep their actual source identities through later seating passes.
            props.update({"network": network, "rid": ",".join(map(str, source_relations))})
        metro_feats.append({"type": "Feature", "properties": props, "geometry": geometry(simp)})
        row = namer.copy({"n": name, "col": shown, "jk": jk, "km": round(sum(km(co) for co in simp)), "bbox": bbox_of(simp)}, props)
        if not cfg.merge_urban_by_colour:
            row.update({"network": network, "rid": props["rid"]})
        metro_rows.append((city, row))
        urban_sources.append({"ct": city, "name": name, "network": network, "col": shown,
                              "way_ids": wids,
                              "relations": source_relations,
                              "route_kinds": dict(kinds)})
    metro_feats = side_by_side(
        metro_feats, continuous=not cfg.merge_urban_by_colour,
        group_of=(lambda props: props.get("jk")) if not cfg.merge_urban_by_colour else None,
    )
    # Hand-placed tram seats are replaced as a whole when every city's light rail is bundled.
    if cfg.urban_seats and cfg.urban_bundles is not True:
        metro_feats, ledger = cfg.urban_seats(metro_feats, ex, urban_sources)
        audit_path = ROOT / "output" / f"{cfg.code}_tram_seats.json"
        audit_path.parent.mkdir(exist_ok=True)
        audit_path.write_text(json.dumps({"country": cfg.code, "sources": urban_sources,
                                         "changes": ledger}, ensure_ascii=False, indent=2) + "\n")
    if cfg.urban_bundles:
        from line_bundles import apply as bundle
        from endpoint_sources import build_sources, endpoint_cities_of
        endpoint_cities = endpoint_cities_of(cfg.code, metro_feats)
        if endpoint_cities:
            endpoint_source = build_sources(
                [f for f in metro_feats if f["properties"].get("ct") in endpoint_cities],
                ways, relations, cfg.urban | cfg.rail,
            )
            metro_feats = bundle(metro_feats, cfg.code, cfg.urban_bundles,
                                 source=endpoint_source, endpoint_cities=endpoint_cities,
                                 geographic_cities=cfg.urban_geographic_cities,
                                 source_bound_cities=cfg.urban_source_bound_cities,
                                 source_bound_identities=cfg.urban_source_bound_identities)
        else:
            metro_feats = bundle(metro_feats, cfg.code, cfg.urban_bundles,
                                 geographic_cities=cfg.urban_geographic_cities,
                                 source_bound_cities=cfg.urban_source_bound_cities,
                                 source_bound_identities=cfg.urban_source_bound_identities)
    if applied_geometry:
        # Direction paths may share the same physical course. Report the final
        # drawn centre length, rather than summing both source directions.
        drawn_lengths = Counter()
        for f in metro_feats:
            p = f['properties']
            identity = (p.get('network'),p['n'],tuple(int(r) for r in p.get('rid','').split(',') if r))
            if identity in applied_geometry:
                co = f['geometry']['coordinates']
                drawn_lengths[identity] += sum(km(part) for part in co) if f['geometry']['type']=='MultiLineString' else km(co)
        for _, row in metro_rows:
            identity = (row.get('network'),row['n'],tuple(int(r) for r in row.get('rid','').split(',') if r))
            if identity in applied_geometry:
                row['input_path_km'] = row['km']
                row['km'] = round(drawn_lengths[identity])
    if post_layout_exclusions:
        metro_feats, metro_rows = filter_urban_display(
            metro_feats, metro_rows, post_layout_exclusions)
    audit = OUT / 'audit'
    audit.mkdir(exist_ok=True)
    atomic_json(audit / f'{cfg.code}_native_direction_paths.json', {
        'scope':'complete reviewed directions; list km is drawn centre geometry, not operating or track distance',
        'applied':[r for r in urban_sources if (r['network'],r['name'],tuple(r['relations'])) in applied_geometry]})
    urban_km = sum(length[w] for w, (t, co) in ways.items() if t.get("railway") in cfg.urban and not t.get("service"))
    if cfg.urban_policy:
        audit_path = OUT / "audit" / f"{cfg.code}_urban_policy.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(urban_policy_audit, ensure_ascii=False, indent=2) + "\n")
    print(f"{cfg.code} metro and tram: {len(metro_rows)} lines; {sum(length[w] for w in covered if ways[w][0].get('railway') in cfg.urban):.0f} "
          f"of {urban_km:.0f} km of their track is on a line drawn", flush=True)
    cities = {}
    for city, row in metro_rows:
        c = cities.setdefault(city, {"n": city, "km": 0, "bbox": list(row["bbox"]), "lines": []})
        c["km"] += row["km"]
        c["bbox"] = [min(c["bbox"][0], row["bbox"][0]), min(c["bbox"][1], row["bbox"][1]), max(c["bbox"][2], row["bbox"][2]), max(c["bbox"][3], row["bbox"][3])]
        c["lines"].append(row)
    known = city_names(cfg.code)
    for c in cities.values():
        c["lines"].sort(key=lambda r: r["n"])
        name_city(c, known, cfg.code)

    # ---------------------------------------------------------------- lines being built
    build_feats = (cfg.construction_of(cfg, ways, namer) if cfg.construction_of else
                   being_built(ways, cfg.code, cfg.plain_name, cfg.build_name, cfg.build_fast, namer))

    # ---------------------------------------------------------------- stations
    seen, stations = set(), []
    station_sources = ex["stations"]
    if cfg.urban_policy:
        from station_provenance import filter_station_sources
        station_sources = filter_station_sources(cfg.code, ex, extract_path)
    for t, lon, lat in station_sources:
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
            # a tram or light-rail stop (t), as China's and Japan's data mark them: the page can show
            # these later than metro stations ("感觉站点太密了", 2026-10-18, Turin's trams at z13)
            kinds = set(re.split(r"[;,]", kind)) - {""}
            if not ({"subway"} & kinds or t.get("subway") == "yes") and (
                    t.get("railway") == "tram_stop" or kinds & {"tram", "light_rail"}):
                props["t"] = 1
        namer.station(props, t, (lon, lat))
        stations.append({"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}})
    # only the stations a drawn line passes: one on a line that is not drawn is a dot in the middle of nothing
    every = len(stations)
    lines_of = lambda feats: [co for f in feats for co in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]])]
    stations = with_a_line(stations, lines_of(rail_feats), lines_of(metro_feats))
    if cfg.urban_station_display:
        stations = cfg.urban_station_display(stations, metro_feats, ex)
    print(f"{cfg.code} stations: {len(stations)} of {every} have a drawn line passing them; the other {every - len(stations)} are not drawn", flush=True)

    # ---------------------------------------------------------------- write
    def write(name, obj):
        p = OUT / name
        atomic_json(p, obj)
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
    if cfg.rail_capsules:                       # from the rail, metro and station files just written
        from station_capsules import rail_display
        rail_display(cfg.code, OUT.parent)
    write(f"{cfg.code}_lines.json", sorted(lines_json, key=lambda r: -r["tk"]))
    write(f"{cfg.code}_metro_cities.json", sorted(cities.values(), key=lambda c: -c["km"]))
    write(f"{cfg.code}_facts.json", {"km": round(sum(by_kind.values())), "fast_km": round(sum(by_kind[k] for k in cfg.fast_kinds)), "bands": sorted({f["properties"]["c"] for f in rail_feats if "d" in f["properties"]})})
    print(f"{cfg.code} rail km drawn by kind:", {k: round(v) for k, v in by_kind.most_common()},
          "| with a line colour:", round(sum(feat_km(f) for f in rail_feats if "lc" in f["properties"])), flush=True)
    print(f"{cfg.code}: {len(lines_json)} railway lines, {sum(by_kind.values()):.0f} km drawn; {len(metro_rows)} metro and tram lines in {len(cities)} cities, "
          f"{sum(r['km'] for _, r in metro_rows)} km; {len(build_feats)} lines being built; {len(stations)} stations")
    write_yards(ex, cfg.code)
