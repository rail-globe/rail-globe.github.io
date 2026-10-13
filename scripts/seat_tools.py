#!/usr/bin/env python3
"""Tools for writing data/seat_overrides.json (seats given by hand along a corridor).

    python3 scripts/seat_tools.py box <lon1,lat1,lon2,lat2>
        the named lines inside a box: kind, class, km inside
    python3 scripts/seat_tools.py table <spine> <from lon,lat> <to lon,lat> [step km=1] [reach m=100]
        what runs along a line between two points: for each other line its distance aside
        (metres, + = to the right of the spine's direction), the seat it has without the list
        (in the spine's terms), and its kind
    python3 scripts/seat_tools.py check <corridors.json> [more.json ...] [--step km] [--show]
        the files applied in memory: the seat of every line along each spine, and where two lines
        would be drawn closer than half a step at zoom 12, or in another order than their tracks lie

They read the layers as they are without any seat by hand (the copies scripts/process_osm.py sets
aside under data/raw/, or data/ where there are none) and write nothing.
"""
import json
import math
import sys
import tempfile
from pathlib import Path

from shapely.geometry import LineString, box

import seat_overrides as S

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAIL = ("rail_hsr.geojson", "rail_conv.geojson", "rail_shared.geojson")
SKIP = ("联络", "走行", "疏解", "动车所", "动车段", "出入")      # connecting and depot lines are not seated (owner, 2026-10-13)
PX12, STEP12 = 1 / 30.0, 5.0            # at zoom 12: pixels to a metre near Beijing, pixels to a step


def layers():
    """{file: features} of the layers before any seat by hand."""
    out = {}
    for name in RAIL:
        base = DATA / "raw" / "design_base" / name
        out[name] = json.loads((base if base.exists() else DATA / name).read_text())["features"]
    base = DATA / "raw" / "seat_base" / "metro.geojson"
    out["metro.geojson"] = json.loads((base if base.exists() else DATA / "metro.geojson").read_text())["features"]
    return out


def kind(name, props):
    if name == "metro.geojson":
        return "suburban guest" if props.get("k") == "s" else "urban"
    return {"rail_hsr.geojson": "fast rail", "rail_conv.geojson": "rail", "rail_shared.geojson": "shared rail"}[name]


def paths(f):
    g = f["geometry"]
    return g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]


def beside(corridor, by_file, s, reach):
    """What runs along the spine at s metres: {line: (metres aside, + = right; seat in the spine's terms; kind)}."""
    here = corridor.spine.interpolate(s)
    a, b = corridor.spine.interpolate(max(s - 30, 0)), corridor.spine.interpolate(min(s + 30, corridor.spine.length))
    ex, ey = b.x - a.x, b.y - a.y
    n = math.hypot(ex, ey) or 1
    hx, hy = here.x / (corridor.cos * S.M), here.y / S.M
    pad = (reach + 50) / S.M
    out = {}
    for name, feats in by_file.items():
        for f in feats:
            props = f["properties"]
            line = props.get("n")
            if not line:
                continue
            for co in paths(f):
                if len(co) < 2:
                    continue
                xs, ys = [p[0] for p in co], [p[1] for p in co]
                if hx < min(xs) - pad / corridor.cos or hx > max(xs) + pad / corridor.cos or hy < min(ys) - pad or hy > max(ys) + pad:
                    continue
                g = LineString([corridor.xy(p) for p in co])
                if g.distance(here) > reach:
                    continue
                t = g.project(here)
                p0, p1 = g.interpolate(max(t - 20, 0)), g.interpolate(min(t + 20, g.length))
                dx, dy = p1.x - p0.x, p1.y - p0.y
                dot = (dx * ex + dy * ey) / ((math.hypot(dx, dy) or 1) * n)
                if abs(dot) < 0.7:
                    continue                                # it crosses
                foot = g.interpolate(t)
                side = ((foot.x - here.x) * ey - (foot.y - here.y) * ex) / n        # + = right of the spine
                off = props.get("off", 1 if props.get("k") == "s" else 0)
                if line not in out or abs(side) < abs(out[line][0]):
                    out[line] = (side, off if dot > 0 else -off, kind(name, props))
    return out


def lonlat(corridor, point):
    return f"{point.x / (corridor.cos * S.M):.4f},{point.y / S.M:.4f}"


def cmd_box(args):
    x1, y1, x2, y2 = [float(v) for v in args[0].split(",")]
    area = box(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    rows = {}
    for name, feats in layers().items():
        for f in feats:
            p = f["properties"]
            for co in paths(f) if p.get("n") else ():
                if len(co) > 1 and LineString(co).intersects(area):
                    r = rows.setdefault(p["n"], [kind(name, p), p.get("c") or p.get("jk"), 0.0])
                    r[2] += LineString(co).intersection(area).length * 100
    for n, (k, c, km) in sorted(rows.items(), key=lambda kv: -kv[1][2]):
        print(f"{km:6.1f} km  {n}  [{k}, {c}]{'  (connecting or depot line: not seated)' if any(w in n for w in SKIP) else ''}")


def cmd_table(args):
    spine, a, b = args[0], [float(v) for v in args[1].split(",")], [float(v) for v in args[2].split(",")]
    step = float(args[3]) if len(args) > 3 else 1.0
    reach = float(args[4]) if len(args) > 4 else 100.0
    by = layers()
    spine_paths = [co for feats in by.values() for f in feats if f["properties"].get("n") == spine for co in paths(f)]
    if not spine_paths:
        sys.exit(f"no line named {spine}")
    c = S.Corridor({"name": "table", "from": a, "to": b, "reach_m": reach, "ramp_m": 1200, "seats": {}}, spine_paths)
    print(f"spine {spine}: {c.spine.length / 1000:.1f} km; + = right of the direction from {a} to {b}; (seat without the list); lines named {SKIP} are left out")
    s, kinds = 0.0, {}
    while s <= c.spine.length:
        near = {n: v for n, v in beside(c, by, s, reach).items() if n != spine and not any(w in n for w in SKIP)}
        kinds.update({n: v[2] for n, v in near.items()})
        print(f"{s / 1000:5.1f} km  {lonlat(c, c.spine.interpolate(s))}  " + "  ".join(f"{n}:{v[0]:+.0f}m({v[1]:+g})" for n, v in sorted(near.items(), key=lambda kv: kv[1][0])))
        s += step * 1000
    print("kinds:", kinds)


def cmd_check(args):
    files = [a for a in args if not a.startswith("--")]
    step = 0.5
    if "--step" in args:
        step = float(args[args.index("--step") + 1])
        files.remove(args[args.index("--step") + 1])
    show = "--show" in args
    rows = [row for a in files for row in json.loads(Path(a).read_text(encoding="utf-8"))["corridors"]]
    merged = Path(tempfile.mkdtemp()) / "all.json"
    merged.write_text(json.dumps({"corridors": rows}, ensure_ascii=False), encoding="utf-8")
    by = layers()
    listed = S.corridors("cn", [f for feats in by.values() for f in feats], merged)
    seated = {name: S.apply(feats, listed, urban=name == "metro.geojson")[0] for name, feats in by.items()}
    print(f"{len(listed)} corridors; {sum(len(v) for v in seated.values()) - sum(len(v) for v in by.values())} more features than before")
    problems = 0
    for c in listed:
        print(f"== {c.name}: spine {c.spine.length / 1000:.1f} km; seats in the spine's terms (+ = right)")
        s = 0.0
        while s <= c.spine.length:
            near = {n: v for n, v in beside(c, seated, s, c.reach).items() if not any(w in n for w in SKIP)}
            drawn = sorted((v[1] * STEP12 + v[0] * PX12, v[0], n, v[1]) for n, v in near.items())
            flags = []
            for (pa, da, na, _), (pb, db, nb, _) in zip(drawn, drawn[1:]):
                if pb - pa < STEP12 * 0.5:
                    flags.append(f"{na} and {nb} only {pb - pa:.1f} px apart")
                if da > db + 25:
                    flags.append(f"{na} drawn left of {nb} but its track is {da - db:.0f} m to the right")
            problems += len(flags)
            if show or flags:
                print(f"{s / 1000:5.1f} km {lonlat(c, c.spine.interpolate(s))}  " + "  ".join(f"{n}:{seat:+g}" for _, _, n, seat in drawn)
                      + ("   !! " + "; ".join(flags) if flags else ""))
            s += step * 1000
    print("problems:", problems)


if __name__ == "__main__":
    commands = {"box": cmd_box, "table": cmd_table, "check": cmd_check}
    if len(sys.argv) < 3 or sys.argv[1] not in commands:
        sys.exit(__doc__)
    commands[sys.argv[1]](sys.argv[2:])
