#!/usr/bin/env python3
"""Compile Chinese Railway GTFS into a small, auditable static train dataset.

Usage (Python 3.10+, no third-party dependencies):
    python scripts/build_trains.py --gtfs /path/to/output_gtfs.zip --release TAG
    python scripts/build_trains.py --download

This is a timetable visualisation, not a vehicle-position feed. The public
community GTFS snapshot provides operating dates, station times and route
shapes; nothing here requests live positions or scrapes 12306. Missing and
untrustworthy routes are never replaced by station-to-station straight lines.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
from typing import Iterable
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "wensimehrp/chinese-railway-gtfs"
SOURCE_URL = f"https://github.com/{REPOSITORY}"
EARTH_RADIUS_M = 6_371_000.0  # Must match src/train-core.mjs.
EXCLUDED_FOREIGN_STOP_IDS = frozenset({"VJM", "VOM", "YTM"})
EXCLUDED_FOREIGN_NAMES = frozenset({"琅勃拉邦", "万荣", "万象"})
TIME_RE = re.compile(r"^(\d{1,3}):([0-5]\d):([0-5]\d)$")


def compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def rows(archive: zipfile.ZipFile, name: str) -> Iterable[dict[str, str]]:
    """Accept the normal GTFS root or one enclosing directory."""
    matches = [n for n in archive.namelist() if n.rsplit("/", 1)[-1] == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {name}; found {len(matches)}")
    with archive.open(matches[0]) as stream:
        yield from csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig"))


def has_table(archive: zipfile.ZipFile, name: str) -> bool:
    return any(n.rsplit("/", 1)[-1] == name for n in archive.namelist())


def parse_time(value: str) -> int | None:
    m = TIME_RE.fullmatch(value or "")
    return sum(int(v) * scale for v, scale in zip(m.groups(), (3600, 60, 1))) if m else None


def parse_date(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y%m%d").date()


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = a
    lon2, lat2 = b
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    u = math.sin((phi2 - phi1) / 2) ** 2
    u += math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(max(0.0, u))))


def cumulative_distances(points: list[tuple[float, float]]) -> list[float]:
    total = [0.0]
    for a, b in zip(points, points[1:]):
        total.append(total[-1] + haversine(a, b))
    return total


def simplify(points: list[tuple[float, float]], tolerance_m: float) -> list[tuple[float, float]]:
    """Iterative Douglas-Peucker in a local metre projection; no runtime dependency.

    The same simplification is used for every trip sharing the shape. Distances
    used by the browser are subsequently measured on *quantised* polyline5
    points, never on these source points or an unrelated cartographic line.
    """
    if len(points) < 3 or tolerance_m <= 0:
        return points
    cos_lat = math.cos(math.radians(sum(p[1] for p in points) / len(points)))
    sx = EARTH_RADIUS_M * math.pi / 180 * cos_lat
    sy = EARTH_RADIUS_M * math.pi / 180
    xy = [(p[0] * sx, p[1] * sy) for p in points]
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    tolerance2 = tolerance_m * tolerance_m
    while stack:
        lo, hi = stack.pop()
        ax, ay = xy[lo]
        bx, by = xy[hi]
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        furthest, best2 = -1, tolerance2
        for j in range(lo + 1, hi):
            x, y = xy[j]
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length2)) if length2 else 0
            d2 = (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2
            if d2 > best2:
                furthest, best2 = j, d2
        if furthest >= 0:
            keep.add(furthest)
            stack.append((lo, furthest))
            stack.append((furthest, hi))
    return [points[j] for j in sorted(keep)]


def quantize(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for lon, lat in points:
        p = (math.floor(lon * 1e5 + 0.5) / 1e5, math.floor(lat * 1e5 + 0.5) / 1e5)
        if not result or p != result[-1]:
            result.append(p)
    return result


def encode_polyline(points: list[tuple[float, float]]) -> str:
    """Google polyline5 encodes LATITUDE first; decoded public points are [lon,lat]."""
    output: list[str] = []
    last_lat = last_lon = 0
    for lon, lat in points:
        current_lat, current_lon = round(lat * 1e5), round(lon * 1e5)
        for delta in (current_lat - last_lat, current_lon - last_lon):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                output.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            output.append(chr(value + 63))
        last_lat, last_lon = current_lat, current_lon
    return "".join(output)


def station_candidates(
    point: tuple[float, float],
    points: list[tuple[float, float]],
    cumulative: list[float],
    tolerance_m: float,
) -> list[tuple[float, float]]:
    """Multiple nearest projections retain loop/return-visit alternatives."""
    sx = EARTH_RADIUS_M * math.pi / 180 * math.cos(math.radians(point[1]))
    sy = EARTH_RADIUS_M * math.pi / 180
    candidates: list[tuple[float, float]] = []
    threshold2 = tolerance_m * tolerance_m
    for j, (a, b) in enumerate(zip(points, points[1:])):
        ax, ay = (a[0] - point[0]) * sx, (a[1] - point[1]) * sy
        bx, by = (b[0] - point[0]) * sx, (b[1] - point[1]) * sy
        # Cheap bounding-box rejection for almost all distant segments.
        if min(ax, bx) > tolerance_m or max(ax, bx) < -tolerance_m:
            continue
        if min(ay, by) > tolerance_m or max(ay, by) < -tolerance_m:
            continue
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        t = max(0.0, min(1.0, -(ax * dx + ay * dy) / length2)) if length2 else 0
        offset2 = (ax + t * dx) ** 2 + (ay + t * dy) ** 2
        if offset2 <= threshold2:
            distance = cumulative[j] + t * (cumulative[j + 1] - cumulative[j])
            candidates.append((distance, math.sqrt(offset2)))
    # Segment endpoints often generate duplicate projections. Keep distinct
    # distances on the line, including repeated visits to the same coordinates.
    unique: list[tuple[float, float]] = []
    for candidate in sorted(candidates, key=lambda p: p[1]):
        if all(abs(candidate[0] - old[0]) >= 30 for old in unique):
            unique.append(candidate)
            if len(unique) == 40:
                break
    return sorted(unique)


def project_stations(
    coordinates: list[tuple[float, float]],
    points: list[tuple[float, float]],
    tolerance_m: float,
) -> tuple[list[float] | None, float, str | None]:
    """Find a monotone sequence of close projections, or explicitly reject it.

    A dynamic program handles routes revisiting a station. It cannot fabricate
    a connection: every selected position lies on the supplied route and is
    within the stop-offset bound. Reverse direction is tried by the caller.
    """
    cumulative = cumulative_distances(points)
    candidates = [station_candidates(p, points, cumulative, tolerance_m) for p in coordinates]
    if any(not options for options in candidates):
        return None, math.inf, "station_too_far_from_route"
    states = [(offset * offset, [distance], offset) for distance, offset in candidates[0]]
    for i in range(1, len(candidates)):
        next_states = []
        # Distinct stations cannot collapse to the same route position.
        separation = min(100.0, haversine(coordinates[i - 1], coordinates[i]) * 0.1)
        for distance, offset in candidates[i]:
            best = None
            for cost, history, max_offset in states:
                if distance - history[-1] < max(0.01, separation):
                    continue
                candidate = (cost + offset * offset, history + [distance], max(max_offset, offset))
                if best is None or candidate[0] < best[0]:
                    best = candidate
            if best is not None:
                next_states.append(best)
        if not next_states:
            return None, math.inf, "station_order_conflicts_with_route"
        states = next_states
    cost, distances, max_offset = min(states, key=lambda state: state[0])
    return distances, max_offset, None


def normalize_times(stop_rows: list[dict[str, str]]) -> tuple[list[tuple[int, int]] | None, str | None, int]:
    """Only endpoint placeholders are normalised; interior contradictions fail.

    Overnight GTFS times are already 24:xx+, so silently adding days would hide
    upstream errors. In particular an arrival of 47:53 and a departure of 24:15
    is rejected, even if a plausible inferred correction exists.
    """
    if len(stop_rows) < 2:
        return None, "fewer_than_two_stops", 0
    parsed: list[tuple[int, int]] = []
    endpoint_corrections = 0
    for i, row in enumerate(stop_rows):
        arrival = parse_time(row.get("arrival_time", ""))
        departure = parse_time(row.get("departure_time", ""))
        if i == 0:
            if departure is None:
                return None, "invalid_origin_departure", 0
            if arrival != departure:
                endpoint_corrections += 1
            arrival = departure
        elif i == len(stop_rows) - 1:
            if arrival is None:
                return None, "invalid_destination_arrival", 0
            if departure != arrival:
                endpoint_corrections += 1
            departure = arrival
        if arrival is None or departure is None:
            return None, "invalid_time", 0
        if departure < arrival:
            return None, "departure_before_arrival", 0
        if parsed and arrival <= parsed[-1][1]:
            return None, "nonpositive_interstation_travel_time", 0
        parsed.append((arrival, departure))
    if parsed[-1][0] - parsed[0][1] > 7 * 86400:
        return None, "duration_over_seven_days", 0
    return parsed, None, endpoint_corrections


def load_services(archive: zipfile.ZipFile, start: str, end: str) -> dict[str, list[str]]:
    services: dict[str, set[str]] = collections.defaultdict(set)
    if has_table(archive, "calendar.txt"):
        for row in rows(archive, "calendar.txt"):
            first = max(parse_date(start), parse_date(row["start_date"]))
            last = min(parse_date(end), parse_date(row["end_date"]))
            day = first
            week = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
            while day <= last:
                if row.get(week[day.weekday()]) == "1":
                    services[row["service_id"]].add(day.strftime("%Y%m%d"))
                day += dt.timedelta(days=1)
    if has_table(archive, "calendar_dates.txt"):
        for row in rows(archive, "calendar_dates.txt"):
            day = row["date"]
            parse_date(day)
            if not start <= day <= end:
                continue
            if row["exception_type"] == "1":
                services[row["service_id"]].add(day)
            elif row["exception_type"] == "2":
                services[row["service_id"]].discard(day)
    return {key: sorted(value) for key, value in sorted(services.items()) if value}


def download_latest(path: Path) -> tuple[str, str]:
    """One GitHub release lookup and one archive download; no ticket-site crawl."""
    api = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
    request = urllib.request.Request(api, headers={"User-Agent": "rail-globe-timetable-builder/1.0", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=45) as response:
        release = json.load(response)
    asset = next((a for a in release.get("assets", []) if a["name"] == "output_gtfs.zip"), None)
    if not asset:
        raise ValueError("Latest GitHub release has no output_gtfs.zip asset")
    asset_url = asset["browser_download_url"]
    print(f"Downloading {release['tag_name']} ({asset['size']:,} bytes)", flush=True)
    request = urllib.request.Request(asset_url, headers={"User-Agent": "rail-globe-timetable-builder/1.0"})
    with urllib.request.urlopen(request, timeout=60) as source, path.open("wb") as destination:
        shutil.copyfileobj(source, destination, length=1024 * 1024)
    if path.stat().st_size != asset["size"]:
        raise ValueError("Downloaded GTFS size does not match the release asset")
    return release["tag_name"], asset_url


def train_type(number: str) -> str:
    return number[0] if number and number[0] in "GDCZKTSY" else "other"


def write_geometry_shards(shapes: dict[str, dict], output: Path, maximum_bytes: int) -> dict[str, str]:
    shape_dir = output / "shapes"
    shape_dir.mkdir(parents=True, exist_ok=True)
    for previous in shape_dir.glob("*.json"):
        previous.unlink()
    files = {}
    batch: dict[str, dict] = {}
    size = 2
    shard = 0

    def flush() -> None:
        nonlocal batch, size, shard
        if not batch:
            return
        filename = f"shapes/{shard:02d}.json"
        content = compact_json(batch)
        if len(content.encode("utf-8")) > maximum_bytes:
            raise ValueError("Geometry shard exceeded its size limit")
        (output / filename).write_text(content, encoding="utf-8")
        for shape_id in batch:
            files[shape_id] = filename
        shard += 1
        batch, size = {}, 2

    for shape_id, shape in sorted(shapes.items()):
        item_bytes = len(compact_json(shape_id).encode()) + 1 + len(compact_json(shape).encode()) + 1
        if item_bytes + 2 > maximum_bytes:
            raise ValueError(f"One shape exceeds the shard limit: {shape_id}")
        if batch and size + item_bytes > maximum_bytes:
            flush()
        batch[shape_id] = shape
        size += item_bytes
    flush()
    return files


def compile_feed(args: argparse.Namespace) -> dict:
    archive_path = Path(args.gtfs)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    counts: collections.Counter = collections.Counter()
    rejection_reasons: collections.Counter = collections.Counter()
    with zipfile.ZipFile(archive_path) as archive:
        feed = next(iter(rows(archive, "feed_info.txt")))
        start, end = feed["feed_start_date"], feed["feed_end_date"]
        if parse_date(start) > parse_date(end):
            raise ValueError("Feed start date is after end date")
        agencies = list(rows(archive, "agency.txt"))
        if any(a.get("agency_timezone") != "Asia/Shanghai" for a in agencies):
            raise ValueError("Only Asia/Shanghai feeds are supported")
        services = load_services(archive, start, end)
        if not services:
            raise ValueError("No explicitly dated services found; refusing a synthetic daily calendar")
        source_trips = list(rows(archive, "trips.txt"))
        counts["sourceTrips"] = len(source_trips)
        stop_rows = list(rows(archive, "stops.txt"))
        counts["sourceStops"] = len(stop_rows)
        foreign_ids = {r["stop_id"] for r in stop_rows if r["stop_id"] in EXCLUDED_FOREIGN_STOP_IDS or r["stop_name"] in EXCLUDED_FOREIGN_NAMES}
        stops, stop_indices = [], {}
        invalid_stop_ids = set()
        for row in sorted(stop_rows, key=lambda r: r["stop_id"]):
            stop_id = row["stop_id"]
            if stop_id in foreign_ids:
                continue
            try:
                lon, lat = float(row["stop_lon"]), float(row["stop_lat"])
            except (ValueError, TypeError):
                invalid_stop_ids.add(stop_id)
                continue
            if not (math.isfinite(lon) and math.isfinite(lat) and 73 <= lon <= 136 and 17 <= lat <= 54):
                invalid_stop_ids.add(stop_id)
                continue
            stop_indices[stop_id] = len(stops)
            stops.append({"id": stop_id, "name": row["stop_name"], "lon": round(lon, 6), "lat": round(lat, 6)})
        by_trip: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
        for row in rows(archive, "stop_times.txt"):
            by_trip[row["trip_id"]].append(row)
            counts["sourceStopTimes"] += 1
        for trip_stops in by_trip.values():
            trip_stops.sort(key=lambda r: int(r["stop_sequence"]))
        source_shapes: dict[str, list[tuple[int, tuple[float, float]]]] = collections.defaultdict(list)
        print("Reading route geometry…", flush=True)
        for row in rows(archive, "shapes.txt"):
            shape_id = row["shape_id"]
            lon, lat = float(row["shape_pt_lon"]), float(row["shape_pt_lat"])
            source_shapes[shape_id].append((int(row["shape_pt_sequence"]), (lon, lat)))
            counts["sourceShapePoints"] += 1

    counts["sourceShapes"] = len(source_shapes)
    counts["foreignStopsExcluded"] = len(foreign_ids)
    counts["invalidStopsExcluded"] = len(invalid_stop_ids)
    prepared: dict[str, tuple[list[tuple[float, float]], str | None, float]] = {}
    print(f"Simplifying {len(source_shapes):,} shapes at {args.simplify_m:g} m…", flush=True)
    for i, (shape_id, values) in enumerate(source_shapes.items()):
        values.sort(key=lambda p: p[0])
        points = [v[1] for v in values]
        if len(points) < 2 or any(not (math.isfinite(p[0]) and math.isfinite(p[1]) and -180 <= p[0] <= 180 and -90 <= p[1] <= 90) for p in points):
            prepared[shape_id] = ([], "invalid_route_coordinates", 0)
            continue
        maximum_gap = max(haversine(a, b) for a, b in zip(points, points[1:]))
        if maximum_gap > args.max_source_gap_m:
            prepared[shape_id] = ([], "route_has_large_geometry_gap", maximum_gap)
            counts["shapesRejectedForGeometryGap"] += 1
            continue
        points = quantize(simplify(points, args.simplify_m))
        counts["simplifiedShapePoints"] += len(points)
        prepared[shape_id] = (points, None if len(points) > 1 else "route_is_degenerate", maximum_gap)
        if (i + 1) % 1000 == 0:
            print(f"  prepared {i + 1:,}/{len(source_shapes):,}", flush=True)
    del source_shapes

    trips = []
    encoded_shapes: dict[str, dict] = {}
    geometry_cache: dict[tuple[str, tuple[int, ...]], tuple[list[float] | None, str | None, float, str | None]] = {}
    rejected_examples: dict[str, list[dict]] = collections.defaultdict(list)
    station_offsets = []
    print("Validating times and matching stations to actual route shapes…", flush=True)
    for source in source_trips:
        tid = source["trip_id"]
        timetable = by_trip.get(tid, [])
        if any(stop["stop_id"] in foreign_ids for stop in timetable):
            counts["foreignTripsExcluded"] += 1
            continue
        times, time_error, endpoint_corrections = normalize_times(timetable)
        counts["endpointTimesNormalized"] += endpoint_corrections
        counts["tripsWithSourceShape"] += bool(source.get("shape_id"))
        number = source.get("trip_short_name") or source["route_id"]
        trip = {
            "id": tid, "number": number, "serviceId": source["service_id"],
            "shapeId": None, "type": train_type(number), "stops": [], "renderable": False,
        }
        error = time_error
        if source["service_id"] not in services:
            error = error or "no_valid_service_dates"
        if any(s["stop_id"] not in stop_indices for s in timetable):
            error = error or "unknown_or_invalid_stop"
        if times:
            trip["stops"] = [[stop_indices.get(s["stop_id"], -1), a, d, None] for s, (a, d) in zip(timetable, times)]
        else:
            # Invalid rows remain inspectable without presenting an inferred
            # timetable as valid. UI/core should use timetableValid=false.
            trip["stops"] = [[stop_indices.get(s["stop_id"], -1), parse_time(s.get("arrival_time", "")), parse_time(s.get("departure_time", "")), None] for s in timetable]
            trip["timetableValid"] = False
        shape_id = source.get("shape_id", "")
        if not shape_id:
            error = error or "missing_route_shape"
        elif shape_id not in prepared:
            error = error or "unknown_route_shape"
        elif prepared[shape_id][1]:
            error = error or prepared[shape_id][1]

        if not error:
            station_ids = tuple(s[0] for s in trip["stops"])
            cache_key = (shape_id, station_ids)
            if cache_key not in geometry_cache:
                points = prepared[shape_id][0]
                coordinates = [(stops[j]["lon"], stops[j]["lat"]) for j in station_ids]
                distances, max_offset, projection_error = project_stations(coordinates, points, args.max_stop_offset_m)
                if projection_error == "station_order_conflicts_with_route":
                    reversed_points = list(reversed(points))
                    distances, max_offset, reverse_error = project_stations(coordinates, reversed_points, args.max_stop_offset_m)
                    if not reverse_error:
                        points, projection_error = reversed_points, None
                        counts["stationPatternsReversed"] += 1
                canonical_id = None
                if not projection_error:
                    polyline = encode_polyline(points)
                    canonical_id = "s" + hashlib.sha256(polyline.encode()).hexdigest()[:16]
                    encoded_shapes[canonical_id] = {
                        "p": polyline,
                        "bbox": [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)],
                    }
                geometry_cache[cache_key] = (distances, projection_error, max_offset, canonical_id)
            distances, error, max_offset, canonical_id = geometry_cache[cache_key]
            if not error:
                # A bad shape match can be monotone yet have an impossible
                # segment speed. Reject it rather than animating a teleport.
                for i in range(1, len(times)):
                    travel_seconds = times[i][0] - times[i - 1][1]
                    speed_kmh = (distances[i] - distances[i - 1]) / travel_seconds * 3.6
                    if speed_kmh > args.max_speed_kmh:
                        error = "implausible_route_segment_speed"
                        break
            if not error:
                trip["shapeId"] = canonical_id
                for stop, distance in zip(trip["stops"], distances):
                    stop[3] = round(distance, 1)
                trip["renderable"] = True
                trip["maxStopOffsetM"] = round(max_offset)
                station_offsets.append(max_offset)
        if error:
            trip["geometryNote"] = error
            rejection_reasons[error] += 1
            if len(rejected_examples[error]) < 8:
                rejected_examples[error].append({"id": tid, "number": number, "sourceShapeId": shape_id or None})
        trips.append(trip)

    # Projection checks may have produced a shape subsequently rejected on
    # travel speed. Only transmit shapes actually used by renderable trips.
    used_shapes = {t["shapeId"] for t in trips if t["renderable"]}
    encoded_shapes = {k: v for k, v in encoded_shapes.items() if k in used_shapes}
    shape_files = write_geometry_shards(encoded_shapes, output, args.shard_bytes)
    counts["trips"] = len(trips)
    counts["stops"] = len(stops)
    counts["renderableTrips"] = sum(t["renderable"] for t in trips)
    counts["rejectedTrips"] = counts["trips"] - counts["renderableTrips"]
    counts["publishedShapes"] = len(encoded_shapes)
    counts["geometryShards"] = len(set(shape_files.values()))
    counts["geometryBytes"] = sum((output / f).stat().st_size for f in set(shape_files.values()))
    counts["renderablePercent"] = round(100 * counts["renderableTrips"] / max(1, len(trips)), 2)
    counts["maxStopOffsetM"] = round(max(station_offsets, default=0))
    counts["sourceShapeTripsRejected"] = counts["tripsWithSourceShape"] - counts["renderableTrips"]
    asset_url = args.source_url or (f"{SOURCE_URL}/releases/download/{args.release}/output_gtfs.zip" if args.release else SOURCE_URL + "/releases")
    meta = {
        "feedStartDate": start, "feedEndDate": end, "timezone": "Asia/Shanghai",
        "sourceUrl": SOURCE_URL, "assetUrl": asset_url,
        "release": args.release or feed.get("feed_version", "unknown"),
        "feedVersion": feed.get("feed_version"),
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "mode": "timetable-estimate", "isLiveVehiclePositionFeed": False,
        "positionDescription": "根据社区时刻表与线路几何按北京时间估算；不提供列车实际GPS、实际晚点或停运信息。",
        "scope": "中国境内；包含香港西九龙；含境外停站的跨境行程整体排除",
        "coverageNote": "仅对有明确运行日期、有效停站时序且通过路线质量检查的旅程估算位置；缺失路线不补站间直线。",
        "calendarNote": "严格使用本快照明确列出的运行日期；日历过期不会自动循环为每天。",
        "geometryNote": "社区GTFS中的WGS84路线；上游可能对缺失坐标插值。本构建保守排除原始点间距过大的稀疏路线，该阈值不证明路线错误。通过校验也不等于逐段精确轨道或实际行车路径。",
        "archiveSha256": archive_hash,
        "polylinePrecision": 5, "distanceEarthRadiusM": int(EARTH_RADIUS_M),
        "simplifyToleranceM": args.simplify_m,
        "qualityThresholds": {"maxStopOffsetM": args.max_stop_offset_m, "maxSourceSegmentM": args.max_source_gap_m, "maxSegmentSpeedKmh": args.max_speed_kmh},
        "quality": dict(counts), "rejectionReasons": dict(rejection_reasons),
        "license": {"name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/", "sourceLicenseUrl": SOURCE_URL + "/blob/main/LICENSE", "changes": "已作中国范围筛选、质量校验、几何简化、压缩与格式转换"},
        "attribution": [
            {"name": "Chinese Railway GTFS（社区生成，并非12306官方开放定位接口）", "url": SOURCE_URL},
            {"name": "RailGo-Parser 上游列车数据采集", "url": "https://github.com/RailGoApps/RailGo-Parser"},
            {"name": "OpenStreetMap 车站坐标贡献者", "url": "https://www.openstreetmap.org/copyright"},
        ],
    }
    result = {"schemaVersion": 1, "meta": meta, "stops": stops, "services": services, "trips": trips, "shapeFiles": shape_files}
    (output / "index.json").write_text(compact_json(result), encoding="utf-8")
    report = {"meta": meta, "indexBytes": (output / "index.json").stat().st_size, "rejectedExamples": rejected_examples}
    (output / "quality.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "indexBytes": report["indexBytes"], "quality": dict(counts), "rejectionReasons": dict(rejection_reasons)}, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--gtfs", help="Existing GTFS zip; never modified")
    choice.add_argument("--download", action="store_true", help="Download the latest community GTFS GitHub release")
    parser.add_argument("--release", default="", help="Release tag for provenance")
    parser.add_argument("--source-url", default="", help="Exact archive URL for provenance")
    parser.add_argument("--output", default=str(ROOT / "data" / "trains"))
    parser.add_argument("--simplify-m", type=float, default=100.0)
    parser.add_argument("--max-stop-offset-m", type=float, default=1500.0)
    parser.add_argument("--max-source-gap-m", type=float, default=20000.0)
    parser.add_argument("--max-speed-kmh", type=float, default=450.0)
    parser.add_argument("--shard-bytes", type=int, default=2_800_000)
    args = parser.parse_args()
    if min(args.max_stop_offset_m, args.max_source_gap_m, args.max_speed_kmh, args.shard_bytes) <= 0 or args.simplify_m < 0:
        parser.error("Thresholds must be positive, and simplification nonnegative")
    if args.download:
        with tempfile.TemporaryDirectory(prefix="rail-globe-gtfs-") as temporary:
            target = Path(temporary) / "output_gtfs.zip"
            args.release, args.source_url = download_latest(target)
            args.gtfs = str(target)
            compile_feed(args)
    else:
        compile_feed(args)


if __name__ == "__main__":
    main()
