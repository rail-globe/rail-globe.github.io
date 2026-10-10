"""Yards and depots of a country abroad, as the Chinese map draws them (scripts/process_osm.py):
station, yard and depot track under everything else, and the named yards and depots beside it.

    python3 scripts/yards.py jp           -> data/jp_yards.geojson, data/jp_depots.geojson
    python3 scripts/yards.py uk           -> data/uk_yards.geojson, data/uk_depots.geojson
    python3 scripts/yards.py kr           -> data/kr_yards.geojson, data/kr_depots.geojson
    python3 scripts/yards.py cn           -> data/depots.geojson only, from data/yards.geojson as it is

The scripts of the countries (process_jp.py, and scripts/country.py for the others) call this at their end, so a full run of either
writes these too; run on its own it takes seconds. Which name labels which depot is decided in
scripts/depots.py, for China as well: scripts/process_osm.py writes its labels through write_depots()
here, and "cn" above writes them again without the rest of that run (after the names table or the
rules have changed).
"""
import json
import pickle
import sys
from pathlib import Path

from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge

from depots import features, labels, running_lines, table_rows

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data"
YARD_SERVICE = {"yard", "siding", "crossover"}      # station and depot tracks; industrial spurs are left out
TRACK = {"rail", "subway", "light_rail", "tram", "monorail", "narrow_gauge"}
CHUNK = 400                 # a few large MultiLineStrings tile and render faster than one huge feature
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


def write_depots(g, lines, named, name=None):
    """The labels of a country's yards and depots, written to its depots file. lines: its yard
    track as drawn; named: the named ground and yard objects of its extract."""
    if named is None:
        sys.exit(f"the extract of {g} has no named ground yet: run  python3 scripts/extract_osm.py {'' if g == 'cn' else g + ' '}places")
    found, notes = labels(g, lines, named, table_rows(g), running_lines(g, OUT))     # its metro file is written before this
    feats = features(g, found, abroad=g != "cn", named=named)
    p = OUT / (name or f"{g}_depots.geojson")
    p.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":")))
    print(f"{p.name}: {len(feats)} features, {p.stat().st_size / 1e6:.2f} MB", flush=True)
    by = {k: sum(1 for f in found if f[3] == k) for k in ("ground", "object", "table")}
    print(f"{g} depots: {notes['depots']} fans of yard track taken as depots; labels from named ground with its tracks {by['ground']}, "
          f"from a yard or depot object {by['object']}, from the names table {by['table']}", flush=True)
    for what, key in (("table rows at no fan of yard track", "no_depot"), ("table rows at a depot that has a row already", "second_row"),
                      ("table rows whose depot OSM names otherwise (OSM's name is shown)", "osm_differs")):
        if notes[key]:
            print(f"{g} depots, to look at: {what}: {notes[key]}", flush=True)
    return feats


def write_yards(ex, g):
    simp, parts = yard_lines(ex["ways"])
    yards = [{"type": "Feature", "properties": {"g": g}, "geometry": {"type": "MultiLineString", "coordinates": simp[i:i + CHUNK]}}
             for i in range(0, len(simp), CHUNK)]
    p = OUT / f"{g}_yards.geojson"
    p.write_text(json.dumps({"type": "FeatureCollection", "features": yards}, ensure_ascii=False, separators=(",", ":")))
    print(f"{p.name}: {len(yards)} features, {p.stat().st_size / 1e6:.2f} MB", flush=True)
    depots = write_depots(g, simp, ex.get("named"))
    km = sum(LineString(co).length for co in simp) * 100
    print(f"{g} yard and siding track: about {km:.0f} km in {len(simp)} runs; {len(depots)} named yards and depots", flush=True)


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else ""
    if code not in ("jp", "uk", "kr", "cn"):
        sys.exit("usage: python3 scripts/yards.py jp|uk|kr|cn")
    # written locally by scripts/extract_osm.py, so loading it is safe here
    if code == "cn":          # China's yard track is written by scripts/process_osm.py: only the labels again
        lines = [co for f in json.loads((OUT / "yards.geojson").read_text())["features"]
                 for co in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]])]
        write_depots("cn", lines, pickle.load(open(RAW / "extract.pkl", "rb")).get("named"), "depots.geojson")
    else:
        write_yards(pickle.load(open(RAW / f"extract_{code}.pkl", "rb")), code)
