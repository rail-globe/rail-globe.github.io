"""Lines drawn in the same place are moved apart, and only there.

A metro line is drawn on its own track. Where several lines are drawn along one path (track they
share, or tracks side by side that the corridor pass laid on one path) each gets a slot: -0.5 and
0.5 for two lines, -1, 0, 1 for three. The map turns the slot (property off) into a sideways shift
in pixels. Everywhere else the slot is 0, so a line does not leave its track where it runs alone
and its stations stay on it. Between the two the slot changes in small steps over a few hundred
metres, so the line moves over the way a train changes track, with no sideways jump.
"""
import math
from collections import defaultdict

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.ops import substring
from shapely.strtree import STRtree

NEAR = 0.00015       # ~17 m: two lines this close, running the same way, are drawn in the same place
STEP = 0.0003        # ~33 m between the points a line is looked at
MIN_RUN = 0.003      # ~330 m: shorter company is a crossing or a station throat, not a shared stretch
RAMP = 0.004         # ~440 m over which a line moves to its side
GRAIN = 0.125        # slots: the line moves over in steps of this size, under a pixel on the map
MAX_STEPS = 11


def alike(a, b):
    """Two colours that read as one: a through service under two names is drawn once."""
    if not a or not b or len(a) != 7 or len(b) != 7:
        return a == b
    return sum(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) for i in (1, 3, 5)) < 40


def heading(g, at, d=0.0003):
    a, b = g.interpolate(max(at - d, 0)), g.interpolate(min(at + d, g.length))
    n = math.hypot(b.x - a.x, b.y - a.y)
    return ((b.x - a.x) / n, (b.y - a.y) / n) if n else (0.0, 0.0)


def slots(parts, near=NEAR, step=STEP):
    """Per part, the slot at every sample: [(position, slot, number of lines there)].

    parts: [(line, colour, LineString)]. The slot is signed for the direction the part is written
    in, so that every line of a bundle ends up on its own side whichever way each one runs."""
    geoms = [g for _, _, g in parts]
    tree = STRtree(geoms)
    out = []
    for i, (line, colour, g) in enumerate(parts):
        n = max(2, int(round(g.length / step)) + 1)
        at = np.linspace(0, g.length, n)
        pts = shapely.line_interpolate_point(g, at)
        company = defaultdict(list)                  # sample -> [(colour, line, same way or not)]
        if len(geoms) > 1:
            for k, j in zip(*tree.query(pts, predicate="dwithin", distance=near)):
                other, col, h = parts[j][0], parts[j][1], geoms[j]
                if other == line or alike(col, colour):
                    continue
                a, b = heading(g, at[k]), heading(h, h.project(pts[k]))
                dot = a[0] * b[0] + a[1] * b[1]
                if abs(dot) > 0.8:                   # a line that crosses is not company
                    company[int(k)].append((col, other, 1 if dot > 0 else -1))
        row = []
        for k in range(n):
            mates = company.get(k)
            if not mates:
                row.append((float(at[k]), 0.0, 1))
                continue
            # one slot per colour, in a fixed order, so every line keeps its side from one stretch
            # to the next; the first line of the bundle says which way the bundle runs
            classes = []
            for col in sorted({colour} | {m[0] for m in mates}):
                if not any(alike(col, c) for c in classes):
                    classes.append(col)
            mine = next(x for x, c in enumerate(classes) if alike(c, colour))
            lead = min(mates + [(colour, line, 1)])
            row.append((float(at[k]), lead[2] * (mine - (len(classes) - 1) / 2), len(classes)))
        out.append(row)
    return out


def stretches(row, min_run=MIN_RUN):
    """The samples of one part as stretches of one slot: [[from, to, slot, lines]]. A stretch too
    short to be drawn on its own (a line crossed, a station throat) goes to its longer neighbour."""
    runs = []
    for pos, slot, lines in row:
        if runs and runs[-1][2] == slot and runs[-1][3] == lines:
            runs[-1][1] = pos
        else:
            runs.append([pos, pos, slot, lines])
    for a, b in zip(runs, runs[1:]):                 # one stretch ends and the next begins halfway between two samples
        a[1] = b[0] = (a[1] + b[0]) / 2
    while len(runs) > 1:
        k = min(range(len(runs)), key=lambda x: runs[x][1] - runs[x][0])
        if runs[k][1] - runs[k][0] >= min_run:
            break
        sides = [x for x in (k - 1, k + 1) if 0 <= x < len(runs)]
        keep = max(sides, key=lambda x: runs[x][1] - runs[x][0])
        runs[keep][0], runs[keep][1] = min(runs[keep][0], runs[k][0]), max(runs[keep][1], runs[k][1])
        del runs[k]
        for x in range(len(runs) - 1, 0, -1):        # the neighbours may now be one stretch
            if runs[x][2] == runs[x - 1][2] and runs[x][3] == runs[x - 1][3]:
                runs[x - 1][1] = runs[x][1]
                del runs[x]
    return runs


def eased(runs, ramp=RAMP, grain=GRAIN):
    """[(from, to, slot)] with every change of slot spread over a ramp of small steps. The ramp
    lies where there are fewer lines: a line has moved to its side by the time it meets another."""
    cuts = []                                        # (from, to, slot before, slot after)
    for a, b in zip(runs, runs[1:]):
        if a[2] == b[2]:
            continue
        room_a, room_b = min(ramp, 0.45 * (a[1] - a[0])), min(ramp, 0.45 * (b[1] - b[0]))
        if a[3] < b[3]:
            cuts.append((a[1] - room_a, a[1], a[2], b[2]))
        elif b[3] < a[3]:
            cuts.append((b[0], b[0] + room_b, a[2], b[2]))
        else:
            cuts.append((a[1] - room_a / 2, a[1] + room_b / 2, a[2], b[2]))
    out, at = [], runs[0][0]
    for lo, hi, u, v in cuts:
        out.append((at, lo, u))
        steps = max(1, min(MAX_STEPS, math.ceil(abs(v - u) / grain) - 1))
        for s in range(steps):
            out.append((lo + (hi - lo) * s / steps, lo + (hi - lo) * (s + 1) / steps, u + (v - u) * (s + 1) / (steps + 1)))
        at = hi
    out.append((at, runs[-1][1], runs[-1][2]))
    return [(a, b, s) for a, b, s in out if b - a > 1e-9]


def side_by_side(features, skip=lambda props: props.get("k") == "s"):
    """Rewrite the metro features so that each carries the slot of one stretch of its line: a line
    becomes a few features, one per slot. Returns the new list; other features pass through."""
    parts, where = [], []
    for fi, f in enumerate(features):
        props, g = f["properties"], f["geometry"]
        if skip(props) or not props.get("n"):
            continue
        for co in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]):
            if len(co) > 1 and LineString(co).length > 0:
                parts.append(((props.get("r"), props["n"]), props.get("col"), LineString(co)))
                where.append(fi)
    by_slot = defaultdict(lambda: defaultdict(list))             # feature -> slot -> lines
    for fi, (_, _, g), row in zip(where, parts, slots(parts)):
        for a, b, slot in eased(stretches(row)):
            piece = substring(g, a, b)
            if piece.geom_type == "LineString" and piece.length > 0:
                by_slot[fi][round(slot * 16) / 16].append([[round(x, 6), round(y, 6)] for x, y in piece.coords])
    out = []
    for fi, f in enumerate(features):
        if fi not in by_slot:
            out.append(f)
            continue
        for slot, lines in sorted(by_slot[fi].items(), key=lambda kv: (kv[0] != 0, kv[0])):
            props = {k: v for k, v in f["properties"].items() if k != "off"}
            if slot:
                props["off"] = slot
            out.append({**f, "properties": props,
                        "geometry": {"type": "LineString", "coordinates": lines[0]} if len(lines) == 1 else {"type": "MultiLineString", "coordinates": lines}})
    return out
