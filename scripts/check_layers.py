"""Check the drawn layers against the drawing rules. Run after scripts/process_osm.py.

    python3 scripts/check_layers.py            every check, worst cases first
    python3 scripts/check_layers.py metro      only the metro layer (rail | metro)

It reads data/*.geojson as written for the map and reports, per line:

  twice    a line drawn twice: two of its own pieces run beside each other
  broken   a line that stops and carries on a short distance further
  hidden   two different lines drawn on top of each other (they should be side by side)
  astray   a line moved to one side although no other line runs with it there
  sharp    a sudden change of direction: a line must be smooth

Every finding comes with a place (#zoom/lat/lon, to paste after http://localhost:8765/).
The script changes nothing; the exit code is 0 whatever it finds.
"""
import json
import argparse
import math
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString, Point, shape
from shapely.ops import linemerge, nearest_points
from shapely.strtree import STRtree

warnings.filterwarnings("ignore")
DATA = Path(__file__).resolve().parents[1] / "data"
BESIDE = 0.0006      # ~60 m: two pieces of one line this close, side by side, are the line drawn twice
JOINED = 0.0003      # ~30 m: two pieces this close are joined
GAP_MAX = 0.03       # ~3 km: a line that resumes within this distance is broken, further away it is two sections
ON_TOP = 0.00012     # ~12 m: two lines this close in the same slot hide each other
RAMP_MAX = 0.006     # ~650 m: a shorter moved piece is a line changing sides, or a short shared stretch
KM = 111.0


def here(pt, zoom=15):
    return f"#{zoom}/{pt.y:.4f}/{pt.x:.4f}"


def load(name):
    out = []
    for f in json.load(open(DATA / name))["features"]:
        g = shape(f["geometry"])
        out.append((f["properties"], [x for x in (g.geoms if hasattr(g, "geoms") else [g]) if x.length > 0]))
    return out


def samples(line, step):
    n = max(2, int(line.length / step) + 1)
    return [line.interpolate(i / (n - 1), normalized=True) for i in range(n)], line.length / (n - 1)


COLOUR = {}          # line -> colour, to tell a through service in one colour from two lines


def alike(a, b):
    if not a or not b or len(a) != 7 or len(b) != 7:
        return a == b
    return sum(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) for i in (1, 3, 5)) < 40


def lines_of(layer):
    """{line: [(piece, slot)]} for the layer: a line can be written as several features."""
    out = defaultdict(list)
    if layer in ("metro", "suburb"):
        for p, parts in load("metro.geojson"):
            if (p.get("k") == "s") == (layer == "suburb") and p.get("n"):
                out[(p.get("ct"), p["n"])] += [(g, p.get("off", 0)) for g in parts]
                COLOUR[(p.get("ct"), p["n"])] = p.get("col")
    else:
        files = {"rail": ("rail_hsr.geojson", "rail_conv.geojson"),
                 "shared": ("rail_shared.geojson",), "construction": ("rail_build.geojson",)}
        for name in files[layer]:
            for index, (p, parts) in enumerate(load(name)):
                label = p.get("n") or f"未命名[{name}:{index}]"
                # A railway keeps its identity across a design-grade boundary. Checking
                # each colour separately would mistake intentional grade cuts for ends.
                out[("rail" if layer == "rail" else p["c"], label)] += [(g, 0) for g in parts]
    if layer == 'rail':
        for key, pieces in out.items():
            if len(pieces) > 1:
                merged = linemerge(MultiLineString([g for g, _ in pieces]))
                geoms = list(merged.geoms) if merged.geom_type == 'MultiLineString' else [merged]
                out[key] = [(g, 0) for g in geoms]
    return out


def twice(lines, step):
    """Length of each line that has another stretch of the same line beside it."""
    found = []
    for key, pieces in lines.items():
        geoms = [g for g, _ in pieces]
        tree = STRtree(geoms)
        bad, worst = 0.0, None
        for i, g in enumerate(geoms):
            pts, spacing = samples(g, step)
            if len(pts) < 5:
                continue
            ptree = STRtree(pts)
            for k, pt in enumerate(pts[2:-2], 2):          # ends meet other pieces at junctions: leave them out
                beside = any(int(j) != i and JOINED / 10 < geoms[int(j)].distance(pt) < BESIDE
                             and min(Point(geoms[int(j)].coords[0]).distance(pt), Point(geoms[int(j)].coords[-1]).distance(pt)) > 2 * BESIDE
                             for j in tree.query(pt, predicate="dwithin", distance=BESIDE))
                fold = any(abs(int(j) - k) * spacing > 4 * BESIDE for j in ptree.query(pt, predicate="dwithin", distance=BESIDE))
                if beside or fold:
                    bad += spacing
                    worst = worst or pt
        if bad * KM > 1:
            found.append((bad * KM, key, worst))
    return sorted(found, key=lambda f: -f[0])


def broken(lines):
    """Lines that stop and resume: the gaps between the connected parts of a line."""
    found = []
    for key, pieces in lines.items():
        geoms = [g for g, _ in pieces]
        if len(geoms) < 2:
            continue
        tree = STRtree(geoms)
        group = list(range(len(geoms)))

        def root(i):
            while group[i] != i:
                group[i] = group[group[i]]
                i = group[i]
            return i
        for i, g in enumerate(geoms):
            for j in tree.query(g, predicate="dwithin", distance=JOINED):
                group[root(int(j))] = root(i)
        parts = defaultdict(list)
        for i, g in enumerate(geoms):
            parts[root(i)].append(g)
        if len(parts) < 2:
            continue
        whole = [shapely.union_all(v) for v in parts.values()]
        for a in range(len(whole)):
            near = min(((whole[a].distance(whole[b]), b) for b in range(len(whole)) if b != a), default=None)
            if near and JOINED < near[0] < GAP_MAX and a < near[1]:
                pa, pb = nearest_points(whole[a], whole[near[1]])
                found.append((near[0] * KM * 1000, key, pa, min(whole[a].length, whole[near[1]].length) * KM))
    return sorted(found, key=lambda f: -f[3])


def heading(g, at, d=0.0003):
    a, b = g.interpolate(max(at - d, 0)), g.interpolate(min(at + d, g.length))
    n = math.hypot(b.x - a.x, b.y - a.y)
    return ((b.x - a.x) / n, (b.y - a.y) / n) if n else (0.0, 0.0)


def company(lines, step):
    """For every piece of every line, what runs along it: (line, slot, piece, [per sample:
    (point, [(other line, the side it is drawn on, seen from this piece)])]). The map shifts a
    piece to the right of the direction it is written in, so a line running the other way with
    the opposite slot is on the same side."""
    geoms, owner, slot = [], [], []
    for key, pieces in lines.items():
        for g, off in pieces:
            geoms.append(g)
            owner.append(key)
            slot.append(off)
    tree = STRtree(geoms)
    for i, g in enumerate(geoms):
        n = max(2, int(g.length / step) + 1)
        row = []
        for k in range(n):
            at = g.length * k / (n - 1)
            pt, mine, mates = g.interpolate(at), None, []
            for j in tree.query(pt, predicate="dwithin", distance=ON_TOP):
                j = int(j)
                if owner[j] == owner[i] or alike(COLOUR.get(owner[i]), COLOUR.get(owner[j])):
                    continue                                   # one colour: a through service, drawn once on purpose
                mine = mine or heading(g, at)
                other = heading(geoms[j], geoms[j].project(pt))
                dot = mine[0] * other[0] + mine[1] * other[1]
                if abs(dot) > 0.85:                            # a line that crosses is not beside
                    mates.append((owner[j], slot[j] * (1 if dot > 0 else -1)))
            row.append((pt, mates))
        yield owner[i], slot[i], g, g.length / (n - 1), row


def hidden(lines, step):
    """Pairs of different lines drawn in the same place, on the same side: one covers the other."""
    pairs, where = defaultdict(float), {}
    for key, off, g, spacing, row in company(lines, step):
        for pt, mates in row:
            for other, side in mates:
                if key < other and abs(off - side) < 0.4:
                    pairs[(key, other)] += spacing
                    where.setdefault((key, other), pt)
    return sorted(((v * KM, k, where[k]) for k, v in pairs.items() if v * KM > 1), key=lambda f: -f[0])


def astray(lines, step):
    """Lines moved off their own track where nothing runs with them: a line is drawn to one side
    only along a stretch it shares. Short moved pieces are the line changing sides and are left out."""
    found, where = defaultdict(float), {}
    for key, off, g, spacing, row in company(lines, step):
        if abs(off) < 0.25 or g.length < RAMP_MAX:
            continue
        for pt, mates in row:
            if not mates:
                found[key] += spacing
                where.setdefault(key, pt)
    return sorted(((v * KM, k, where[k]) for k, v in found.items() if v * KM > 1), key=lambda f: -f[0])


def sharp(lines, limit=70.0):
    """Sudden changes of direction: turns sharper than `limit` degrees."""
    found = []
    for key, pieces in lines.items():
        for g, _ in pieces:
            co = list(g.coords)
            for a, b, c in zip(co, co[1:], co[2:]):
                k = math.cos(math.radians(b[1]))
                v1, v2 = ((b[0] - a[0]) * k, b[1] - a[1]), ((c[0] - b[0]) * k, c[1] - b[1])
                n1, n2 = math.hypot(*v1), math.hypot(*v2)
                if n1 > 0.00003 and n2 > 0.00003:
                    angle = math.degrees(math.acos(max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / n1 / n2))))
                    if angle > limit:
                        found.append((angle, key, Point(b)))
    return sorted(found, key=lambda f: -f[0])


def report(layer):
    lines = lines_of(layer)
    step = 0.0015 if layer == "metro" else 0.003
    total = sum(g.length for pieces in lines.values() for g, _ in pieces) * KM
    print(f"== {layer}: {len(lines)} lines, {total:.0f} km drawn")
    # Unnamed features collect unrelated tracks across the country. They can be checked for
    # corners, but their separate pieces cannot be treated as one named continuous route.
    named = {key: pieces for key, pieces in lines.items() if not key[1].startswith("未命名[")}
    result = {"lines": len(lines), "drawn_km": total, "twice": [], "broken": [], "sharp": [], "hidden": [], "astray": []}
    found = twice(named, step)
    result["twice"] = [{"km": length, "line": list(key), "view": here(pt)} for length, key, pt in found]
    print(f"   twice: {len(found)} lines with more than 1 km drawn twice, {sum(f[0] for f in found):.0f} km in all")
    for length, key, pt in found[:15]:
        print(f"      {length:6.1f} km  {key[1]} ({key[0]})  {here(pt)}")
    found = broken(named)
    result["broken"] = [{"gap_m": gap, "line": list(key), "view": here(pt, 16), "part_km": size} for gap, key, pt, size in found]
    print(f"   broken: {len(found)} places where a line stops and carries on within 3 km")
    for gap, key, pt, size in found[:25]:
        print(f"      gap {gap:5.0f} m  {key[1]} ({key[0]}), the smaller part is {size:.1f} km  {here(pt, 16)}")
    found = sharp(lines)
    result["sharp"] = [{"angle": angle, "line": list(key), "view": here(pt, 17)} for angle, key, pt in found]
    print(f"   sharp: {len(found)} turns of more than 70 degrees")
    for angle, key, pt in found[:12]:
        print(f"      {angle:4.0f} deg  {key[1]} ({key[0]})  {here(pt, 17)}")
    if layer == "metro":
        found = hidden(lines, step / 3)
        result["hidden"] = [{"km": length, "lines": [list(a), list(b)], "view": here(pt)} for length, (a, b), pt in found]
        print(f"   hidden: {len(found)} pairs of lines drawn on top of each other for more than 1 km")
        for length, (a, b), pt in found[:20]:
            print(f"      {length:6.1f} km  {a[1]} + {b[1]} ({a[0]})  {here(pt)}")
        found = astray(lines, step / 3)
        result["astray"] = [{"km": length, "line": list(key), "view": here(pt)} for length, key, pt in found]
        print(f"   astray: {len(found)} lines moved off their track for more than 1 km with no line beside them, {sum(f[0] for f in found):.0f} km in all")
        for length, key, pt in found[:15]:
            print(f"      {length:6.1f} km  {key[1]} ({key[0]})  {here(pt)}")
    return result


LAYERS = ["metro", "rail", "suburb", "shared", "construction"]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layers", nargs="*", metavar="layer", help=" | ".join(LAYERS))
    parser.add_argument("--json", type=Path, help="Save every finding, including those beyond the printed examples")
    args = parser.parse_args()
    for layer in args.layers:
        if layer not in LAYERS:
            parser.error(f"unknown layer {layer!r}: choose from {', '.join(LAYERS)}")
    results = {layer: report(layer) for layer in (args.layers or LAYERS)}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=2))
