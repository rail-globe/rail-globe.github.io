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
import math
import pickle
import sys
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge
from shapely.strtree import STRtree

from depots import REACH, features, labels, running_lines, table_rows

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data"
YARD_SERVICE = {"yard", "siding", "crossover"}      # station and depot tracks; industrial spurs are left out
TRACK = {"rail", "subway", "light_rail", "tram", "monorail", "narrow_gauge"}
CHUNK = 400                 # a few large MultiLineStrings tile and render faster than one huge feature
BESIDE_M = 25.0             # metres: yard track that never leaves a drawn line by more than this is the line's own track
TOUCH = 0.00002             # degrees (~2 m): two pieces of yard track this close are one group
SAMPLE = 0.0002             # degrees (~22 m): how often a piece is measured against the lines
LENGTH = 8                  # vertices: the drawn lines are measured against in lengths of this many segments
M = 111320.0                # metres in a degree of latitude


def drawn_lines(g, data=None):
    """Every line of the country as the map draws it: railways, lines being built, urban lines."""
    data = data or OUT
    names = (("rail_hsr", "rail_conv", "rail_shared", "rail_build", "metro") if g == "cn"
             else (f"{g}_rail", f"{g}_build", f"{g}_metro"))
    out = []
    for name in names:
        path = data / f"{name}.geojson"
        for f in (json.loads(path.read_text())["features"] if path.exists() else []):
            geom = f["geometry"]
            out += [co for co in (geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]) if len(co) > 1]
    return out


def off_the_line(yards, lines, reach=BESIDE_M, named_at=(), named_reach=REACH):
    """The yard track worth drawing: [True where the piece stays]. A crossover, a passing loop or
    the second track of a line lies inside the line's own stroke, and beside a line drawn to one
    side it shows as stray threads between two lines (reported 2026-10-13). Pieces of yard track
    that touch are one group; a group that nowhere leaves the drawn lines by more than `reach` is
    the lines' own track and is not drawn. A group that does (the tracks of a station, a yard, a
    depot) is drawn whole, with the tracks nearest the line. So is a group by a name of the
    layer (named_at: [(lon, lat)]): a named yard that lies along its line keeps its tracks."""
    if not yards or not lines:
        return [True] * len(yards)
    pieces = [LineString(co) for co in yards]
    tree = STRtree(pieces)
    parent = list(range(len(pieces)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    a, b = tree.query(pieces, predicate="dwithin", distance=TOUCH)
    for i, j in zip(a.tolist(), b.tolist()):
        if i < j and find(i) != find(j):
            parent[find(i)] = find(j)
    owner, at = [], []
    for i, g in enumerate(pieces):
        n = max(2, int(g.length / SAMPLE) + 1)
        owner += [find(i)] * n
        at += [g.interpolate(k / (n - 1), normalized=True) for k in range(n)]
    owner, at = np.asarray(owner), np.asarray(at, dtype=object)
    # in short lengths: a line of a thousand kilometres has a box that every point of a province falls in
    drawn = np.asarray([LineString(co[k:k + LENGTH + 1]) for co in lines for k in range(0, len(co) - 1, LENGTH)], dtype=object)
    xy = shapely.get_coordinates(at)
    cosy = np.cos(np.radians(xy[:, 1]))
    # a degree of longitude is shorter than one of latitude: search wide, then measure in metres
    wide = reach / M / max(float(cosy.min()), 0.2)
    far = np.ones(len(at), dtype=bool)
    lines_tree = STRtree(drawn)
    for start in range(0, len(at), 200000):
        block = slice(start, start + 200000)
        pi, li = lines_tree.query(at[block], predicate="dwithin", distance=wide)
        if not len(pi):
            continue
        pi = pi + start
        foot = shapely.get_coordinates(shapely.line_interpolate_point(drawn[li], shapely.line_locate_point(drawn[li], at[pi])))
        metres = np.hypot((foot[:, 0] - xy[pi, 0]) * cosy[pi], foot[:, 1] - xy[pi, 1]) * M
        far[pi[metres <= reach]] = False
    leaves = set(owner[far].tolist())
    for lon, lat in named_at:
        cos = max(math.cos(math.radians(lat)), 0.2)
        here = shapely.Point(lon, lat)
        for i in tree.query(here, predicate="dwithin", distance=named_reach / M / cos):
            x, y = shapely.get_coordinates(shapely.line_interpolate_point(pieces[i], shapely.line_locate_point(pieces[i], here)))[0]
            if math.hypot((x - lon) * cos, y - lat) * M <= named_reach:
                leaves.add(find(int(i)))
    return [find(i) in leaves for i in range(len(pieces))]


def worth_drawing(g, runs, named, data=None):
    """[True where the run of yard track is drawn]: off_the_line(), with the names the layer has
    on all of its track, so that no name is lost with the track it stands on."""
    data = data or OUT
    found, _ = labels(g, runs, named, table_rows(g), running_lines(g, data)) if named is not None else ((), None)
    return off_the_line(runs, drawn_lines(g, data), named_at=[(lon, lat) for _, lon, lat, _ in found])
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
    stays = worth_drawing(g, simp, ex.get("named"))           # the country's lines are written before this
    print(f"{g} yard track that only runs along a drawn line, not drawn: {len(simp) - sum(stays)} of {len(simp)} runs, "
          f"about {sum(LineString(co).length for co, keep in zip(simp, stays) if not keep) * 100:.0f} km", flush=True)
    simp = [co for co, keep in zip(simp, stays) if keep]
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
