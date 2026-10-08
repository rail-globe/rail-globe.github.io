"""How well the drawn metro lines lie on their track.

A line is drawn from its own track, moved onto a common path where it runs in the company of other
lines, with its turnbacks taken out and its pieces joined. Each of those steps can go wrong in a
way that leaves the drawing continuous and smooth, and so unnoticed by the other checks: a line
carried across the inside of a junction, or stopping a few hundred metres short of its terminus.
Two measurements, per line:

- astray: stretches of the drawn line with none of the line's track near them;
- undrawn: stretches of the line's own track with nothing of the line drawn near them.

A railway-scale line may lie up to a corridor's width from its track; a light-rail line is drawn
on its track or on the one beside it, so its limits are a few tens of metres.
"""
from collections import defaultdict

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.strtree import STRtree

STEP = 0.0002                    # ~22 m between the points looked at
# (how far is away, how long a stretch has to be to count): light rail, everything else
ASTRAY = {True: (0.00025, 0.0005), False: (0.0018, 0.002)}
UNDRAWN = {True: (0.0004, 0.001), False: (0.002, 0.003)}


def stretches(geoms, others, limit, least):
    """Stretches of geoms further than limit from all of others, at least `least` long:
    [(length in degrees, lon, lat of its middle)]."""
    if not others:
        return [(g.length, *g.interpolate(0.5, normalized=True).coords[0]) for g in geoms if g.length >= least]
    tree = STRtree(others)
    out = []
    for g in geoms:
        n = max(2, int(g.length / STEP) + 1)
        at = np.linspace(0, g.length, n)
        pts = shapely.line_interpolate_point(g, at)
        far = np.ones(n, dtype=bool)
        hit, _ = tree.query(pts, predicate="dwithin", distance=limit)
        far[np.unique(hit)] = False
        k = 0
        while k < n:
            if not far[k]:
                k += 1
                continue
            j = k
            while j + 1 < n and far[j + 1]:
                j += 1
            if at[j] - at[k] + STEP >= least:
                mid = g.interpolate((at[k] + at[j]) / 2)
                out.append((float(at[j] - at[k] + STEP), round(mid.x, 5), round(mid.y, 5)))
            k = j + 1
    return out


def fit(features, tracks, paths, light=()):
    """features: the metro features as drawn. tracks: {(region, name): coordinate lists of every
    track of the line}. paths: {(region, name): the line's own path as LineStrings}. light: the
    (region, name) of light-rail lines. Returns {"astray": [...], "undrawn": [...]}, longest first:
    each entry {"line", "region", "km", "at": [lon, lat], "light"}."""
    drawn = defaultdict(list)
    for f in features:
        p, g = f["properties"], f["geometry"]
        if p.get("k") == "s" or not p.get("n"):
            continue
        for co in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]):
            if len(co) > 1:
                drawn[(p.get("r"), p["n"])].append(LineString(co))
    report = {"astray": [], "undrawn": []}
    for key in sorted(set(drawn) | set(paths)):
        is_light = key in light
        every = [LineString(co) for co in tracks.get(key, ()) if len(co) > 1]
        for kind, geoms, others, (limit, least) in (("astray", drawn.get(key, []), every, ASTRAY[is_light]),
                                                    ("undrawn", list(paths.get(key, ())), drawn.get(key, []), UNDRAWN[is_light])):
            if kind == "astray" and not every:
                continue                              # a line known by its drawing alone
            for length, x, y in stretches(geoms, others, limit, least):
                report[kind].append({"line": key[1], "region": key[0], "km": round(length * 105, 2), "at": [x, y], "light": is_light})
    for kind in report:
        report[kind].sort(key=lambda e: -e["km"])
    return report


def summary(report, most=8):
    lines = []
    for kind, what in (("astray", "drawn away from the line's track"), ("undrawn", "own track with nothing drawn")):
        rows = report[kind]
        light = [e for e in rows if e["light"]]
        lines.append(f"metro fit, {what}: {len(rows)} stretches, {sum(e['km'] for e in rows):.1f} km"
                     f" (light rail: {len(light)}, {sum(e['km'] for e in light):.1f} km)")
        for e in rows[:most]:
            lines.append(f"      {e['km']:5.2f} km  {e['line']} ({e['region']})  #16/{e['at'][1]:.4f}/{e['at'][0]:.4f}")
    return "\n".join(lines)
