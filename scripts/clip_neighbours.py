"""Take out of a country's drawn layers what lies in the land of a neighbour that is drawn too.

China's OSM extract reaches over its borders. Once Laos was drawn, 14.6 km of 磨万铁路, 11 km
of station tracks and the station 磨丁 lay inside Laos, under Laos's own line, and 磨丁 came up
twice in the search (2026-10-19, "加新国家前，先查已有国家的数据有没有画进它的国土"). The
neighbour's land is its own boundary from its extract (scripts/process_sea.py reads it the same
way), so both countries end at the same line.

    python3 scripts/clip_neighbours.py cn

China: after process_osm.py and build_graph.py (the route network keeps its stations; only what
the map draws and lists is clipped), before station_capsules.py and build_tiles.py. Running it
again changes nothing.

Germany, Switzerland and Italy, once Austria was drawn (2026-10-21): their extracts reach over
the border and drew Austrian lines (Italy's Gailtalbahn and Rudolfsbahn, Switzerland's
Vorarlbergbahn and the stations of Lustenau, Germany's Außerfernbahn), 55 km in all, under
Austria's own. scripts/process_europe.py runs this after each of them; a row of the line list
whose line has nothing left drawn is taken out too (Italy listed the Gailtalbahn).
"""
import json
import pickle
import sys
from pathlib import Path

from shapely.geometry import LineString, mapping, shape
from shapely.prepared import prep

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# the neighbours of a country that are on the map, and the files of its drawn layers
NEIGHBOURS = {"cn": ["la"], "de": ["at"], "ch": ["at"], "it": ["at"]}
SLIVER_M = 100       # a line left shorter than this at the border lies under the neighbour's line
FILES = {"cn": ["rail_hsr.geojson", "rail_conv.geojson", "rail_shared.geojson", "rail_build.geojson",
                "yards.geojson", "depots.geojson", "stations.geojson", "metro.geojson", "metro_stations.geojson"],
         **{g: [f"{g}_{k}.geojson" for k in ("rail", "build", "metro", "stations", "yards", "depots")] for g in ("de", "ch", "it")}}
LINES = {g: (f"{g}_lines.json", [f"{g}_rail.geojson", f"{g}_build.geojson"]) for g in ("de", "ch", "it")}


def land_of(code):
    """A drawn neighbour's land, from the boundary its extract carries."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from process_sea import land_of as area
    path = DATA / "raw" / f"extract_{code}.pkl"
    if not path.exists():
        sys.exit(f"no {path.name}: the land of {code} is needed to clip its neighbours (run extract_osm.py {code})")
    with path.open("rb") as stream:            # (the pipeline's own extract, written by extract_osm.py here)
        territory = pickle.load(stream).get("territory")
    if not territory:
        sys.exit(f"{path.name} has no territory")
    return area(territory)


def rounded(geometry, places=7):
    def walk(value):
        if isinstance(value, (list, tuple)):
            if value and isinstance(value[0], (int, float)):
                return [round(v, places) for v in value]
            return [walk(v) for v in value]
        return value
    out = mapping(geometry)
    return {"type": out["type"], "coordinates": walk(out["coordinates"])}


def clip(features, land):
    """The features with what lies in the land taken out, line by line: a line's parts that stay
    out of the land are kept as they are (the overlay of a whole multi-line re-nodes every part of
    it, across the country), the parts that cross the border are cut there, and a piece left shorter
    than SLIVER_M is dropped. Points inside are dropped; a feature with nothing left is dropped."""
    inside = prep(land)
    kept, cut, dropped = [], 0, []
    for f in features:
        g = shape(f["geometry"])
        if not inside.intersects(g):
            kept.append(f)
            continue
        kind = f["geometry"]["type"]
        if kind in ("Point", "MultiPoint"):
            dropped.append(f["properties"].get("n"))
            continue
        parts = f["geometry"]["coordinates"] if kind == "MultiLineString" else [f["geometry"]["coordinates"]]
        out, changed = [], False
        for part in parts:
            line = LineString(part)
            if not inside.intersects(line) or line.intersection(land).length * 111320 < 1:
                out.append(part)                 # (a coordinate rounded onto the border: running again changes nothing)
                continue
            changed = True
            rest = line.difference(land)
            pieces = [rest] if rest.geom_type == "LineString" else [q for q in getattr(rest, "geoms", []) if q.geom_type == "LineString"]
            out += [rounded(q)["coordinates"] for q in pieces if q.length * 111320 >= SLIVER_M]
        if not changed:
            kept.append(f)
            continue
        if not out:
            dropped.append(f["properties"].get("n"))
            continue
        geometry = {"type": "MultiLineString", "coordinates": out} if kind == "MultiLineString" or len(out) > 1 \
            else {"type": "LineString", "coordinates": out[0]}
        kept.append({**f, "geometry": geometry})
        cut += 1
    return kept, cut, dropped


def main(code):
    land = None
    for neighbour in NEIGHBOURS.get(code, []):
        area = land_of(neighbour)
        land = area if land is None else land.union(area)
    if land is None:
        return
    for name in FILES[code]:
        path = DATA / name
        if not path.exists():
            continue
        text = path.read_text()
        data = json.loads(text)
        features, cut, dropped = clip(data["features"], land)
        if not cut and not dropped:
            continue
        data["features"] = features
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ("\n" if text.endswith("\n") else ""))
        print(f"{name}: {cut} cut at the border, {len(dropped)} dropped {dropped[:5]}")
    if code in LINES:
        # a station whose only drawn line lay over the border is a dot in the middle of nothing:
        # Switzerland's Widnau Habsburg and Kriessern stood on the Rhine dike railway, drawn on the
        # Austrian bank (the same test as the pipeline's, process_jp.with_a_line)
        from process_jp import with_a_line
        drawn = lambda layer: [co for f in json.loads((DATA / f"{code}_{layer}.geojson").read_text())["features"]
                               for co in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]])]
        path = DATA / f"{code}_stations.geojson"
        text = path.read_text()
        data = json.loads(text)
        served = {id(f) for f in with_a_line(data["features"], drawn("rail") + drawn("build"), drawn("metro"))}
        alone = [f for f in data["features"] if id(f) not in served and land.distance(shape(f["geometry"])) * 111320 < 2000]
        if alone:
            data["features"] = [f for f in data["features"] if id(f) in served or f not in alone]
            path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ("\n" if text.endswith("\n") else ""))
            print(f"{path.name}: {len(alone)} stations near the border left with no drawn line taken out {[f['properties'].get('n') for f in alone]}")
        listed, layers = LINES[code]
        path = DATA / listed
        drawn = {f["properties"].get("n") for name in layers if (DATA / name).exists()
                 for f in json.loads((DATA / name).read_text())["features"]}
        text = path.read_text()
        rows = json.loads(text)
        kept = [row for row in rows if row.get("n") in drawn]
        if len(kept) != len(rows):
            path.write_text(json.dumps(kept, ensure_ascii=False, separators=(",", ":")) + ("\n" if text.endswith("\n") else ""))
            print(f"{listed}: {len(rows) - len(kept)} lines with nothing left drawn taken out {sorted({r['n'] for r in rows} - {r['n'] for r in kept})[:8]}")
        # the card's railway length, summed as scripts/country.py sums it, of what is left
        from country import km
        facts_path, rail = DATA / f"{code}_facts.json", json.loads((DATA / f"{code}_rail.geojson").read_text())["features"]
        by_kind = {}
        for f in rail:
            parts = f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]]
            by_kind[f["properties"]["jk"]] = by_kind.get(f["properties"]["jk"], 0) + sum(km(co) for co in parts)
        facts = json.loads(facts_path.read_text())
        totals = {"km": round(sum(by_kind.values())), "fast_km": round(by_kind.get("hs", 0))}
        if {k: facts[k] for k in totals} != totals:
            print(f"{facts_path.name}: {({k: facts[k] for k in totals})} -> {totals}")
            facts_path.write_text(json.dumps({**facts, **totals}, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "cn")
