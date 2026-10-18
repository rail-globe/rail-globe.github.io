"""Stage 1: pull railway and metro objects out of OSM country extracts into data/raw/extract*.pkl.

    python3 scripts/extract_osm.py        China, Hong Kong, Macao, Taiwan -> extract.pkl (with trams
                                          and tram stops)
    python3 scripts/extract_osm.py uk     United Kingdom                  -> extract_uk.pkl (with trams,
                                          heritage and narrow-gauge lines, tram stops and halts)
    python3 scripts/extract_osm.py jp     Japan                           -> extract_jp.pkl (with trams
                                          and tram stops)
    python3 scripts/extract_osm.py kr     South Korea                     -> extract_kr.pkl
    python3 scripts/extract_osm.py de     Germany                         -> extract_de.pkl
    python3 scripts/extract_osm.py fr     France                          -> extract_fr.pkl
    python3 scripts/extract_osm.py ch     Switzerland                     -> extract_ch.pkl
    python3 scripts/extract_osm.py es     Spain                           -> extract_es.pkl

Reading a 1.6-2.3 GB extract takes a few minutes, so it is done once here;
scripts/process_osm.py then classifies and writes the map layers from the pickles in seconds.

Kept: railway=rail|construction ways including yard and siding tracks, with their tunnel/bridge
and electrification tags; railway=subway|light_rail|monorail|maglev ways everywhere;
railway=station nodes/ways; named yards, depots and railway land (for depot labels);
train / metro route and route_master relations (line colours, operators), and route=railway
relations (which named line a track belongs to, including track it shares with another line).

The names of depots are on many kinds of object (scripts/depots.py), so the named ground and
yard objects are kept too, ways and multipolygon relations alike, each with its outline ("named"
in the pickle). To read only these again into a pickle that is there:

    python3 scripts/extract_osm.py [uk|jp|kr] places
"""
import os
import json
import pickle
import sys
import time
from pathlib import Path

import osmium

from depots import AREA_USES, YARD_KINDS, form_of, name_of, worth_keeping

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
WAY_TAGS = ("railway", "service", "usage", "highspeed", "maxspeed", "maxspeed:design", "design_speed",
            "construction", "construction:railway", "name", "name:zh", "name:en", "network", "operator", "colour",
            "tunnel", "bridge", "electrified", "voltage", "frequency", "gauge", "tracks", "railway:preserved")
REL_TAGS = ("type", "route", "route_master", "name", "name:zh", "name:en", "ref", "colour", "network", "operator",
            "usage", "service", "tourism", "heritage", "railway:preserved", "description", "opening_hours",
            "website", "wikipedia", "disused", "end_date")
NAME_TAGS = ("name", "name:zh", "name:en")
METRO_RAIL = {"subway", "light_rail", "monorail", "maglev"}
# Ordinary train services stop at railway stations; their stops let a station that two parallel
# railway lines both call at show a capsule (scripts/station_capsules.py, 2026-10-18). Every
# consumer of "stops" looks routes up by relation id, so metro and tram results do not change.
STOP_ROUTES = {"train"}
YARD_KINDS = {"yard", "depot", "workshop", "engine_shed", "roundhouse"}


def station_tags(tags, obj, keys=NAME_TAGS):
    """Keep native object identity inside the existing station tuple contract.

    It is provenance, not an OSM tag or a display coordinate. Older extracts
    without these fields require a hash-bound native-source recovery scan.
    """
    return {**{key: tags.get(key) for key in keys if tags.get(key)},
            "_osm_type": "w" if obj.is_way() else "n", "_osm_id": obj.id}


def centre(way):
    pts = [(n.lon, n.lat) for n in way.nodes if n.location.valid()]
    if not pts:
        return None
    xs, ys = zip(*pts)
    return sum(xs) / len(xs), sum(ys) / len(ys)


RING_POINTS = 400     # an outline is kept with at most so many points: enough to tell what it holds


def named_ground(path, g):
    """The named things of one extract that can carry a depot's name: ground (landuse=railway,
    industrial, depot, construction, commercial, garages) and yard objects (railway=yard, depot,
    workshop, ...), as nodes, ways and multipolygon relations. Each is {"form", "osm", "name",
    "key": the tag the name is read from, "at": its middle, "ring": its outline as coordinate
    lists, or None for a node, and "en": its name:en where that is not the name already}. Ground
    that is not railway ground is kept only with a depot word
    in its name (depots.worth_keeping): there are tens of thousands of named factories.
    No index of every node is built: the nodes of the outlines are fetched by their numbers."""
    forms = [("landuse", v) for v in AREA_USES] + [("railway", k) for k in YARD_KINDS]
    if g in ("de", "fr", "ch", "es", "nl", "be", "it"):
        # Swiss tram depots, among others, put their names on the depot building.
        # Still keep only a depot name; its actual outline must hold yard track.
        forms += [("building", k) for k in ("industrial", "transportation", "train_station", "service", "yes")]
    def named_form(tags):
        return form_of(tags) or ("building=" + tags["building"] if g in ("de", "fr", "ch", "es", "nl", "be", "it") and tags.get("building") else None)
    tags_of = lambda o: {t.k: t.v for t in o.tags}

    def thinned(refs):
        return refs if len(refs) <= RING_POINTS else refs[::len(refs) // RING_POINTS + 1] + refs[-1:]
    found = []                        # [form, osm, name, key, [node numbers of each ring], English name]
    english = lambda t, name: t.get("name:en") if t.get("name:en") and t.get("name:en") != name else None
    members = {}                      # way of a multipolygon -> its node numbers
    for o in osmium.FileProcessor(path, osmium.osm.RELATION).with_filter(osmium.filter.TagFilter(*forms)):
        t = tags_of(o)
        form = named_form(t)
        name, key = name_of(t, form, g) if form else ("", "")
        if t.get("type") == "multipolygon" and worth_keeping(g, name, form, key):
            ways = [m.ref for m in o.members if m.type == "w" and m.role in ("outer", "")]
            members.update(dict.fromkeys(ways))
            found.append([form, f"r{o.id}", name, key, ways, english(t, name)])
    for o in osmium.FileProcessor(path, osmium.osm.WAY).with_filter(osmium.filter.TagFilter(*forms)):
        t = tags_of(o)
        form = named_form(t)
        name, key = name_of(t, form, g) if form else ("", "")
        if worth_keeping(g, name, form, key):
            found.append([form, f"w{o.id}", name, key, [thinned([n.ref for n in o.nodes])], english(t, name)])
    if members:
        for o in osmium.FileProcessor(path, osmium.osm.WAY).with_filter(osmium.filter.IdFilter(members)):
            members[o.id] = thinned([n.ref for n in o.nodes])
    for row in found:
        if row[1][0] == "r":
            row[4] = [members[w] for w in row[4] if members.get(w)]
    place = dict.fromkeys(ref for row in found for ring in row[4] for ref in ring)
    if place:
        for o in osmium.FileProcessor(path, osmium.osm.NODE).with_filter(osmium.filter.IdFilter(place)):
            place[o.id] = (round(o.location.lon, 6), round(o.location.lat, 6))
    out = []
    for form, osm, name, key, rings, en in found:
        rings = [[place[ref] for ref in ring if place.get(ref)] for ring in rings]
        rings = [ring for ring in rings if len(ring) > 1]
        points = [pt for ring in rings for pt in ring]
        if points:
            at = (sum(x for x, _ in points) / len(points), sum(y for _, y in points) / len(points))
            out.append({"form": form, "osm": osm, "name": name, "key": key, "at": at, "ring": rings, "en": en})
    for o in osmium.FileProcessor(path, osmium.osm.NODE).with_filter(osmium.filter.TagFilter(*forms[len(AREA_USES):])):
        t = tags_of(o)
        form = form_of(t)
        name, key = name_of(t, form, g) if form else ("", "")
        if worth_keeping(g, name, form, key):
            out.append({"form": form, "osm": f"n{o.id}", "name": name, "key": key, "at": (o.location.lon, o.location.lat), "ring": None,
                        "en": english(t, name)})
    return out


STOP_TAGS = ("name", "name:zh", "railway", "public_transport", "station", "construction", "proposed", "disused", "abandoned",
             "disused:railway", "abandoned:railway", "not:public_transport")


def route_stops(path, kinds):
    """Where the metro, tram and train routes of an extract stop: the stop and platform members of each
    route relation, with their roles, names and places. Returns {"routes": {relation: [(member
    type, id, role)]}, "nodes": {id: (tags, lon, lat)}, "platforms": {way: (tags, lon, lat) of its
    middle}, "areas": {node: the name of the stop_area it is in}}. A route's stops are the stations
    of its line: scripts/process_osm.py links a station to the lines that stop there, not to every
    line that passes within a few hundred metres of it."""
    tags_of = lambda o, keys: {t.k: t.v for t in o.tags if t.k in keys}
    routes, areas = {}, {}
    for o in osmium.FileProcessor(path, osmium.osm.RELATION).with_filter(osmium.filter.TagFilter(("type", "route"), ("public_transport", "stop_area"))):
        t = {x.k: x.v for x in o.tags}
        if t.get("type") == "route" and t.get("route") in kinds:
            routes[o.id] = [(m.type, m.ref, m.role) for m in o.members if m.type == "n" or (m.type == "w" and "platform" in m.role)]
        elif t.get("public_transport") == "stop_area" and (t.get("name:zh") or t.get("name")):
            for m in o.members:
                if m.type == "n":
                    areas.setdefault(m.ref, t.get("name:zh") or t.get("name"))
    want = {ref for members in routes.values() for kind, ref, _ in members if kind == "n"}
    platform_ways = {ref for members in routes.values() for kind, ref, _ in members if kind == "w"}
    nodes, way_nodes, platforms = {}, {}, {}
    if platform_ways:
        for o in osmium.FileProcessor(path, osmium.osm.WAY).with_filter(osmium.filter.IdFilter(platform_ways)):
            way_nodes[o.id] = (tags_of(o, STOP_TAGS), [n.ref for n in o.nodes])
    every = want | {n for _, refs in way_nodes.values() for n in refs}
    if every:
        for o in osmium.FileProcessor(path, osmium.osm.NODE).with_filter(osmium.filter.IdFilter(every)):
            nodes[o.id] = (tags_of(o, STOP_TAGS), round(o.location.lon, 7), round(o.location.lat, 7))
    for wid, (t, refs) in way_nodes.items():
        pts = [nodes[n][1:] for n in refs if n in nodes]
        if pts:
            platforms[wid] = (t, round(sum(x for x, _ in pts) / len(pts), 7), round(sum(y for _, y in pts) / len(pts), 7))
    return {"routes": routes, "nodes": {n: nodes[n] for n in want if n in nodes}, "platforms": platforms,
            "areas": {n: name for n, name in areas.items() if n in want}}


def stops_again(files, out, kinds):
    """Reads only where the metro, tram and train routes stop, into a pickle that is there."""
    cache = pickle.load(open(RAW / out, "rb"))        # written here, by main() below
    t0 = time.time()
    found = {"routes": {}, "nodes": {}, "platforms": {}, "areas": {}}
    for pbf in files:
        part = route_stops(str(RAW / pbf), kinds)
        for key in found:
            found[key].update(part[key])
    cache["stops"] = found
    print(f"{out}: {len(found['routes'])} routes, {len(found['nodes'])} stop nodes, {len(found['platforms'])} platform ways, {time.time() - t0:.0f}s", flush=True)
    tmp = RAW / (out + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(cache, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, RAW / out)
    print("wrote", RAW / out)


def places_again(files, out, g):
    """Reads only the named ground and yard objects again, into a pickle that is there."""
    cache = pickle.load(open(RAW / out, "rb"))        # written here, by main() below
    t0 = time.time()
    cache["named"] = [o for pbf in files for o in named_ground(str(RAW / pbf), g)]
    print(f"{out}: {len(cache['named'])} named ground and yard objects, {time.time() - t0:.0f}s", flush=True)
    tmp = RAW / (out + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(cache, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, RAW / out)
    print("wrote", RAW / out)


def main(files, out, more=(), stops=(), g="cn"):
    """more: further kinds of track and of route to keep for this country (tram, preserved, ...);
    stops: further kinds of stopping place kept as stations (tram_stop, halt), marked with their kind;
    g: the country, for the words that name a depot in its language."""
    missing = [str(RAW / pbf) for pbf in files if not (RAW / pbf).exists()]
    if missing:          # never write a partial cache over a good one
        sys.exit("missing input, nothing written: " + ", ".join(missing))
    ways, stations, relations, places, sources, named = [], [], [], [], [], []
    route_stopping = {"routes": {}, "nodes": {}, "platforms": {}, "areas": {}}     # where the metro and tram routes stop
    for pbf in files:
        path = RAW / pbf
        with osmium.io.Reader(str(path)) as reader:
            header = reader.header()
            sources.append({"file": pbf, "bytes": path.stat().st_size,
                            "timestamp": header.get("osmosis_replication_timestamp"),
                            "sequence": header.get("osmosis_replication_sequence_number"),
                            "replication_url": header.get("osmosis_replication_base_url")})
        receipt = path.with_name(path.name + ".source.json")
        if receipt.exists():
            import hashlib
            provenance = json.loads(receipt.read_text())
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if provenance.get("bytes") != path.stat().st_size or provenance.get("sha256") != digest:
                sys.exit(f"source receipt does not match {pbf}, nothing written")
            sources[-1].update({key: provenance[key] for key in ("url", "sha256", "etag", "last_modified")
                               if key in provenance})
        t0 = time.time()
        fp = osmium.FileProcessor(str(path)).with_locations("sparse_mem_array").with_filter(osmium.filter.KeyFilter("railway"))
        for o in fp:
            t = o.tags
            r = t.get("railway")
            if o.is_way():
                if r in stops:
                    c = centre(o)
                    if c and t.get("name"):
                        stations.append(({**station_tags(t, o), "railway": r}, *c))
                    continue
                if r == "station" or r in YARD_KINDS:
                    c = centre(o)
                    if c and r == "station":
                        stations.append((station_tags(t, o, NAME_TAGS + ("station", "subway", "light_rail")), *c))
                    elif c and t.get("name"):
                        places.append((r, {k: t.get(k) for k in NAME_TAGS if t.get(k)}, *c))
                    continue
                if r not in ("rail", "construction") and r not in METRO_RAIL and r not in more:
                    continue
                coords = [(round(n.lon, 6), round(n.lat, 6)) for n in o.nodes if n.location.valid()]
                if len(coords) < 2:
                    continue
                ways.append((o.id, {k: t.get(k) for k in WAY_TAGS if t.get(k) is not None}, coords))
            elif o.is_node():
                if r == "station":
                    stations.append((station_tags(t, o, NAME_TAGS + ("station", "subway", "light_rail")),
                                     o.location.lon, o.location.lat))
                elif r in stops and t.get("name"):
                    stations.append(({**station_tags(t, o), "railway": r}, o.location.lon, o.location.lat))
                elif r in YARD_KINDS and t.get("name"):
                    places.append((r, {k: t.get(k) for k in NAME_TAGS if t.get(k)}, o.location.lon, o.location.lat))
        print(f"{pbf}: {len(ways)} ways, {len(stations)} stations, {time.time() - t0:.0f}s", flush=True)

        # Depots are usually mapped as named railway land rather than as a railway=* object.
        t0 = time.time()
        fp = osmium.FileProcessor(str(path)).with_locations("sparse_mem_array").with_filter(osmium.filter.TagFilter(("landuse", "railway")))
        for o in fp:
            if o.is_way() and o.tags.get("name"):
                c = centre(o)
                if c:
                    places.append(("land", {k: o.tags.get(k) for k in NAME_TAGS if o.tags.get(k)}, *c))
        print(f"{pbf}: {len(places)} named yards / depots / railway land, {time.time() - t0:.0f}s", flush=True)

        t0 = time.time()
        for o in osmium.FileProcessor(str(path), osmium.osm.RELATION):
            t = o.tags
            kind = t.get("route") if t.get("type") == "route" else t.get("route_master") if t.get("type") == "route_master" else None
            if kind in METRO_RAIL or kind in ("train", "railway") or kind in more:
                relations.append((o.id, {k: t.get(k) for k in REL_TAGS if t.get(k) is not None},
                                  [(m.type, m.ref) for m in o.members]))
        print(f"{pbf}: {len(relations)} route relations, {time.time() - t0:.0f}s", flush=True)

        t0 = time.time()
        named += named_ground(str(path), g)
        print(f"{pbf}: {len(named)} named ground and yard objects, {time.time() - t0:.0f}s", flush=True)

        t0 = time.time()
        part = route_stops(str(path), METRO_RAIL | STOP_ROUTES | set(more))
        for key in route_stopping:
            route_stopping[key].update(part[key])
        print(f"{pbf}: stops of {len(route_stopping['routes'])} metro, tram and train routes, {time.time() - t0:.0f}s", flush=True)

    if not ways or not stations:
        sys.exit("nothing extracted, the cache is left as it was")
    tmp = RAW / (out + ".tmp")            # written beside the cache and swapped in only when complete
    with open(tmp, "wb") as f:
        pickle.dump({"ways": ways, "stations": stations, "relations": relations, "places": places, "sources": sources, "named": named,
                     "stops": route_stopping, "relation_tag_schema": REL_TAGS},
                    f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, RAW / out)
    (RAW / (out + ".sources.json")).write_text(json.dumps(sources, ensure_ascii=False, indent=2))
    print("wrote", RAW / out)


COUNTRIES = {
    "uk": dict(files=["united-kingdom.osm.pbf"], out="extract_uk.pkl", more=("tram", "narrow_gauge", "preserved"), stops=("tram_stop", "halt")),
    "jp": dict(files=["japan-latest.osm.pbf"], out="extract_jp.pkl", more=("tram",), stops=("tram_stop",)),      # the street tramways (都電荒川線, 広島電鉄, ...)
    "kr": dict(files=["south-korea-latest.osm.pbf"], out="extract_kr.pkl", more=("tram",), stops=("tram_stop", "halt")),
    "de": dict(files=["germany-latest.osm.pbf"], out="extract_de.pkl", more=("tram", "narrow_gauge", "preserved"), stops=("tram_stop", "halt")),
    "fr": dict(files=["france-latest.osm.pbf"], out="extract_fr.pkl", more=("tram", "narrow_gauge", "preserved"), stops=("tram_stop", "halt")),
    "ch": dict(files=["switzerland-latest.osm.pbf"], out="extract_ch.pkl", more=("tram", "narrow_gauge", "preserved"), stops=("tram_stop", "halt")),
    "es": dict(files=["spain-latest.osm.pbf", "canarias-latest.osm.pbf", "ceuta-latest.osm.pbf", "melilla-latest.osm.pbf"],
               out="extract_es.pkl", more=("tram", "narrow_gauge", "preserved"), stops=("tram_stop", "halt")),
    "nl": dict(files=["netherlands-latest.osm.pbf"], out="extract_nl.pkl", more=("tram", "narrow_gauge", "preserved"), stops=("tram_stop", "halt")),
    "be": dict(files=["belgium-latest.osm.pbf"], out="extract_be.pkl", more=("tram", "narrow_gauge", "preserved"), stops=("tram_stop", "halt")),
    "it": dict(files=["italy-latest.osm.pbf"], out="extract_it.pkl", more=("tram", "narrow_gauge", "preserved"), stops=("tram_stop", "halt")),
    # Trams are light rail here (Shenyang, Suzhou, Dalian, Wuhan, Hong Kong's 電車), so their track,
    # routes and stops are taken too. Halts are not: in China a halt is a stop on the railway,
    # and the railway stations would change with it.
    "cn": dict(files=["china.osm.pbf", "taiwan.osm.pbf"], out="extract.pkl", more=("tram",), stops=("tram_stop",)),
}

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a not in ("places", "stops")]
    g = args[0] if args else "cn"
    if g not in COUNTRIES or len(args) > 1:
        sys.exit("usage: python3 scripts/extract_osm.py [uk|jp|kr|de|fr|ch|es|nl|be|it] [places] [stops]")
    if "places" in sys.argv[1:]:
        places_again(COUNTRIES[g]["files"], COUNTRIES[g]["out"], g)
    if "stops" in sys.argv[1:]:
        stops_again(COUNTRIES[g]["files"], COUNTRIES[g]["out"], METRO_RAIL | STOP_ROUTES | set(COUNTRIES[g].get("more", ())))
    if not {"places", "stops"} & set(sys.argv[1:]):
        main(g=g, **COUNTRIES[g])
