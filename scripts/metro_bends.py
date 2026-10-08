"""Display repairs backed by the line's own track, with a separate verified refit.

This runs before interpolation. It removes erroneous local detours by restoring
source geometry, rather than hiding them by subdividing the same detour.
"""
import math
import json
import heapq
from collections import defaultdict
from pathlib import Path

import numpy as np
from shapely.affinity import scale
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, substring

from check_bends import scan


def projected(g, latitude):
    return scale(g, xfact=111320 * math.cos(math.radians(latitude)), yfact=110574, origin=(0, 0))


def geographic(g, latitude, original=None):
    out = scale(g, xfact=1 / (111320 * math.cos(math.radians(latitude))), yfact=1 / 110574, origin=(0, 0))
    if original is not None:
        kept = dict(zip(projected(original, latitude).coords, original.coords))
        return LineString([kept.get(p, q) for p,q in zip(g.coords, out.coords)])
    return out


def peak(g, latitude):
    return max((abs(r['turn_degrees']) for r in scan(geographic(g, latitude).coords, limit=0)), default=0)


def replace(g, a, b, replacement):
    before, after = substring(g, 0, a), substring(g, b, g.length)
    co = list(before.coords) + list(replacement.coords) + list(after.coords)
    return LineString([p for i, p in enumerate(co) if not i or p != co[i - 1]])


def junctions(tracks):
    """Actual source track junctions, not arbitrary display cut/terminus points."""
    neighbours = {}
    for co in tracks:
        for a,b in zip(co,co[1:]):
            a,b=tuple(a),tuple(b)
            if a!=b:
                neighbours.setdefault(a,set()).add(b)
                neighbours.setdefault(b,set()).add(a)
    return [p for p,adjacent in neighbours.items() if len(adjacent)>2]


def network_path(start, end, tracks, reach=45, limit=1400):
    """Shortest source path with either parallel track available at both ends.

    Picking only the nearest track independently at each end can force a
    crossover and a turnback. Project onto every nearby source way, and let
    connectivity and path length choose a consistent track instead.
    """
    box = LineString([start, end]).buffer(limit / 2).envelope
    local = [g for g in tracks if g.intersects(box)]
    adjacent = defaultdict(dict)
    tips = [dict(), dict()]
    for g in local:
        co = list(g.coords)
        at = np.r_[0, np.cumsum(np.linalg.norm(np.diff(np.asarray(co), axis=0), axis=1))]
        points = list(zip(at, co))
        for i, p in enumerate((start, end)):
            if g.distance(p) > reach:
                continue
            d = g.project(p)
            # Preserve an existing source node exactly when the projection lands on it.
            k = int(np.argmin(abs(at - d)))
            q = co[k] if abs(at[k] - d) < 1e-6 else g.interpolate(d).coords[0]
            tips[i][q] = min(tips[i].get(q, float('inf')), Point(q).distance(p))
            points.append((d, q))
        points.sort(key=lambda pair: pair[0])
        for (_, a), (_, b) in zip(points, points[1:]):
            if a == b:
                continue
            length = math.dist(a, b)
            adjacent[a][b] = adjacent[b][a] = length
    if not all(tips):
        return None
    distance, previous = dict(tips[0]), {}
    heap = [(d, p) for p, d in distance.items()]
    heapq.heapify(heap)
    best = None
    while heap:
        d, p = heapq.heappop(heap)
        if d != distance[p]:
            continue
        if d > limit or (best and d > best[0]):
            break
        if p in tips[1] and (best is None or d + tips[1][p] < best[0]):
            best = (d + tips[1][p], p)
        for q, length in adjacent[p].items():
            if d + length < distance.get(q, float('inf')):
                distance[q], previous[q] = d + length, p
                heapq.heappush(heap, (d + length, q))
    if best is None or best[0] > limit:
        return None
    path = [best[1]]
    while path[-1] in previous:
        path.append(previous[path[-1]])
    return LineString(path[::-1]) if len(path) > 1 else None


def restore(parts, tracks, protected=()):
    """Restore a local detour only when an existing source run is clearly smoother.

    Both boundaries must lie within 45 m of the same source run (metro tracks can
    be 15 to 40 m apart). The replacement
    may deviate by at most 75 m from the drawing, must remove at least 25 m of
    detour or halve the bend, and may not cross a retained branch connection.
    Ordinary source curves, including tight tram curves, cannot qualify merely
    because they are tight: the candidate must already exist in the source.
    """
    if not tracks:
        return parts, []
    joined = linemerge(MultiLineString(tracks))
    source = (list(joined.geoms) if joined.geom_type == 'MultiLineString' else [joined]) + [LineString(co) for co in tracks if len(co)>1]
    out, log = [], []
    for original in parts:
        initial = len(log)
        lat = original.centroid.y
        g = projected(original, lat)
        refs = [projected(h, lat) for h in source]
        network = [projected(LineString(co), lat) for co in tracks if len(co)>1]
        ports = [projected(Point(p), lat) for p in protected]
        for _ in range(8):
            rows = sorted(scan(geographic(g, lat).coords), key=lambda r: -abs(r['turn_degrees']))
            changed = False
            for row in rows:
                d = g.project(projected(Point(row['at']), lat))
                choices = []
                for margin in (180, 300, 500):
                    a, b = max(0, d - margin), min(g.length, d + margin)
                    junctions = [p for p in ports if a+1 < g.project(p) < b-1 and p.distance(g)<2]
                    old = substring(g, a, b)
                    if old.is_closed:
                        continue               # never replace a whole circular route by its chord
                    start, end = old.boundary.geoms
                    candidates = refs
                    if abs(row['turn_degrees']) > 70 and row['reverse_bend'] and a>25 and b<g.length-25:
                        # A station throat can split every source run at its points.
                        # Follow the actual track network instead of requiring one
                        # unsplit OSM way to cover both patch boundaries.
                        path = network_path(start, end, network)
                        candidates = refs + ([path] if path is not None else [])
                    for ref in candidates:
                        if max(ref.distance(start), ref.distance(end)) > 45:
                            continue
                        x, y = ref.project(start), ref.project(end)
                        h = substring(ref, x, y)
                        if h.geom_type != 'LineString' or h.length < 30:
                            continue
                        # Taper the small track-to-track displacement at the boundaries.
                        h = h.segmentize(20)
                        co = np.asarray(h.coords)
                        at = np.r_[0, np.cumsum(np.linalg.norm(np.diff(co, axis=0), axis=1))]
                        co += np.maximum(0, 1 - at / 150)[:, None] * (np.asarray(start.coords[0]) - co[0])
                        co += np.maximum(0, 1 - (at[-1] - at) / 150)[:, None] * (np.asarray(end.coords[0]) - co[-1])
                        co[0], co[-1] = start.coords[0], end.coords[0]
                        h = LineString(co)
                        if any(h.distance(p)>2 for p in junctions):
                            continue
                        # A replacement that follows the same junction may qualify,
                        # but the branch vertex itself must survive exactly.
                        positions = [(h.project(Point(p)),p) for p in h.coords]
                        positions += [(h.project(p),p.coords[0]) for p in junctions]
                        positions.sort(key=lambda t:t[0])
                        co=[p for _,p in positions]
                        h=LineString([p for i,p in enumerate(co) if not i or p!=co[i-1]])
                        new_peak = peak(h, lat)
                        saving = old.length - h.length
                        if h.hausdorff_distance(old) <= 75 and new_peak < abs(row['turn_degrees']) * .55 and (saving > 25 or new_peak < 15):
                            updated = replace(g, a, b, h)
                            check = substring(updated, max(0, a-25), min(updated.length, a+h.length+25))
                            if peak(check, lat) < abs(row['turn_degrees']) * .55:
                                choices.append((b-a, new_peak, h.length, h, a, b, old, updated))
                if choices:
                    _, _, _, h, a, b, old, updated = min(choices, key=lambda t: t[:3])
                    g = updated
                    log.append({'kind': 'source_restore', 'at': row['at'], 'before_degrees': row['turn_degrees'],
                                'after_degrees': round(peak(h, lat), 2), 'removed_m': round(old.length - h.length, 1)})
                    changed = True
                    break
            if not changed:
                break
        out.append(geographic(g, lat, original) if len(log) > initial else original)
    return out, log


def refit(g, centre, radius=350, maximum=45, margins=(150, 200, 250, 300, 350, 400, 500), protected=(), anchors=()):
    """Replace a verified bad sample by a tangent-continuous local cubic.

    The endpoint positions and headings are retained. Choose the smallest source
    deviation that satisfies the cited radius. Return None if the bounds cannot
    be met; never silently relax them. No source/routing data are edited.
    """
    lat = g.centroid.y
    line, point = projected(g, lat), projected(Point(centre), lat)
    if point.distance(line) > 60:
        return None
    d = line.project(point)
    choices = []
    ports = [projected(Point(p), lat) for p in protected]
    stations = [line.interpolate(line.project(projected(Point(p), lat))) for p in anchors
                if projected(Point(p), lat).distance(line)<50]
    for left, right in ((a,b) for a in margins for b in margins):
        a, b = d - left, d + right
        if a < 6 or b > line.length - 6:
            continue
        if any(a+1 < line.project(p) < b-1 and p.distance(line)<2 for p in ports):
            continue
        p, q = np.array(line.interpolate(a).coords[0]), np.array(line.interpolate(b).coords[0])
        u = np.array(line.interpolate(a+2).coords[0]) - np.array(line.interpolate(a-2).coords[0])
        v = np.array(line.interpolate(b+2).coords[0]) - np.array(line.interpolate(b-2).coords[0])
        u, v = u / np.linalg.norm(u), v / np.linalg.norm(v)
        span = np.linalg.norm(q - p)
        old = substring(line, a, b)
        t = np.linspace(0, 1, 201)[:, None]
        for first in (.25, .3, 1/3, .4, .45):
            for last in (.25, .3, 1/3, .4, .45):
                c, e = p + u * span * first, q - v * span * last
                co = (1-t)**3*p + 3*(1-t)**2*t*c + 3*(1-t)*t*t*e + t**3*q
                velocity = 3*(1-t)**2*(c-p) + 6*(1-t)*t*(e-c) + 3*t*t*(q-e)
                acceleration = 6*(1-t)*(e-2*c+p) + 6*t*(q-2*e+c)
                cross = abs(velocity[:, 0]*acceleration[:, 1] - velocity[:, 1]*acceleration[:, 0])
                minimum = float(np.min(np.linalg.norm(velocity, axis=1)**3 / np.maximum(cross, 1e-9)))
                if minimum < radius:
                    continue
                candidate = LineString(co)
                off = candidate.hausdorff_distance(old)
                stays = all(candidate.distance(p) <= 1 for p in stations if a <= line.project(p) <= b)
                if off <= maximum and stays:
                    # Retain the cubic to <= 0.1 m, not all 201 trial samples.
                    choices.append((b-a, off, candidate.simplify(.1), a, b, minimum))
    if not choices:
        return None
    span, off, candidate, a, b, minimum = min(choices, key=lambda x: x[:2])
    return geographic(replace(line, a, b, candidate), lat, g), {
        'kind': 'verified_refit', 'at': list(centre), 'span_m': round(span, 1),
        'maximum_shift_m': round(off, 1), 'minimum_cubic_radius_m': round(minimum, 1)}


def repair(parts, tracks, name, protected=(), anchors=(), rules=None):
    parts, report = restore(parts, tracks, protected)
    if rules is None:
        rules = json.loads((Path(__file__).resolve().parents[1] / 'data' / 'metro_geometry_overrides.json').read_text())
    for rule in rules:
        if rule['line'] != name:
            continue
        for i, g in enumerate(parts):
            fixed = refit(g, rule['at'], radius=rule['minimum_radius_m'], maximum=rule['maximum_shift_m'],
                          protected=protected, anchors=anchors)
            if fixed:
                parts[i], record = fixed
                record.update(source=rule['source'], checked=rule['checked'])
                report.append(record)
    for record in report:
        record['line'] = name
    return parts, report


def trim_unowned_loop(co, stations, minimum=500):
    """An unowned tail that returns to its attachment without any station is
    not a passenger branch. Keep its approach, not the terminal balloon.
    Call only for extra track outside route relations. Small turning loops and
    any loop with a station are left for the ordinary topology pass/review.
    """
    co = list(map(tuple, co))
    for reverse in (False, True):
        run = co[::-1] if reverse else co
        for i in range(1,len(run)-2):
            if run[i] != run[-1]:
                continue
            loop = LineString(run[i:]); lat=loop.centroid.y
            metric=projected(loop,lat)
            if metric.length < minimum or any(metric.distance(projected(Point(p),lat)) < 65 for p in stations):
                continue
            kept=run[:i+1]
            return (kept[::-1] if reverse else kept), {'at':list(run[i]), 'removed_m':round(metric.length,1)}
    return co, None
