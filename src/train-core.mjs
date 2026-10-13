/**
 * Calendar-aware timetable playback for the China Rail Globe extension.
 *
 * All service-day times are seconds after midnight in Asia/Shanghai (UTC+8),
 * including values above 24 hours. Positions are timetable estimates, never
 * observations or statements that a train is on time.
 *
 * Geometry contract: Google polyline5; stop distances are metres measured along
 * that exact decoded geometry using a sphere of radius 6,371,000 metres.
 */

export const CHINA_TIMEZONE = 'Asia/Shanghai';
export const EARTH_RADIUS_METRES = 6371000;

const OFFSET_MS = 8 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;
const EMPTY_PATH = Object.freeze([]);
const DISTANCE_ROUNDING_METRES = 2;
const shapeCache = new WeakMap();
const stringShapeCache = new Map();

function validNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function assertEpoch(epochMs) {
  if (!validNumber(epochMs) || Math.abs(epochMs) > 8.64e15 - OFFSET_MS) {
    throw new RangeError('epochMs must be a finite, representable timestamp in milliseconds');
  }
  return epochMs;
}

function serviceDateInfo(value) {
  if (typeof value !== 'string' || !/^\d{8}$/.test(value)) return null;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > 31) return null;
  const date = new Date(0);
  // setUTCFullYear avoids Date.UTC's special treatment of years 0 through 99.
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(0, 0, 0, 0);
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return { date: value, midnightMs: date.getTime() - OFFSET_MS };
}

/** YYYYMMDD in Beijing time, independent of the browser or server timezone. */
export function chinaDate(epochMs = Date.now()) {
  const date = new Date(assertEpoch(epochMs) + OFFSET_MS);
  return String(date.getUTCFullYear()).padStart(4, '0') +
    String(date.getUTCMonth() + 1).padStart(2, '0') +
    String(date.getUTCDate()).padStart(2, '0');
}

/** HH:mm:ss in Beijing time; pass false as the second argument for HH:mm. */
export function clock(epochMs = Date.now(), includeSeconds = true) {
  const date = new Date(assertEpoch(epochMs) + OFFSET_MS);
  const parts = [date.getUTCHours(), date.getUTCMinutes()];
  if (includeSeconds) parts.push(date.getUTCSeconds());
  return parts.map(value => String(value).padStart(2, '0')).join(':');
}

export const chinaClock = clock;

/**
 * Format GTFS service-day seconds. Default preserves 24h+ hours (25:10).
 * { wrap: true } instead gives 01:10 (+1日); { includeSeconds: true } adds :ss.
 * A missing or invalid time is shown as an em dash, never as midnight.
 */
export function formatTime(serviceDaySeconds, { wrap = false, includeSeconds = false } = {}) {
  if (!validNumber(serviceDaySeconds) || serviceDaySeconds < 0) return '—';
  const total = Math.floor(serviceDaySeconds);
  const days = Math.floor(total / 86400);
  const hours = Math.floor(total / 3600);
  const parts = [wrap ? hours % 24 : hours, Math.floor(total / 60) % 60];
  if (includeSeconds) parts.push(total % 60);
  return parts.map(value => String(value).padStart(2, '0')).join(':') +
    (wrap && days ? ` (+${days}日)` : '');
}

function validCoordinate(point) {
  return Array.isArray(point) && point.length >= 2 &&
    validNumber(point[0]) && validNumber(point[1]) &&
    Math.abs(point[0]) <= 180 && Math.abs(point[1]) <= 90;
}

/**
 * Decode Google polyline5 to [longitude, latitude] pairs.
 * Malformed encodings or out-of-range coordinates return [], never a partial
 * path which could silently join unrelated points.
 */
export function decodePolyline(encoded) {
  if (typeof encoded !== 'string' || !encoded.length) return [];
  let index = 0, latitude = 0, longitude = 0;
  const coordinates = [];
  const read = () => {
    let value = 0, shift = 0;
    for (;;) {
      if (index >= encoded.length || shift > 30) return null;
      const byte = encoded.charCodeAt(index++) - 63;
      if (byte < 0 || byte > 63) return null;
      value += (byte & 31) * (2 ** shift);
      if (byte < 32) return value % 2 ? -(value + 1) / 2 : value / 2;
      shift += 5;
    }
  };
  while (index < encoded.length) {
    const dLat = read();
    if (dLat === null) return [];
    const dLon = read();
    if (dLon === null) return [];
    latitude += dLat;
    longitude += dLon;
    const point = [longitude / 1e5, latitude / 1e5];
    if (!validCoordinate(point)) return [];
    coordinates.push(point);
  }
  return coordinates;
}

/** Spherical distance in metres, using the compiler's fixed earth radius. */
export function haversineMetres(a, b) {
  if (!validCoordinate(a) || !validCoordinate(b)) return NaN;
  const rad = Math.PI / 180;
  const dLat = (b[1] - a[1]) * rad;
  const dLon = (b[0] - a[0]) * rad;
  const h = Math.sin(dLat / 2) ** 2 +
    Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dLon / 2) ** 2;
  return EARTH_RADIUS_METRES * 2 * Math.atan2(Math.sqrt(Math.min(1, h)), Math.sqrt(Math.max(0, 1 - h)));
}

function prepareShape(shape) {
  if (shape && typeof shape === 'object' && shapeCache.has(shape)) return shapeCache.get(shape);
  if (typeof shape === 'string' && stringShapeCache.has(shape)) return stringShapeCache.get(shape);

  const points = Array.isArray(shape)
    ? (shape.every(validCoordinate) ? shape.map(point => [point[0], point[1]]) : [])
    : decodePolyline(typeof shape === 'string' ? shape : shape?.p);
  let prepared = null;
  if (points.length >= 2) {
    const distances = new Float64Array(points.length);
    for (let i = 1; i < points.length; i++) {
      distances[i] = distances[i - 1] + haversineMetres(points[i - 1], points[i]);
    }
    const length = distances[distances.length - 1];
    if (Number.isFinite(length) && length > 0) {
      prepared = { points, distances, length };
    }
  }
  if (shape && typeof shape === 'object') shapeCache.set(shape, prepared);
  if (typeof shape === 'string') {
    // Object-form geometry shards use the WeakMap. Bound the convenience cache
    // for callers that repeatedly supply raw encoded strings.
    if (stringShapeCache.size >= 128) stringShapeCache.delete(stringShapeCache.keys().next().value);
    stringShapeCache.set(shape, prepared);
  }
  return prepared;
}

/** A LineString-ready [lng,lat][]; [] for a missing, invalid or zero-length path. */
export function shapePath(shape) {
  return prepareShape(shape)?.points || EMPTY_PATH;
}

function pointAlong(shape, distance) {
  const target = Math.max(0, Math.min(shape.length, distance));
  if (target === 0) return [...shape.points[0]];
  if (target === shape.length) return [...shape.points[shape.points.length - 1]];
  let lo = 0, hi = shape.distances.length - 1;
  // First cumulative distance strictly greater than target. Skipping duplicate
  // vertices here avoids dividing by the length of a zero-length segment.
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (shape.distances[mid] <= target) lo = mid + 1;
    else hi = mid;
  }
  const next = lo, previous = next - 1;
  const fraction = (target - shape.distances[previous]) /
    (shape.distances[next] - shape.distances[previous]);
  const a = shape.points[previous], b = shape.points[next];
  let deltaLng = b[0] - a[0];
  if (deltaLng > 180) deltaLng -= 360;
  if (deltaLng < -180) deltaLng += 360;
  let longitude = a[0] + fraction * deltaLng;
  if (longitude > 180) longitude -= 360;
  if (longitude < -180) longitude += 360;
  return [longitude, a[1] + fraction * (b[1] - a[1])];
}

function upperBound(values, target) {
  let lo = 0, hi = values.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (values[mid] <= target) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * Create an engine for trains/index.json schemaVersion 1.
 *
 * activeAt(t): all valid instances whose first departure <= t < final arrival.
 * Includes trips without drawable geometry, so a list can show coverage honestly.
 *
 * tripInstances(trip, t): every valid service date, ordered active first (newest
 * departure first), future next (nearest departure first), past last (most recent
 * arrival first). Thus [0] is useful for a search/detail view even off service.
 * preferredInstance(trip, t): the same first result, using a binary search and
 * allocating at most one instance; null when the trip has no valid service date.
 * tripPath(trip, shape): the valid shape clipped to the trip's first and final
 * stop distances, including interpolated endpoints; [] when not drawable.
 *
 * positionAt(instance, t, shape): timetable position. A running leg requires a
 * valid shape and valid monotonic stop distances. Otherwise coordinate is null.
 * A stopped train can use its supplied station coordinate. For a dwell,
 * fromIndex === toIndex === stopIndex; secondsToNext is until departure.
 */
export function createEngine(data) {
  if (!data || data.schemaVersion !== 1 || !Array.isArray(data.trips) ||
    !Array.isArray(data.stops) || !data.services || typeof data.services !== 'object') {
    throw new TypeError('Expected a trains index with schemaVersion 1, trips, stops and services');
  }
  if (data.meta?.timezone !== CHINA_TIMEZONE) {
    throw new RangeError(`Timetable timezone must be ${CHINA_TIMEZONE}`);
  }
  const feedStart = serviceDateInfo(data.meta?.feedStartDate);
  const feedEnd = serviceDateInfo(data.meta?.feedEndDate);
  if (!feedStart || !feedEnd || feedEnd.midnightMs < feedStart.midnightMs) {
    throw new RangeError('feedStartDate and feedEndDate must be valid ordered YYYYMMDD dates');
  }

  const diagnostics = { ignoredServiceDates: 0, invalidServices: 0, invalidTrips: [] };
  const calendars = new Map();
  for (const [id, dates] of Object.entries(data.services)) {
    if (!Array.isArray(dates)) {
      diagnostics.invalidServices++;
      continue;
    }
    const unique = new Map();
    for (const value of dates) {
      const day = serviceDateInfo(value);
      if (!day || day.midnightMs < feedStart.midnightMs || day.midnightMs > feedEnd.midnightMs) {
        diagnostics.ignoredServiceDates++;
        continue;
      }
      unique.set(day.midnightMs, day.date);
    }
    const starts = [...unique.keys()].sort((a, b) => a - b);
    calendars.set(id, { starts, dates: unique });
  }

  const records = [], byId = new Map();
  for (const trip of data.trips) {
    let reason = null;
    const id = trip?.id == null ? '' : String(trip.id);
    const calendar = calendars.get(String(trip?.serviceId));
    const rows = [];
    if (!id) reason = 'missing trip id';
    else if (trip.timetableValid === false) reason = 'timetable rejected by data compiler';
    else if (byId.has(id)) reason = 'duplicate trip id';
    else if (!calendar) reason = 'missing or invalid service calendar';
    else if (!Array.isArray(trip.stops) || trip.stops.length < 2) reason = 'at least two timed stops are required';
    if (!reason) {
      for (const row of trip.stops) {
        if (!Array.isArray(row) || !Number.isInteger(row[0]) || row[0] < 0 || row[0] >= data.stops.length) {
          reason = 'invalid stop reference';
          break;
        }
        // An absent origin arrival or terminal departure is normal in GTFS. A
        // single supplied event is sufficient to represent a no-dwell stop.
        const arrival = row[1] == null ? row[2] : row[1];
        const departure = row[2] == null ? row[1] : row[2];
        if (!validNumber(arrival) || !validNumber(departure) || arrival < 0 || departure < arrival ||
          !Number.isSafeInteger(Math.round(arrival * 1000)) || !Number.isSafeInteger(Math.round(departure * 1000)) ||
          (rows.length && arrival < rows[rows.length - 1].departure)) {
          reason = 'missing, negative or non-monotonic stop times';
          break;
        }
        rows.push({ stopIndex: row[0], arrival, departure, distance: row[3] });
      }
    }
    if (!reason && rows[rows.length - 1].arrival <= rows[0].departure) reason = 'trip has no positive running interval';
    if (reason) {
      diagnostics.invalidTrips.push({ id, reason });
      continue;
    }
    const record = {
      trip, rows, calendar, id,
      startOffsetMs: rows[0].departure * 1000,
      endOffsetMs: rows[rows.length - 1].arrival * 1000,
      instances: new Map(),
      geometryChecks: new WeakMap(),
    };
    byId.set(id, record);
    records.push(record);
  }

  const instanceFor = (record, serviceStartMs) => {
    if (!record.instances.has(serviceStartMs)) {
      const serviceDate = record.calendar.dates.get(serviceStartMs);
      record.instances.set(serviceStartMs, {
        key: `${record.id}@${serviceDate}`,
        trip: record.trip,
        serviceDate,
        serviceStartMs,
        startMs: serviceStartMs + record.startOffsetMs,
        endMs: serviceStartMs + record.endOffsetMs,
      });
    }
    return record.instances.get(serviceStartMs);
  };

  const activeAt = epochMs => {
    assertEpoch(epochMs);
    const active = [];
    for (const record of records) {
      // A run exists iff its actual calendar date starts in this open/closed
      // interval. This covers 24h+ starts, multi-day runs, and two simultaneous
      // departures of the same train number without assuming today's weekday.
      const starts = record.calendar.starts;
      const from = upperBound(starts, epochMs - record.endOffsetMs);
      const until = upperBound(starts, epochMs - record.startOffsetMs);
      for (let i = from; i < until; i++) active.push(instanceFor(record, starts[i]));
    }
    return active;
  };

  const tripInstances = (trip, epochMs = Date.now()) => {
    assertEpoch(epochMs);
    const record = byId.get(String(typeof trip === 'object' ? trip?.id : trip));
    if (!record) return [];
    const instances = record.calendar.starts.map(start => instanceFor(record, start));
    const rank = instance => instance.startMs <= epochMs && epochMs < instance.endMs ? 0 : epochMs < instance.startMs ? 1 : 2;
    return instances.sort((a, b) => {
      const aRank = rank(a), bRank = rank(b);
      return aRank - bRank || (aRank === 1 ? a.startMs - b.startMs : b.endMs - a.endMs);
    });
  };

  const preferredInstance = (trip, epochMs = Date.now()) => {
    assertEpoch(epochMs);
    const record = byId.get(String(typeof trip === 'object' ? trip?.id : trip));
    if (!record || !record.calendar.starts.length) return null;
    const starts = record.calendar.starts;
    const next = upperBound(starts, epochMs - record.startOffsetMs);
    // Instances of a trip share one duration. Its latest departure therefore
    // also ends latest, so testing this one candidate covers overlapping runs.
    if (next > 0 && epochMs < starts[next - 1] + record.endOffsetMs) {
      return instanceFor(record, starts[next - 1]);
    }
    if (next < starts.length) return instanceFor(record, starts[next]);
    return instanceFor(record, starts[starts.length - 1]);
  };

  const checkedGeometry = (record, rawShape) => {
    if (record.trip.renderable === false) return { shape: null, reason: 'trip-not-renderable' };
    const shape = prepareShape(rawShape);
    if (!shape) return { shape: null, reason: rawShape ? 'invalid-shape' : 'missing-shape' };
    if (record.geometryChecks.has(shape)) return record.geometryChecks.get(shape);
    let previous = -Infinity;
    const valid = record.rows.every(row => {
      const distance = row.distance;
      if (!validNumber(distance) || distance < 0 || distance + 1e-6 < previous ||
        distance > shape.length + DISTANCE_ROUNDING_METRES) return false;
      previous = distance;
      return true;
    }) && record.rows[record.rows.length - 1].distance > record.rows[0].distance;
    const result = valid ? { shape, reason: null } : { shape: null, reason: 'invalid-shape-distances' };
    record.geometryChecks.set(shape, result);
    return result;
  };

  const tripPath = (trip, rawShape) => {
    const record = byId.get(String(typeof trip === 'object' ? trip?.id : trip));
    if (!record) return EMPTY_PATH;
    const { shape } = checkedGeometry(record, rawShape);
    if (!shape) return EMPTY_PATH;
    const first = Math.max(0, Math.min(shape.length, record.rows[0].distance));
    const last = Math.max(0, Math.min(shape.length, record.rows[record.rows.length - 1].distance));
    if (last <= first) return EMPTY_PATH;
    const points = [pointAlong(shape, first)];
    let index = upperBound(shape.distances, first);
    while (index < shape.points.length && shape.distances[index] < last) {
      points.push([...shape.points[index++]]);
    }
    points.push(pointAlong(shape, last));
    return points;
  };

  const positionAt = (instance, epochMs, rawShape) => {
    assertEpoch(epochMs);
    const record = byId.get(String(instance?.trip?.id));
    const day = serviceDateInfo(instance?.serviceDate);
    if (!record || !day || !record.calendar.dates.has(day.midnightMs)) {
      throw new RangeError('positionAt requires an instance from a valid service calendar');
    }
    const run = instanceFor(record, day.midnightMs);
    const rows = record.rows, last = rows.length - 1;
    const serviceSeconds = (epochMs - run.serviceStartMs) / 1000;
    const geometry = checkedGeometry(record, rawShape);
    const stationPosition = index => {
      if (geometry.shape) return { coordinate: pointAlong(geometry.shape, rows[index].distance), coordinateSource: 'shape' };
      const stop = data.stops[rows[index].stopIndex];
      const point = [stop?.lon, stop?.lat];
      return validCoordinate(point)
        ? { coordinate: point, coordinateSource: 'station' }
        : { coordinate: null, coordinateSource: null };
    };
    const base = {
      source: 'timetable',
      observed: false,
      geometryIssue: geometry.reason,
      serviceSeconds,
      tripProgress: Math.max(0, Math.min(1, (epochMs - run.startMs) / (run.endMs - run.startMs))),
    };
    if (epochMs < run.startMs) {
      return {
        ...base, ...stationPosition(0), status: 'scheduled',
        fromIndex: 0, toIndex: 0, stopIndex: 0, nextIndex: 0, progress: 0,
        secondsToNext: (run.startMs - epochMs) / 1000, nextEvent: 'departure', nextEventMs: run.startMs,
      };
    }
    if (epochMs >= run.endMs) {
      return {
        ...base, ...stationPosition(last), status: 'finished',
        fromIndex: last, toIndex: last, stopIndex: last, nextIndex: null, progress: 1,
        secondsToNext: null, nextEvent: null, nextEventMs: null,
      };
    }
    for (let i = 0; i < last; i++) {
      const here = rows[i], next = rows[i + 1];
      if (serviceSeconds >= here.arrival && serviceSeconds < here.departure) {
        return {
          ...base, ...stationPosition(i), status: 'dwell',
          fromIndex: i, toIndex: i, stopIndex: i, nextIndex: i + 1, progress: 0,
          secondsToNext: here.departure - serviceSeconds, nextEvent: 'departure',
          nextEventMs: run.serviceStartMs + here.departure * 1000,
        };
      }
      if (serviceSeconds >= here.departure && serviceSeconds < next.arrival) {
        const progress = (serviceSeconds - here.departure) / (next.arrival - here.departure);
        const distance = geometry.shape ? here.distance + (next.distance - here.distance) * progress : null;
        return {
          ...base, status: 'running',
          coordinate: geometry.shape ? pointAlong(geometry.shape, distance) : null,
          coordinateSource: geometry.shape ? 'shape' : null,
          fromIndex: i, toIndex: i + 1, stopIndex: null, nextIndex: i + 1, progress,
          secondsToNext: next.arrival - serviceSeconds, nextEvent: 'arrival',
          nextEventMs: run.serviceStartMs + next.arrival * 1000,
          distanceMetres: distance,
        };
      }
    }
    // Validated times cover the whole interval. Never invent a coordinate if a
    // caller has mutated timetable data or supplied an unsupported edge case.
    throw new RangeError('No timetable segment covers this instance time');
  };

  return {
    activeAt,
    tripInstances,
    preferredInstance,
    positionAt,
    shapePath,
    tripPath,
    diagnostics,
    feedWindow: {
      startMs: feedStart.midnightMs,
      endMs: feedEnd.midnightMs + DAY_MS,
      startDate: feedStart.date,
      endDate: feedEnd.date,
    },
  };
}
