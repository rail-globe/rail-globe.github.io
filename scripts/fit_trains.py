#!/usr/bin/env python3
"""Put the routes of the train data onto the lines the map draws.

    python3 scripts/fit_trains.py            (scripts/build_trains.py runs it at its end)

The route shapes of the community timetable data are not this map's lines. Most of a shape lies on
a line within the 100 m it was simplified by, but here and there it leaves it: a few sparse points
joined by straight lines (D2728 through 天水, 1.3 km off the 宝兰 line), or a bow several hundred
metres off the line in the hills (reported 2026-10-13). There the route cannot be drawn on a line
and the train runs across open country.

A stretch of a shape that leaves the routing network (data/graph.json: the lines as drawn, within
40 m) by more than FAR, and by more than PEAK somewhere, is replaced by the path along the network
between the point where it leaves and the point where it comes back. The path is taken only when
it is about as long as the stretch and stays near it: a route is never sent round by another line.
A stretch that fails this, or that runs off the end of the shape, is left as the data has it, and
counted. The stops of every trip keep their place: outside a replaced stretch their distance along
the shape moves by what the stretch gained or lost, inside one the station is projected onto the
new path. A shape is changed only if every trip on it still passes the builder's own checks
(stops in order, no impossible speed).

Run on data already fitted it finds nothing to do.
"""
import hashlib
import heapq
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from build_trains import compact_json, cumulative_distances, encode_polyline, haversine, quantize, write_geometry_shards

ROOT = Path(__file__).resolve().parents[1]
TRACK = {"main", "branch", "hsr350", "hsr250", "hsr200", "mrail"}     # the railway lines of the routing network
STEP = 100.0            # metres: how often a shape is measured against the network
FAR = 150.0             # metres: further than this from every line, the shape has left the network
PEAK = 300.0            # metres: a stretch is replaced only if it gets this far away somewhere
REACH = 200.0           # metres: the lines this close to where a stretch leaves and comes back are tried
LONGER = (1.5, 1000.0)  # a path may be this many times the stretch, plus this many metres
SHORTER = (0.5, 500.0)  # and no shorter than this share of it, less this many metres
ASIDE = (2.5, 1000.0)   # the path stays within this many times the stretch's own distance from the network, or this many metres
SHARD_BYTES = 2_800_000
R = 6378137.0


def mercator(lon, lat):
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def decode_polyline(text):
    out, i, lat, lon = [], 0, 0, 0
    while i < len(text):
        for which in (0, 1):
            shift = value = 0
            while True:
                b = ord(text[i]) - 63
                i += 1
                value |= (b & 31) << shift
                shift += 5
                if b < 32:
                    break
            delta = ~(value >> 1) if value & 1 else value >> 1
            if which == 0:
                lat += delta
            else:
                lon += delta
        out.append((lon / 1e5, lat / 1e5))
    return out


class Network:
    """The railway lines of the routing network: edges with their geometry, and what meets at each node."""

    def __init__(self, graph):
        nodes, flat, shapes = graph["nodes"], graph["edges"], graph["shapes"]
        self.edges, self.at = [], defaultdict(list)
        k = 0
        for i in range(len(flat) // 5):
            u, v, line, metres, count = flat[i * 5:i * 5 + 5]
            x, y = nodes[u * 2], nodes[u * 2 + 1]
            co = [(x / 1e5, y / 1e5)]
            for j in range(k, k + count):
                x += shapes[j * 2]
                y += shapes[j * 2 + 1]
                co.append((x / 1e5, y / 1e5))
            k += count
            co.append((nodes[v * 2] / 1e5, nodes[v * 2 + 1] / 1e5))
            if graph["lines"][line][1] not in TRACK or u == v:
                continue
            co = [p for n, p in enumerate(co) if not n or p != co[n - 1]]
            if len(co) < 2:
                continue
            e = len(self.edges)
            self.edges.append((u, v, co, cumulative_distances(co)))
            self.at[u].append((e, v))
            self.at[v].append((e, u))
        self.flat = [LineString([mercator(*p) for p in co]) for _, _, co, _ in self.edges]
        self.tree = STRtree(self.flat)

    def away(self, points):
        """Metres from each (lon, lat) to the nearest line."""
        if not len(points):
            return np.zeros(0)
        xy = np.asarray([mercator(*p) for p in points])
        _, dist = self.tree.query_nearest(shapely.points(xy), return_distance=True, all_matches=False)
        return np.asarray(dist) * np.cos(np.radians(np.asarray(points)[:, 1]))

    def near(self, point, reach=REACH):
        """The lines within reach of a point: [(edge, metres along it, metres aside)]."""
        cos = math.cos(math.radians(point[1]))
        here = Point(mercator(*point))
        out = []
        for e in self.tree.query(here, predicate="dwithin", distance=reach / cos):
            e = int(e)
            g, (_, _, co, along) = self.flat[e], self.edges[e]
            out.append((e, g.project(here) / g.length * along[-1] if g.length else 0.0, g.distance(here) * cos))
        return out

    def piece(self, e, a, b):
        """The geometry of an edge from a metres along it to b metres along it (b < a: backwards)."""
        _, _, co, along = self.edges[e]
        lo, hi = min(a, b), max(a, b)

        def at(d):
            k = min(max(int(np.searchsorted(along, d, side="right")) - 1, 0), len(co) - 2)
            t = (d - along[k]) / (along[k + 1] - along[k]) if along[k + 1] > along[k] else 0.0
            return (co[k][0] + (co[k + 1][0] - co[k][0]) * t, co[k][1] + (co[k + 1][1] - co[k][1]) * t)
        out = [at(lo)] + [p for p, d in zip(co, along) if lo < d < hi] + [at(hi)]
        return out if a <= b else out[::-1]

    def path(self, start, end, budget):
        """The shortest way along the lines from one of the places in start to one in end (each
        (edge, metres along it, metres aside)), no longer than budget: (metres, coordinates) or None.
        Being aside counts against a place, so that the line a stretch is on is preferred to one
        that only runs near."""
        best = None
        for e, a, off_a in start:                       # leaves and comes back on one edge
            for f, b, off_b in end:
                if e == f:
                    cost = abs(b - a) + 3 * (off_a + off_b)
                    if best is None or cost < best[0]:
                        best = (cost, abs(b - a), self.piece(e, a, b))
        dist, came, heap = {}, {}, []
        for e, a, off in start:
            u, v, _, along = self.edges[e]
            for node, d in ((u, a), (v, along[-1] - a)):
                cost = d + 3 * off
                if cost < dist.get(node, math.inf):
                    dist[node], came[node] = cost, ("start", e, a)
                    heapq.heappush(heap, (cost, node))
        goals = defaultdict(list)
        for f, b, off in end:
            u, v, _, along = self.edges[f]
            goals[u].append((b + 3 * off, f, b))
            goals[v].append((along[-1] - b + 3 * off, f, b))
        limit = budget + 3 * 2 * REACH
        done, found = set(), None
        while heap:
            cost, node = heapq.heappop(heap)
            if node in done or cost > limit:
                continue
            if found is not None and cost >= found[0]:
                break
            done.add(node)
            for extra, f, b in goals.get(node, ()):
                if found is None or cost + extra < found[0]:
                    found = (cost + extra, node, f, b)
            for e, other in self.at[node]:
                step = cost + self.edges[e][3][-1]
                if step < dist.get(other, math.inf) and step <= limit:
                    dist[other], came[other] = step, ("edge", e, node)
                    heapq.heappush(heap, (step, other))
        if found is not None and (best is None or found[0] < best[0]):
            _, node, f, b = found
            u, v, _, along = self.edges[f]
            tail = self.piece(f, 0.0 if node == u else along[-1], b)
            chain = []
            while True:
                kind, e, where = came[node]
                eu, ev, _, ealong = self.edges[e]
                if kind == "start":
                    chain.append(self.piece(e, where, 0.0 if node == eu else ealong[-1]))
                    break
                chain.append(self.piece(e, 0.0 if where == eu else ealong[-1], 0.0 if node == eu else ealong[-1]))
                node = where
            co = []
            for part in chain[::-1] + [tail]:
                co += part if not co else part[1:]
            best = (found[0], cumulative_distances(co)[-1], co)
        if best is None or best[1] > budget:
            return None
        return best[1], best[2]


def sampled(points, along, step=STEP):
    """Points every `step` metres along a shape, with every vertex: [(metres along, lon, lat)]."""
    out = []
    for k in range(len(points) - 1):
        a, b, d0, d1 = points[k], points[k + 1], along[k], along[k + 1]
        n = max(1, int(math.ceil((d1 - d0) / step)))
        out += [(d0 + (d1 - d0) * i / n, a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n)]
    out.append((along[-1], points[-1][0], points[-1][1]))
    return out


def fit(points, network):
    """A shape on the network. Returns (new points, marks, notes): marks are (metres along the old
    shape, index of the same point in the new one) for every point kept; notes count what was
    done. With nothing to do the points come back as they are."""
    along = cumulative_distances(points)
    samples = sampled(points, along)
    away = network.away([(x, y) for _, x, y in samples])
    notes, cuts, k, n = Counter(), [], 0, len(samples)
    while k < n:
        if away[k] <= FAR:
            k += 1
            continue
        j = k
        while j + 1 < n and away[j + 1] > FAR:
            j += 1
        peak = float(away[k:j + 1].max())
        if peak > PEAK:
            if k == 0 or j == n - 1:
                notes["runs off the end of the shape"] += 1
            else:
                a, b = samples[k - 1], samples[j + 1]
                length = b[0] - a[0]
                found = network.path(network.near(a[1:]), network.near(b[1:]), LONGER[0] * length + LONGER[1])
                reason = None
                if found is None:
                    reason = "no way along the lines"
                elif found[0] < SHORTER[0] * length - SHORTER[1]:
                    reason = "the way along the lines is much shorter"
                else:
                    old = LineString([mercator(x, y) for _, x, y in samples[k - 1:j + 2]])
                    cos = math.cos(math.radians(a[2]))
                    aside = max(old.distance(Point(mercator(*p))) for _, x, y in sampled(found[1], cumulative_distances(found[1]))
                                for p in [(x, y)]) * cos
                    if aside > max(ASIDE[0] * peak, ASIDE[1]):
                        reason = "the way along the lines runs elsewhere"
                if reason:
                    notes[reason] += 1
                else:
                    cuts.append((a, b, found[1]))
                    notes["replaced"] += 1
                    notes["metres replaced"] += length
        k = j + 1
    if not cuts:
        return points, [(d, i) for i, d in enumerate(along)], notes
    out, marks, at = [], [], 0          # at: the next old vertex to copy

    def add(p, old=None):
        q = (math.floor(p[0] * 1e5 + 0.5) / 1e5, math.floor(p[1] * 1e5 + 0.5) / 1e5)
        if not out or q != out[-1]:
            out.append(q)
        if old is not None:
            marks.append((old, len(out) - 1))
    for a, b, way in cuts:
        while at < len(points) and along[at] <= a[0]:
            add(points[at], along[at])
            at += 1
        add(a[1:], a[0])
        for p in way:
            add(p)
        add(b[1:], b[0])
        while at < len(points) and along[at] < b[0]:
            at += 1
    while at < len(points):
        add(points[at], along[at])
        at += 1
    return out, marks, notes


def moved(distances, coordinates, old_points, new_points, marks):
    """The distances of a trip's stops along the new shape. Between two points kept next to each
    other the distance moves with them; where a stretch was replaced the station is projected
    onto the new path."""
    new_along = cumulative_distances(new_points)
    old_at = [m[0] for m in marks]
    out = []
    for d, station in zip(distances, coordinates):
        k = min(max(int(np.searchsorted(old_at, d, side="right")) - 1, 0), len(marks) - 2)
        (d0, i0), (d1, i1) = marks[k], marks[k + 1]
        if i1 - i0 <= 1:                     # the same segment as before
            t = (d - d0) / (d1 - d0) if d1 > d0 else 0.0
            out.append(new_along[i0] + (new_along[i1] - new_along[i0]) * min(max(t, 0.0), 1.0))
            continue
        cos = math.cos(math.radians(station[1]))
        here, best = (station[0] * cos, station[1]), None
        for i in range(i0, i1):
            ax, ay, bx, by = new_points[i][0] * cos, new_points[i][1], new_points[i + 1][0] * cos, new_points[i + 1][1]
            span = (bx - ax) ** 2 + (by - ay) ** 2
            t = min(max(((here[0] - ax) * (bx - ax) + (here[1] - ay) * (by - ay)) / span, 0.0), 1.0) if span else 0.0
            gap = math.hypot(ax + (bx - ax) * t - here[0], ay + (by - ay) * t - here[1])
            if best is None or gap < best[0]:
                best = (gap, new_along[i] + (new_along[i + 1] - new_along[i]) * t)
        out.append(best[1])
    return out


def in_order(distances, coordinates, times, top_kmh, length):
    """The builder's own checks on a trip: stops in order and apart, on the shape, at a possible speed."""
    if distances[0] < -0.5 or distances[-1] > length + 0.5:
        return False
    for i in range(1, len(distances)):
        if distances[i] - distances[i - 1] < max(0.01, min(100.0, haversine(coordinates[i - 1], coordinates[i]) * 0.1)):
            return False
        seconds = times[i][0] - times[i - 1][1]
        if seconds <= 0 or (distances[i] - distances[i - 1]) / seconds * 3.6 > top_kmh:
            return False
    return True


def fit_data(index, shapes, network, top_kmh):
    """Fit every shape in use. Changes index and shapes in place; returns the notes."""
    stops = index["stops"]
    by_shape = defaultdict(list)
    for trip in index["trips"]:
        if trip.get("renderable") and trip.get("shapeId"):
            by_shape[trip["shapeId"]].append(trip)
    notes, fitted = Counter(), {}
    for sid in sorted(by_shape):
        points = decode_polyline(shapes[sid]["p"])
        new, marks, found = fit(points, network)
        for key, value in found.items():
            if key not in ("replaced", "metres replaced"):
                notes["stretches left: " + key] += value
        if not found["replaced"]:
            fitted[sid] = (sid, shapes[sid], None)
            continue
        length = cumulative_distances(new)[-1]
        rows = []
        for trip in by_shape[sid]:
            coordinates = [(stops[s[0]]["lon"], stops[s[0]]["lat"]) for s in trip["stops"]]
            distances = moved([s[3] for s in trip["stops"]], coordinates, points, new, marks)
            if not in_order(distances, coordinates, [(s[1], s[2]) for s in trip["stops"]], top_kmh, length):
                rows = None
                break
            rows.append(distances)
        if rows is None:
            notes["shapes left: a trip's stops would not stay in order"] += 1
            notes["stretches left: a trip's stops would not stay in order"] += found["replaced"]
            fitted[sid] = (sid, shapes[sid], None)
            continue
        polyline = encode_polyline(new)
        new_id = "s" + hashlib.sha256(polyline.encode()).hexdigest()[:16]
        fitted[sid] = (new_id, {"p": polyline, "bbox": [min(p[0] for p in new), min(p[1] for p in new),
                                                         max(p[0] for p in new), max(p[1] for p in new)]}, rows)
        notes["shapes changed"] += 1
        notes["trips on them"] += len(by_shape[sid])
        notes["stretches replaced"] += found["replaced"]
        notes["km replaced"] += found["metres replaced"] / 1000
    shapes.clear()
    for sid, (new_id, shape, rows) in fitted.items():
        shapes[new_id] = shape
        for n, trip in enumerate(by_shape[sid]):
            trip["shapeId"] = new_id
            if rows is not None:
                for stop, distance in zip(trip["stops"], rows[n]):
                    stop[3] = round(distance, 1)
    return {key: (round(value, 1) if isinstance(value, float) else value) for key, value in sorted(notes.items())}


def main(folder=ROOT / "data" / "trains", graph_path=ROOT / "data" / "graph.json"):
    folder = Path(folder)
    index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    shapes = {}
    for name in sorted(set(index["shapeFiles"].values())):
        shapes.update(json.loads((folder / name).read_text(encoding="utf-8")))
    network = Network(json.loads(Path(graph_path).read_text(encoding="utf-8")))
    quality = json.loads((folder / "quality.json").read_text(encoding="utf-8"))
    notes = fit_data(index, shapes, network, quality["meta"]["qualityThresholds"]["maxSegmentSpeedKmh"])
    print("train routes on the map's lines:", json.dumps(notes, ensure_ascii=False), flush=True)
    if not notes.get("shapes changed"):
        return notes
    index["shapeFiles"] = write_geometry_shards(shapes, folder, SHARD_BYTES)
    said = "偏离本图线路 150 米以上的区段改为沿本图线路的路径，停站里程随之重算"
    for meta in (index["meta"], quality["meta"]):
        meta["fittedToMapLines"] = notes
        if said not in meta["license"]["changes"]:
            meta["license"]["changes"] += "；" + said
        meta["quality"]["publishedShapes"] = len(shapes)
        meta["quality"]["geometryShards"] = len(set(index["shapeFiles"].values()))
        meta["quality"]["geometryBytes"] = sum((folder / name).stat().st_size for name in set(index["shapeFiles"].values()))
    (folder / "index.json").write_text(compact_json(index), encoding="utf-8")
    quality["indexBytes"] = (folder / "index.json").stat().st_size
    (folder / "quality.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    return notes


if __name__ == "__main__":
    main(*sys.argv[1:3])
