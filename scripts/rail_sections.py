"""Select a physical line before splitting its display by source speed evidence.

Only collinear source edges containing both display endpoints may supply tags.
The numerical allowance is 64 coordinate ULPs, never a nearby parallel track.
Synthetic stitch links remain unclassified and carry no source speed claim.
"""
import math
from collections import defaultdict

from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from process_jp import runs_of
from single_track import join_up, one_track, stitch


def adopt_track_gaps(line_of, unnamed, ways):
    """Name only an unbranched gap bounded at both ends by the same named line.

    An entire unnamed connected railway network is never named by a vote at its
    junctions. Split it into chains at junctions and existing named boundaries.
    Dead ends and chains between different or ambiguous identities stay unnamed.
    """
    at, named = defaultdict(list), defaultdict(set)
    for wid in unnamed:
        for end in (ways[wid][1][0], ways[wid][1][-1]):
            at[end].append(wid)
    for wid, key in line_of.items():
        for end in (ways[wid][1][0], ways[wid][1][-1]):
            named[end].add(key)
    stops = {end for end, wids in at.items() if len(wids) != 2 or named[end]}
    pending = set(unnamed)
    seeds = sorted((wid, end) for end in stops for wid in at[end])
    seeds += [(wid, ways[wid][1][0]) for wid in sorted(unnamed)]
    for wid, start in seeds:
        if wid not in pending:
            continue
        chain, current, end = [], wid, start
        while current in pending:
            pending.remove(current)
            chain.append(current)
            a, b = ways[current][1][0], ways[current][1][-1]
            end = b if end == a else a
            if end in stops:
                break
            current = next((w for w in at[end] if w in pending), None)
        if (start != end and len(named[start]) == 1
                and named[start] == named[end]):
            key = next(iter(named[start]))
            for part in chain:
                line_of[part] = key
    return [wid for wid in unnamed if wid not in line_of]


def source_sections(paths, wids, ways, line_of):
    edges, owners = [], []
    for wid in sorted(wids):
        coords = ways[wid][1]
        for a, b in zip(coords, coords[1:]):
            if a != b:
                edges.append(LineString([a, b]))
                owners.append(wid)
    if not edges:
        return {}, {}
    allowance = 64 * max(math.ulp(v) for edge in edges for pt in edge.coords for v in pt)
    tree = STRtree(edges)
    pieces, sources = defaultdict(list), defaultdict(set)
    for path in paths:
        coords = list(path.coords)
        active, chain = None, []
        for a, b in zip(coords, coords[1:]):
            if a == b:
                continue
            segment = LineString([a, b])
            candidates = []
            for index in tree.query(segment, predicate="dwithin", distance=allowance):
                edge = edges[int(index)]
                if edge.distance(Point(a)) <= allowance and edge.distance(Point(b)) <= allowance:
                    candidates.append(owners[int(index)])
            wid = min(candidates) if candidates else None
            key = line_of[wid] if wid is not None else None
            if not chain or key != active or chain[-1] != a:
                if chain:
                    pieces[active].append(LineString(chain))
                chain = [a]
            chain.append(b)
            active = key
            if wid is not None:
                sources[key].add(wid)
        if chain:
            pieces[active].append(LineString(chain))
    return dict(pieces), dict(sources)


def prune_parallel_stubs(paths, gap=0.0018, limit=0.03, step=0.0002):
    """Discard only short paths that remain parallel to a longer selected path.

    Station approaches can end on separate platform tracks and therefore look
    topologically like branches. They are duplicate directions when every
    sample remains in the corridor and follows it; a real branch that turns
    away or leaves the corridor is retained.
    """
    if len(paths) < 2:
        return paths
    kept = []
    for path in sorted(paths, key=lambda geom: -geom.length):
        if path.length > limit or not kept:
            kept.append(path)
            continue
        tree = STRtree(kept)
        samples = max(3, math.ceil(path.length / step) + 1)
        duplicate = True
        for index in range(samples):
            at = path.length * index / (samples - 1)
            point = path.interpolate(at)
            nearby = tree.query(point, predicate="dwithin", distance=gap)
            if len(nearby) == 0:
                duplicate = False
                break
            target = min((kept[int(j)] for j in nearby), key=lambda geom: geom.distance(point))
            on = target.project(point)
            delta = min(step, path.length / 4, target.length / 4)
            a, b = path.interpolate(max(0, at - delta)), path.interpolate(min(path.length, at + delta))
            c, d = target.interpolate(max(0, on - delta)), target.interpolate(min(target.length, on + delta))
            u, v = (b.x - a.x, b.y - a.y), (d.x - c.x, d.y - c.y)
            norm = math.hypot(*u) * math.hypot(*v)
            if not norm or abs(u[0] * v[0] + u[1] * v[1]) / norm < 0.8:
                duplicate = False
                break
        if not duplicate:
            kept.append(path)
    return kept


def draw_sections(tracks, ways, line_of):
    """{evidence key: [source runs, selected pieces]}, selected way IDs, junction count."""
    groups = defaultdict(list)
    for key, wids in tracks.items():
        # Unnamed component identities are separate from their evidence suffix.
        identity = key[2] or key[1].split(":osm:", 1)[0]
        groups[identity].extend(wids)
    physical = {}
    for identity, wids in sorted(groups.items()):
        runs = runs_of([ways[w][1] for w in sorted(wids)])
        # A regular railway can have its two directions in separate tubes or
        # spread through a station. The old 0.0006-degree corridor classified
        # the 60–100 m separation of the Guadarrama tubes as a long branch.
        # This wider corridor is only within the already assigned identity;
        # preserved/park railways retain their original tighter selection.
        regular = any(ways[w][0].get("railway") in ("rail", "narrow_gauge")
                      and ways[w][0].get("usage") != "tourism" for w in wids)
        gap = 0.0012 if regular else 0.0006
        physical[identity] = [runs, one_track(runs, gap=gap, keep=0.05, apart=0.004, apart_min=0.01)]
    closed = join_up(list(physical.values()))
    once, chosen, selected = {}, {}, {}
    for identity, (runs, drawn) in physical.items():
        paths = stitch(runs_of([list(g.coords) for g in drawn]))
        # Junction restoration can follow the discarded direction of this very
        # line for kilometres. Stitching can also reveal a folded run that was
        # split among short source ways at the first selection. Collapse those
        # restored paths before cutting them by evidence, so speed differences
        # never bring the two directions back as separately drawn lines.
        regular = any(ways[w][0].get("railway") in ("rail", "narrow_gauge")
                      and ways[w][0].get("usage") != "tourism" for w in groups[identity])
        gap = 0.0012 if regular else 0.0006
        paths = stitch(one_track(paths, gap=gap, keep=0.05,
                                 apart=0.004, apart_min=0.01))
        selected[identity] = prune_parallel_stubs(paths) if regular else paths
    for identity, paths in selected.items():
        runs = physical[identity][0]
        pieces, sources = source_sections(paths, groups[identity], ways, line_of)
        for key, geometry in pieces.items():
            if key is None:
                name = line_of[groups[identity][0]][2]
                key = ("rail", "display_join:" + identity, name)
                sources[key] = set()
            once[key] = [runs, geometry]
            chosen[key] = sources[key]
    return once, chosen, closed
