"""Lines drawn in the same place are moved apart, and only there.

A metro line is drawn on its own track. Where several lines are drawn along one path (track they
share, or tracks side by side that the corridor pass laid on one path) each gets a slot: -0.5 and
0.5 for two lines, -1, 0, 1 for three. The map turns the slot (property off) into a sideways shift
in pixels. Everywhere else the slot is 0, so a line does not leave its track where it runs alone
and its stations stay on it. With continuous=True the transition is a distance-parametrised
quintic curve on independent display geometry. Legacy callers retain their frozen feature
contract; the full-path renderer replaces those quantised steps without moving source geometry.
"""
import math
from collections import defaultdict

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.ops import substring
from shapely.strtree import STRtree

from continuous_offset import chains, encode, profile, source_identity, value_at

NEAR = 0.00015       # ~17 m: two lines this close, running the same way, are drawn in the same place
STEP = 0.0003        # ~33 m between the points a line is looked at
MIN_RUN = 0.003      # ~330 m: shorter company is a crossing or a station throat, not a shared stretch
RAMP = 0.004         # ~440 m over which a line moves to its side
GRAIN = 0.125        # slots: the line moves over in steps of this size, under a pixel on the map


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
                if other == line:
                    continue
                a, b = heading(g, at[k]), heading(h, h.project(pts[k]))
                dot = a[0] * b[0] + a[1] * b[1]
                if abs(dot) > 0.8:                   # a line that crosses is not company
                    company[int(k)].append((col, other, 1 if dot > 0 else -1))
        row = []
        for k in range(n):
            present = company.get(k, [])
            # a line in the same colour is the same line under another name: it takes no slot,
            # but it is there, and may be the one that says which way the bundle runs
            explicit = lambda key: isinstance(key, tuple) and key[0] == "source"
            same = lambda col, key, other_col, other_key: (key == other_key
                if explicit(key) or explicit(other_key) else alike(col, other_col))
            mates = [m for m in present if not same(m[0], m[1], colour, line)]
            if not mates:
                row.append((float(at[k]), 0.0, 1))
                continue
            # one slot per colour, in a fixed order, so every line keeps its side from one stretch
            # to the next
            classes = []
            for col, key in sorted({(colour, line)} | {(m[0], m[1]) for m in mates}, key=lambda pair: (pair[0] or "", str(pair[1]))):
                if not any(same(col, key, c, k) for c, k in classes):
                    classes.append((col, key))
            mine = next(x for x, (c, key) in enumerate(classes) if same(c, key, colour, line))
            # The bundle runs the way most of its lines are written; with as many each way, the
            # way of its first line. Going by the first line alone, every line would change sides
            # where a line written the other way joins the bundle or leaves it.
            ways = sum(m[2] for m in present) + 1
            way = (1 if ways > 0 else -1) if ways else min(present + [(colour, line, 1)], key=lambda m: (m[0] or "", str(m[1])))[2]
            row.append((float(at[k]), way * (mine - (len(classes) - 1) / 2), len(classes)))
        out.append(row)
    return out


def abreast(parts, near=0.0003, step=0.0005, reach=0.0012):
    """Slots for railway lines that each lie on their own track, a few metres from the next: the
    lines of one corridor (山手線, 京浜東北線 and 東海道本線 out of 東京). Same form as slots().

    Here the lines are not on one path, so their order is given: a line's slot is its place in the
    corridor counted from the left, seen along the line. Its neighbours are the lines within `near`
    of it running the same way, and their neighbours in turn, out to `reach` on either side: every
    line of a corridor then counts the same lines and comes to the same order, whichever of them
    is asked."""
    geoms = [g for _, _, g in parts]
    tree = STRtree(geoms)
    out = []
    for i, (line, _, g) in enumerate(parts):
        n = max(2, int(round(g.length / step)) + 1)
        at = np.linspace(0, g.length, n)
        pts = shapely.line_interpolate_point(g, at)
        beside = defaultdict(set)
        if len(geoms) > 1:
            for k, j in zip(*tree.query(pts, predicate="dwithin", distance=near)):
                if parts[j][0] != line:
                    beside[int(k)].add(int(j))
        row = []
        for k in range(n):
            if k not in beside:
                row.append((float(at[k]), 0.0, 1))
                continue
            p, h = pts[k], heading(g, at[k])
            right = {line: 0.0}                       # line -> how far to the right of this one it runs here
            todo = [p]
            while todo:
                q = todo.pop()
                for j in tree.query(q, predicate="dwithin", distance=near):
                    other, o = parts[int(j)][0], geoms[int(j)]
                    if other in right:
                        continue
                    on = o.project(p)
                    there = o.interpolate(on)
                    side = -(h[0] * (there.y - p.y) - h[1] * (there.x - p.x))
                    way = heading(o, on)
                    if abs(side) > reach or abs(h[0] * way[0] + h[1] * way[1]) < 0.9:
                        continue                      # too far across to be the same corridor, or a line that crosses
                    right[other] = side
                    todo.append(o.interpolate(o.project(q)))
            if len(right) == 1:
                row.append((float(at[k]), 0.0, 1))
                continue
            order = sorted(right, key=lambda name: (right[name], str(name)))
            row.append((float(at[k]), order.index(line) - (len(order) - 1) / 2, len(order)))
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
    """Continuous profile; grain is accepted for old callers, not quantisation."""
    return profile(runs, ramp)


def side_by_side(features, skip=lambda props: props.get("k") == "s", slots_of=slots, min_run=MIN_RUN, rings=False, continuous=False, group_of=None):
    """Attach seats to metro features. Other features pass through.
    slots_of: slots() for lines drawn along one path, abreast() for lines on their own track.
    continuous: exact endpoint chains share an op domain; original vertices and ring starts stay.
    rings: only legacy mode rotates a ring into its longest constant-seat stretch.
    group_of: independent continuous seating groups, e.g. surface trams versus subways."""
    parts, where = [], []
    for fi, f in enumerate(features):
        props, g = f["properties"], f["geometry"]
        if skip(props) or not props.get("n"):
            continue
        for co in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]):
            if len(co) > 1 and LineString(co).length > 0:
                parts.append((source_identity(props), props.get("col"), LineString(co)))
                where.append(fi)
    if not continuous:
        return _legacy_features(features, parts, where, slots_of, min_run, rings)
    joined = chains(parts)
    whole = [(parts[members[0][0]][0], parts[members[0][0]][1], LineString(co))
             for co, members in joined]
    if group_of is None:
        rows = list(slots_of(whole))
    else:
        groups = defaultdict(list)
        for i, (_, members) in enumerate(joined):
            groups[group_of(features[where[members[0][0]]]["properties"])].append(i)
        rows = [None] * len(whole)
        for indices in groups.values():
            for i, row in zip(indices, slots_of([whole[i] for i in indices])):
                rows[i] = row
    specs = {}
    for (_, members), (_, _, geom), row in zip(joined, whole, rows):
        spec = profile(stretches(row, min_run), RAMP, closed=geom.is_ring)
        for pi, start, direction in members:
            origin = start if direction == 1 else start + parts[pi][2].length
            specs[pi] = {**spec, "origin": origin, "direction": direction}
    by_feature = defaultdict(list)
    for pi, fi in enumerate(where):
        by_feature[fi].append(pi)
    out = []
    for fi, f in enumerate(features):
        if fi not in by_feature:
            out.append(f)
            continue
        indices = by_feature[fi]
        if all(not specs[pi]["base"] and not specs[pi]["ramps"] for pi in indices):
            props = {k: v for k, v in f["properties"].items() if k not in ("off", "op")}
            out.append({**f, "properties": props})
            continue
        # One scalar JSON profile per original part, with every original vertex
        # retained. off is a representative seat for legacy width/host styling.
        for pi in indices:
            spec, geom = specs[pi], parts[pi][2]
            props = {k: v for k, v in f["properties"].items() if k not in ("off", "op")}
            props["off"] = value_at(spec, geom.length / 2)
            props["op"] = encode(spec, spec["origin"], spec["direction"])
            if slots_of is abreast:
                props.setdefault("ap", 1)
            out.append({**f, "properties": props, "geometry": {
                "type": "LineString", "coordinates": [list(c) for c in geom.coords]}})
    return out


def _legacy_eased(runs, ramp=RAMP, grain=GRAIN):
    """Frozen data contract, not the renderer. UK/KR/CN/JP callers stay byte-compatible."""
    cuts = []
    for a, b in zip(runs, runs[1:]):
        if a[2] == b[2]:
            continue
        ra, rb = min(ramp, .45 * (a[1] - a[0])), min(ramp, .45 * (b[1] - b[0]))
        cuts.append((a[1] - ra, a[1], a[2], b[2]) if a[3] < b[3] else
                    (b[0], b[0] + rb, a[2], b[2]) if b[3] < a[3] else
                    (a[1] - ra / 2, a[1] + rb / 2, a[2], b[2]))
    out, at = [], runs[0][0]
    for lo, hi, u, v in cuts:
        out.append((at, lo, u))
        steps = max(1, min(11, math.ceil(abs(v - u) / grain) - 1))
        for s in range(steps):
            out.append((lo + (hi - lo) * s / steps, lo + (hi - lo) * (s + 1) / steps,
                        u + (v - u) * (s + 1) / (steps + 1)))
        at = hi
    out.append((at, runs[-1][1], runs[-1][2]))
    return [(a, b, s) for a, b, s in out if b - a > 1e-9]


def _legacy_features(features, parts, where, slots_of, min_run, rings):
    rows = list(slots_of(parts))
    if rings:
        turned = False
        for k, ((key, colour, g), row) in enumerate(zip(parts, rows)):
            runs = stretches(row, min_run) if g.is_ring else []
            if len(runs) > 1:
                longest = max(runs, key=lambda run: run[1] - run[0])
                start = (longest[0] + longest[1]) / 2
                first, rest = substring(g, start, g.length), substring(g, 0, start)
                if first.geom_type == rest.geom_type == "LineString" and first.length > 0 and rest.length > 0:
                    parts[k] = (key, colour, LineString(list(first.coords) + list(rest.coords)[1:]))
                    turned = True
        if turned:
            rows = list(slots_of(parts))
    by_slot = defaultdict(lambda: defaultdict(list))
    for fi, (_, _, g), row in zip(where, parts, rows):
        for a, b, slot in _legacy_eased(stretches(row, min_run)):
            piece = substring(g, a, b)
            if piece.geom_type == "LineString" and piece.length > 0:
                by_slot[fi][round(slot * 16) / 16].append([[round(x, 7), round(y, 7)] for x, y in piece.coords])
    out = []
    for fi, f in enumerate(features):
        if fi not in by_slot:
            out.append(f)
            continue
        for slot, lines in sorted(by_slot[fi].items(), key=lambda kv: (kv[0] != 0, kv[0])):
            props = {k: v for k, v in f["properties"].items() if k != "off"}
            if slot:
                props["off"] = slot
            out.append({**f, "properties": props, "geometry": {"type": "LineString", "coordinates": lines[0]}
                        if len(lines) == 1 else {"type": "MultiLineString", "coordinates": lines}})
    return out
