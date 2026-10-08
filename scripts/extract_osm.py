"""Stage 1: pull railway and metro objects out of the Geofabrik extracts into data/raw/extract*.pkl.

    python3 scripts/extract_osm.py        China, Hong Kong, Macao, Taiwan -> extract.pkl
    python3 scripts/extract_osm.py uk     United Kingdom                  -> extract_uk.pkl
    python3 scripts/extract_osm.py jp     Japan                           -> extract_jp.pkl

Reading a 1.6-2.3 GB extract takes a few minutes, so it is done once here;
scripts/process_osm.py then classifies and writes the map layers from the pickles in seconds.

Kept: railway=rail|construction ways including yard and siding tracks, with their tunnel/bridge
and electrification tags; railway=subway|light_rail|monorail|maglev ways everywhere;
railway=station nodes/ways; named yards, depots and railway land (for depot labels);
train / metro route and route_master relations (line colours, operators), and route=railway
relations (which named line a track belongs to, including track it shares with another line).
"""
import os
import json
import pickle
import sys
import time
from pathlib import Path

import osmium

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
WAY_TAGS = ("railway", "service", "usage", "highspeed", "maxspeed", "maxspeed:design", "design_speed",
            "construction", "construction:railway", "name", "name:zh", "name:en", "network", "operator", "colour",
            "tunnel", "bridge", "electrified", "voltage", "frequency", "gauge", "tracks")
REL_TAGS = ("type", "route", "route_master", "name", "name:zh", "name:en", "ref", "colour", "network", "operator")
NAME_TAGS = ("name", "name:zh", "name:en")
METRO_RAIL = {"subway", "light_rail", "monorail", "maglev"}
YARD_KINDS = {"yard", "depot", "workshop", "engine_shed", "roundhouse"}


def centre(way):
    pts = [(n.lon, n.lat) for n in way.nodes if n.location.valid()]
    if not pts:
        return None
    xs, ys = zip(*pts)
    return sum(xs) / len(xs), sum(ys) / len(ys)


def main(files, out):
    missing = [str(RAW / pbf) for pbf in files if not (RAW / pbf).exists()]
    if missing:          # never write a partial cache over a good one
        sys.exit("missing input, nothing written: " + ", ".join(missing))
    ways, stations, relations, places, sources = [], [], [], [], []
    for pbf in files:
        path = RAW / pbf
        with osmium.io.Reader(str(path)) as reader:
            header = reader.header()
            sources.append({"file": pbf, "bytes": path.stat().st_size,
                            "timestamp": header.get("osmosis_replication_timestamp"),
                            "sequence": header.get("osmosis_replication_sequence_number"),
                            "replication_url": header.get("osmosis_replication_base_url")})
        t0 = time.time()
        fp = osmium.FileProcessor(str(path)).with_locations("sparse_mem_array").with_filter(osmium.filter.KeyFilter("railway"))
        for o in fp:
            t = o.tags
            r = t.get("railway")
            if o.is_way():
                if r == "station" or r in YARD_KINDS:
                    c = centre(o)
                    if c and r == "station":
                        stations.append(({k: t.get(k) for k in NAME_TAGS + ("station", "subway", "light_rail") if t.get(k)}, *c))
                    elif c and t.get("name"):
                        places.append((r, {k: t.get(k) for k in NAME_TAGS if t.get(k)}, *c))
                    continue
                if r not in ("rail", "construction") and r not in METRO_RAIL:
                    continue
                coords = [(round(n.lon, 6), round(n.lat, 6)) for n in o.nodes if n.location.valid()]
                if len(coords) < 2:
                    continue
                ways.append((o.id, {k: t.get(k) for k in WAY_TAGS if t.get(k) is not None}, coords))
            elif o.is_node():
                if r == "station":
                    stations.append(({k: t.get(k) for k in NAME_TAGS + ("station", "subway", "light_rail") if t.get(k)},
                                     o.location.lon, o.location.lat))
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
            if kind in METRO_RAIL or kind in ("train", "railway"):
                relations.append((o.id, {k: t.get(k) for k in REL_TAGS if t.get(k) is not None},
                                  [(m.type, m.ref) for m in o.members]))
        print(f"{pbf}: {len(relations)} route relations, {time.time() - t0:.0f}s", flush=True)

    if not ways or not stations:
        sys.exit("nothing extracted, the cache is left as it was")
    tmp = RAW / (out + ".tmp")            # written beside the cache and swapped in only when complete
    with open(tmp, "wb") as f:
        pickle.dump({"ways": ways, "stations": stations, "relations": relations, "places": places, "sources": sources},
                    f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, RAW / out)
    (RAW / (out + ".sources.json")).write_text(json.dumps(sources, ensure_ascii=False, indent=2))
    print("wrote", RAW / out)


if __name__ == "__main__":
    if sys.argv[1:] == ["uk"]:
        main(["united-kingdom.osm.pbf"], "extract_uk.pkl")
    elif sys.argv[1:] == ["jp"]:
        main(["japan-latest.osm.pbf"], "extract_jp.pkl")
    else:
        main(["china.osm.pbf", "taiwan.osm.pbf"], "extract.pkl")
