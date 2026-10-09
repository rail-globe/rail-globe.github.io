"""Yards and depots of a country abroad, as the Chinese map draws them (scripts/process_osm.py):
station, yard and depot track under everything else, and the named yards and depots beside it.

    python3 scripts/yards.py jp           -> data/jp_yards.geojson, data/jp_depots.geojson
    python3 scripts/yards.py uk           -> data/uk_yards.geojson, data/uk_depots.geojson
    python3 scripts/yards.py kr           -> data/kr_yards.geojson, data/kr_depots.geojson

The scripts of the countries (process_jp.py, and scripts/country.py for the others) call this at their end, so a full run of either
writes these too; run on its own it takes seconds.
"""
import json
import pickle
import re
import sys
from pathlib import Path

from shapely import STRtree
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data"
YARD_SERVICE = {"yard", "siding", "crossover"}      # station and depot tracks; industrial spurs are left out
TRACK = {"rail", "subway", "light_rail", "tram", "monorail", "narrow_gauge"}
CHUNK = 400                 # a few large MultiLineStrings tile and render faster than one huge feature
# Railway land is named for all sorts of things: only what names a yard, a depot or a works counts.
DEPOT_NAME = {
    "jp": re.compile(r"車両基地|車両センター|総合車両|車両所|車両区|運転所|運転区|運輸区|機関区|電車区|気動車区|検車区|検修|車庫|工場|操車場|貨物ターミナル|貨物駅|電留線|留置線"),
    "kr": re.compile(r"차량기지|차량사업소|차량정비|정비단|정비창|기지$|조차장|기관차|검수|화물|컨테이너|주박"),
    "uk": re.compile(r"Depot|Sidings?\b|Yard\b|Works\b|TMD|Traincare|Train Care|Maintenance|Carriage|Stabling|Freight ?liner|Terminal\b", re.I),
}


def yard_lines(ways, tol=0.00004):
    """Yard track joined up and simplified: coordinate lists, and the runs of track they come from."""
    lines = [co for _, t, co in ways if t.get("service") in YARD_SERVICE and t.get("railway") in TRACK and len(co) > 1]
    if not lines:
        return [], []
    merged = linemerge(MultiLineString(lines))
    parts = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
    out = []
    for g in parts:
        co = [[round(x, 5), round(y, 5)] for x, y in g.simplify(tol, preserve_topology=False).coords]
        co = [p for i, p in enumerate(co) if not i or p != co[i - 1]]
        if len(co) > 1:
            out.append(co)
    return out, parts


def depot_points(places, parts, named, g):
    """The named yards and depots that lie by yard track, one point each."""
    tree = STRtree(parts) if parts else None
    depots, seen = [], set()
    for kind, t, lon, lat in places:
        name = re.sub(r"\s+", " ", t.get("name") or "").strip()
        if not name or (kind == "land" and not named.search(name)):
            continue
        k = (name, round(lon, 2), round(lat, 2))
        if k in seen or tree is None or not len(tree.query(Point(lon, lat), predicate="dwithin", distance=0.01)):
            continue
        seen.add(k)
        depots.append({"type": "Feature", "properties": {"n": name, "g": g}, "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}})
    return depots


def write_yards(ex, g):
    simp, parts = yard_lines(ex["ways"])
    yards = [{"type": "Feature", "properties": {"g": g}, "geometry": {"type": "MultiLineString", "coordinates": simp[i:i + CHUNK]}}
             for i in range(0, len(simp), CHUNK)]
    depots = depot_points(ex.get("places", []), parts, DEPOT_NAME[g], g)
    for name, feats in ((f"{g}_yards.geojson", yards), (f"{g}_depots.geojson", depots)):
        p = OUT / name
        p.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":")))
        print(f"{name}: {len(feats)} features, {p.stat().st_size / 1e6:.2f} MB", flush=True)
    km = sum(LineString(co).length for co in simp) * 100
    print(f"{g} yard and siding track: about {km:.0f} km in {len(simp)} runs; {len(depots)} named yards and depots", flush=True)


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else ""
    if code not in DEPOT_NAME:
        sys.exit("usage: python3 scripts/yards.py jp|uk|kr")
    # written locally by scripts/extract_osm.py, so loading it is safe here
    write_yards(pickle.load(open(RAW / f"extract_{code}.pkl", "rb")), code)
