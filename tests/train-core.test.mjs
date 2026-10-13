import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import {
  chinaDate, chinaClock, clock, formatTime, decodePolyline,
  haversineMetres, shapePath, createEngine,
} from '../src/train-core.mjs';

const HOUR = 3600;
const ONE_DEGREE_METRES = 111194.92664455874;
const at = time => Date.parse(time.includes('+') || time.endsWith('Z') ? time : `${time}+08:00`);

function encode(points) {
  let lat = 0, lng = 0, text = '';
  const part = delta => {
    let unsigned = delta < 0 ? -delta * 2 - 1 : delta * 2;
    let out = '';
    while (unsigned >= 32) {
      out += String.fromCharCode((unsigned % 32) + 32 + 63);
      unsigned = Math.floor(unsigned / 32);
    }
    return out + String.fromCharCode(unsigned + 63);
  };
  for (const point of points) {
    const nextLat = Math.round(point[1] * 1e5), nextLng = Math.round(point[0] * 1e5);
    text += part(nextLat - lat) + part(nextLng - lng);
    lat = nextLat; lng = nextLng;
  }
  return text;
}

function fixture() {
  return {
    schemaVersion: 1,
    meta: { feedStartDate: '20261012', feedEndDate: '20261014', timezone: 'Asia/Shanghai' },
    stops: [
      { id: 'a', name: '始发站', lon: 116, lat: 0 },
      { id: 'b', name: '中间站', lon: 117, lat: 0 },
      { id: 'c', name: '终点站', lon: 118, lat: 0 },
    ],
    services: { s: ['20261012', '20261014'] },
    trips: [{
      id: 'trip-1', number: 'G1', serviceId: 's', shapeId: 'line-1', type: 'G', renderable: true,
      stops: [
        [0, 8 * HOUR, 8 * HOUR, 0],
        [1, 9 * HOUR, 9 * HOUR + 600, ONE_DEGREE_METRES],
        [2, 10 * HOUR, 10 * HOUR, 2 * ONE_DEGREE_METRES],
      ],
    }],
    shapeFiles: { 'line-1': 'shapes/00.json' },
  };
}

const shape = { p: encode([[116, 0], [117, 0], [118, 0]]), bbox: [116, 0, 118, 0] };
const close = (actual, expected, tolerance = 1e-7) => assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} != ${expected}`);

test('Beijing date and clock cross UTC midnight without host timezone dependence', () => {
  const epoch = at('2026-10-11T16:03:04Z');
  assert.equal(chinaDate(epoch), '20261012');
  assert.equal(clock(epoch), '00:03:04');
  assert.equal(chinaClock(epoch, false), '00:03');
  assert.equal(chinaDate(at('2026-12-31T16:00:00Z')), '20270101');
  assert.throws(() => clock(NaN), RangeError);
});

test('service-day time formatting preserves 24h+ values and never turns missing times into midnight', () => {
  assert.equal(formatTime(25 * HOUR + 605), '25:10');
  assert.equal(formatTime(49 * HOUR + 605, { wrap: true, includeSeconds: true }), '01:10:05 (+2日)');
  assert.equal(formatTime(0), '00:00');
  for (const invalid of [null, undefined, NaN, -1, '', '08:00']) assert.equal(formatTime(invalid), '—');
});

test('Google canonical polyline decodes longitude first', () => {
  assert.deepEqual(decodePolyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@'), [
    [-120.2, 38.5], [-120.95, 40.7], [-126.453, 43.252],
  ]);
});

test('malformed, truncated and out-of-range polylines never return partial paths', () => {
  for (const invalid of [null, '', '_', '!', shape.p + '_', encode([[0, 91]]), encode([[181, 0]]), '_'.repeat(30)]) {
    assert.deepEqual(decodePolyline(invalid), []);
  }
  assert.deepEqual(shapePath({ p: '??' }), []);
  assert.deepEqual(shapePath({ p: '????' }), []);
  assert.deepEqual(shapePath([[0, 0], [NaN, 1]]), []);
});

test('haversine uses metres and the compiler earth radius', () => {
  close(haversineMetres([0, 0], [1, 0]), ONE_DEGREE_METRES, 1e-6);
  close(haversineMetres([0, 0], [0, 1]), ONE_DEGREE_METRES, 1e-6);
  assert.equal(haversineMetres([0, 0], [0, 0]), 0);
  assert.ok(Number.isNaN(haversineMetres([null, 0], [1, 0])));
});

test('shapePath accepts shards, encoded strings and decoded paths consistently', () => {
  const expected = [[116, 0], [117, 0], [118, 0]];
  assert.deepEqual(shapePath(shape), expected);
  assert.deepEqual(shapePath(shape.p), expected);
  assert.deepEqual(shapePath(expected), expected);
  assert.deepEqual(createEngine(fixture()).shapePath(shape), expected);
});

test('tripPath clips shared geometry to interpolated first and final stop positions', () => {
  const data = fixture();
  data.trips[0].stops[0][3] = 0.25 * ONE_DEGREE_METRES;
  data.trips[0].stops[2][3] = 1.75 * ONE_DEGREE_METRES;
  const path = createEngine(data).tripPath(data.trips[0], shape);
  assert.equal(path.length, 3);
  close(path[0][0], 116.25);
  close(path[1][0], 117);
  close(path[2][0], 117.75);
  assert.ok(path.every(point => point[1] === 0));
});

test('tripPath handles exact endpoints, metre rounding, missing shapes and rejected trips', () => {
  const data = fixture(), engine = createEngine(data);
  assert.deepEqual(engine.tripPath('trip-1', shape), [[116, 0], [117, 0], [118, 0]]);
  assert.deepEqual(engine.tripPath('trip-1'), []);
  assert.deepEqual(engine.tripPath('missing', shape), []);
  data.trips[0].stops[2][3] = Math.ceil(2 * ONE_DEGREE_METRES);
  assert.deepEqual(createEngine(data).tripPath('trip-1', shape).at(-1), [118, 0]);
  data.trips[0].renderable = false;
  assert.deepEqual(createEngine(data).tripPath('trip-1', shape), []);
});

test('a train starts at departure, dwells, and disappears at terminal arrival', () => {
  const engine = createEngine(fixture());
  assert.equal(engine.activeAt(at('2026-10-12T07:59:59')).length, 0);
  assert.equal(engine.activeAt(at('2026-10-12T08:00:00')).length, 1);
  assert.equal(engine.activeAt(at('2026-10-12T09:05:00')).length, 1);
  assert.equal(engine.activeAt(at('2026-10-12T09:59:59.999')).length, 1);
  assert.equal(engine.activeAt(at('2026-10-12T10:00:00')).length, 0);
});

test('position follows shape distance across station intervals and dwell boundaries', () => {
  const data = fixture(), engine = createEngine(data);
  const instance = engine.tripInstances(data.trips[0], at('2026-10-12T08:30:00'))[0];
  assert.equal(instance.key, 'trip-1@20261012');
  assert.equal(instance.serviceStartMs, at('2026-10-12T00:00:00'));
  const moving = engine.positionAt(instance, at('2026-10-12T08:30:00'), shape);
  assert.equal(moving.status, 'running');
  assert.deepEqual([moving.fromIndex, moving.toIndex], [0, 1]);
  close(moving.coordinate[0], 116.5);
  close(moving.progress, 0.5);
  assert.equal(moving.secondsToNext, 1800);
  assert.equal(moving.source, 'timetable');
  assert.equal(moving.observed, false);
  const dwelling = engine.positionAt(instance, at('2026-10-12T09:05:00'), shape);
  assert.equal(dwelling.status, 'dwell');
  assert.deepEqual([dwelling.fromIndex, dwelling.toIndex, dwelling.stopIndex], [1, 1, 1]);
  close(dwelling.coordinate[0], 117);
  assert.equal(dwelling.secondsToNext, 300);
  assert.equal(dwelling.nextEvent, 'departure');
  assert.equal(engine.positionAt(instance, at('2026-10-12T09:00:00'), shape).status, 'dwell');
  assert.equal(engine.positionAt(instance, at('2026-10-12T09:10:00'), shape).status, 'running');
  close(engine.positionAt(instance, at('2026-10-12T09:35:00'), shape).coordinate[0], 117.5);
});

test('selected non-running instances have explicit scheduled and finished states', () => {
  const data = fixture(), engine = createEngine(data);
  const instance = engine.tripInstances(data.trips[0], at('2026-10-12T07:00:00'))[0];
  const before = engine.positionAt(instance, at('2026-10-12T07:00:00'), shape);
  assert.equal(before.status, 'scheduled');
  assert.equal(before.secondsToNext, 3600);
  assert.deepEqual(before.coordinate, [116, 0]);
  const after = engine.positionAt(instance, at('2026-10-12T10:00:00'), shape);
  assert.equal(after.status, 'finished');
  assert.equal(after.secondsToNext, null);
  assert.equal(after.nextEventMs, null);
  assert.deepEqual(after.coordinate, [118, 0]);
});

test('non-service days and expired calendars do not repeat trains', () => {
  const data = fixture(), engine = createEngine(data);
  assert.equal(engine.activeAt(at('2026-10-13T09:00:00')).length, 0);
  assert.equal(engine.activeAt(at('2026-10-15T09:00:00')).length, 0);
  assert.equal(engine.activeAt(at('2027-10-12T09:00:00')).length, 0);
  const old = engine.tripInstances(data.trips[0], at('2027-10-12T09:00:00'));
  assert.deepEqual(old.map(run => run.serviceDate), ['20261014', '20261012']);
  assert.equal(engine.positionAt(old[0], at('2027-10-12T09:00:00'), shape).status, 'finished');
});

test('search candidates order active, nearest future, then most recent past', () => {
  const data = fixture(), engine = createEngine(data);
  assert.deepEqual(engine.tripInstances(data.trips[0], at('2026-10-12T09:00:00')).map(run => run.serviceDate), ['20261012', '20261014']);
  assert.deepEqual(engine.tripInstances('trip-1', at('2026-10-13T09:00:00')).map(run => run.serviceDate), ['20261014', '20261012']);
  assert.deepEqual(engine.tripInstances('missing', at('2026-10-13T09:00:00')), []);
});

test('preferredInstance matches the first complete candidate before, during and after service', () => {
  const data = fixture(), engine = createEngine(data);
  for (const time of [
    '2026-10-11T09:00:00', '2026-10-12T07:59:59', '2026-10-12T08:00:00',
    '2026-10-12T09:05:00', '2026-10-12T10:00:00', '2026-10-13T09:00:00',
    '2026-10-14T09:00:00', '2026-10-14T10:00:00', '2027-01-01T09:00:00',
  ]) {
    const epoch = at(time);
    assert.equal(engine.preferredInstance(data.trips[0], epoch), engine.tripInstances('trip-1', epoch)[0]);
  }
  assert.equal(engine.preferredInstance('missing', at('2026-10-13T09:00:00')), null);
  data.services.s = [];
  assert.equal(createEngine(data).preferredInstance('trip-1', at('2026-10-13T09:00:00')), null);
});

test('24h+ times are tied to departure service date, not the current date', () => {
  const data = fixture();
  data.services.s = ['20261012'];
  data.trips[0].stops = [[0, 23 * HOUR, 23 * HOUR, 0], [1, 25 * HOUR, 25 * HOUR + 600, ONE_DEGREE_METRES], [2, 27 * HOUR, 27 * HOUR, 2 * ONE_DEGREE_METRES]];
  const engine = createEngine(data), now = at('2026-10-13T01:05:00');
  const [instance] = engine.activeAt(now);
  assert.equal(instance.serviceDate, '20261012');
  assert.equal(instance.endMs, at('2026-10-13T03:00:00'));
  assert.equal(engine.positionAt(instance, now, shape).status, 'dwell');
  assert.equal(engine.activeAt(at('2026-10-13T03:00:00')).length, 0);
});

test('first departure itself can be later than 24h without requiring service on the next day', () => {
  const data = fixture();
  data.services.s = ['20261012'];
  data.trips[0].stops = [[0, 25 * HOUR, 25 * HOUR, 0], [1, 26 * HOUR, 26 * HOUR, ONE_DEGREE_METRES], [2, 27 * HOUR, 27 * HOUR, 2 * ONE_DEGREE_METRES]];
  const engine = createEngine(data);
  assert.equal(engine.activeAt(at('2026-10-12T01:30:00')).length, 0);
  assert.equal(engine.activeAt(at('2026-10-13T01:30:00'))[0].serviceDate, '20261012');
});

test('multi-day runs can overlap and continue past the last valid feed service date', () => {
  const data = fixture();
  data.meta.feedEndDate = '20261013';
  data.services.s = ['20261012', '20261013'];
  data.trips[0].stops = [[0, 23 * HOUR, 23 * HOUR, 0], [1, 25 * HOUR, 25 * HOUR, ONE_DEGREE_METRES], [2, 49 * HOUR, 49 * HOUR, 2 * ONE_DEGREE_METRES]];
  const engine = createEngine(data);
  assert.deepEqual(engine.activeAt(at('2026-10-14T00:30:00')).map(run => run.key), ['trip-1@20261012', 'trip-1@20261013']);
  assert.equal(engine.tripInstances('trip-1', at('2026-10-14T00:30:00'))[0].serviceDate, '20261013');
  assert.deepEqual(engine.activeAt(at('2026-10-14T01:00:00')).map(run => run.serviceDate), ['20261013']);
  assert.equal(engine.activeAt(at('2026-10-15T01:00:00')).length, 0);
  for (const time of ['2026-10-12T22:59:59', '2026-10-13T23:00:00', '2026-10-14T00:30:00', '2026-10-14T01:00:00', '2026-10-15T01:00:00']) {
    const epoch = at(time);
    assert.equal(engine.preferredInstance('trip-1', epoch), engine.tripInstances('trip-1', epoch)[0]);
  }
  assert.equal(engine.preferredInstance('trip-1', at('2026-10-14T00:30:00')).serviceDate, '20261013');
});

test('invalid dates, out-of-feed dates and duplicates never create extra services', () => {
  const data = fixture();
  data.services.s = ['20261012', '20261012', '20261011', '20261015', '20260230', '2026-10-13', 20261013];
  const engine = createEngine(data);
  assert.equal(engine.tripInstances('trip-1', at('2026-10-12T09:00:00')).length, 1);
  assert.equal(engine.diagnostics.ignoredServiceDates, 5);
  assert.equal(engine.activeAt(at('2026-10-11T09:00:00')).length, 0);
  assert.equal(engine.activeAt(at('2026-10-15T09:00:00')).length, 0);
});

test('missing and invalid geometry never substitute a straight-line position', () => {
  const engine = createEngine(fixture()), now = at('2026-10-12T08:30:00');
  const [instance] = engine.activeAt(now);
  for (const missing of [undefined, null, { p: '_' }, { p: '????' }]) {
    const position = engine.positionAt(instance, now, missing);
    assert.equal(position.status, 'running');
    assert.equal(position.coordinate, null);
    assert.equal(position.coordinateSource, null);
  }
  const dwelling = engine.positionAt(instance, at('2026-10-12T09:05:00'));
  assert.equal(dwelling.coordinateSource, 'station');
  assert.deepEqual(dwelling.coordinate, [117, 0]);
});

test('non-renderable trips remain countable but do not get moving coordinates', () => {
  const data = fixture();
  data.trips[0].renderable = false;
  const engine = createEngine(data), now = at('2026-10-12T08:30:00');
  const active = engine.activeAt(now);
  assert.equal(active.length, 1);
  const position = engine.positionAt(active[0], now, shape);
  assert.equal(position.coordinate, null);
  assert.equal(position.geometryIssue, 'trip-not-renderable');
});

test('missing, negative, backwards and out-of-range stop distances are not drawable', () => {
  for (const distances of [[0, null, 200000], [0, -1, 200000], [100000, 50000, 200000], [0, 100000, 1e9], [0, 0, 0]]) {
    const data = fixture();
    data.trips[0].stops.forEach((stop, index) => { stop[3] = distances[index]; });
    const engine = createEngine(data), now = at('2026-10-12T08:30:00');
    const position = engine.positionAt(engine.activeAt(now)[0], now, shape);
    assert.equal(position.coordinate, null);
    assert.equal(position.geometryIssue, 'invalid-shape-distances');
  }
});

test('metre rounding at the final vertex is tolerated without extrapolation', () => {
  const data = fixture();
  data.trips[0].stops[2][3] = Math.ceil(2 * ONE_DEGREE_METRES);
  const engine = createEngine(data), instance = engine.tripInstances('trip-1', at('2026-10-12T09:00:00'))[0];
  const last = engine.positionAt(instance, at('2026-10-12T10:00:00'), shape);
  assert.equal(last.geometryIssue, null);
  assert.deepEqual(last.coordinate, [118, 0]);
});

test('duplicate vertices do not create NaN at interpolation boundaries', () => {
  const repeated = { p: encode([[116, 0], [116, 0], [117, 0], [117, 0], [118, 0]]) };
  const engine = createEngine(fixture()), now = at('2026-10-12T09:10:00');
  const position = engine.positionAt(engine.activeAt(now)[0], now, repeated);
  close(position.coordinate[0], 117);
  assert.equal(position.coordinate[1], 0);
});

test('shape interpolation uses its bent path rather than the line between stations', () => {
  const data = fixture();
  const cornerShape = { p: encode([[0, 0], [1, 0], [1, 1]]) };
  data.trips[0].stops = [[0, 0, 0, 0], [2, 2 * HOUR, 2 * HOUR, 2 * ONE_DEGREE_METRES]];
  const engine = createEngine(data), now = at('2026-10-12T01:00:00');
  const position = engine.positionAt(engine.activeAt(now)[0], now, cornerShape);
  close(position.coordinate[0], 1);
  close(position.coordinate[1], 0);
});

test('a null station coordinate is not interpreted as the Gulf of Guinea', () => {
  const data = fixture();
  data.stops[1].lon = null;
  const engine = createEngine(data), now = at('2026-10-12T09:05:00');
  assert.equal(engine.positionAt(engine.activeAt(now)[0], now).coordinate, null);
});

test('invalid schedules are diagnosed and excluded instead of moving in reverse time', () => {
  const data = fixture();
  const valid = structuredClone(data.trips[0]);
  const bad = [
    { ...structuredClone(valid), id: 'negative', stops: [[0, -1, -1, 0], [2, 10, 10, 1]] },
    { ...structuredClone(valid), id: 'backwards', stops: [[0, 10, 10, 0], [2, 9, 9, 1]] },
    { ...structuredClone(valid), id: 'missing', stops: [[0, null, null, 0], [2, 10, 10, 1]] },
    { ...structuredClone(valid), id: 'reference', stops: [[99, 0, 0, 0], [2, 10, 10, 1]] },
    { ...structuredClone(valid), id: 'same-time', stops: [[0, 10, 10, 0], [2, 10, 10, 1]] },
    { ...structuredClone(valid), id: 'bad-service', serviceId: 'no-calendar' },
  ];
  data.trips.push(...bad);
  const engine = createEngine(data);
  assert.equal(engine.diagnostics.invalidTrips.length, bad.length);
  assert.deepEqual(engine.activeAt(at('2026-10-12T08:30:00')).map(run => run.trip.id), ['trip-1']);
});

test('missing origin arrival and terminal departure use the available event', () => {
  const data = fixture();
  data.trips[0].stops[0][1] = null;
  data.trips[0].stops[2][2] = null;
  const engine = createEngine(data);
  assert.equal(engine.diagnostics.invalidTrips.length, 0);
  assert.equal(engine.activeAt(at('2026-10-12T08:30:00')).length, 1);
});

test('an explicit compiler timetable rejection overrides otherwise usable-looking times', () => {
  const data = fixture();
  data.trips[0].timetableValid = false;
  const engine = createEngine(data);
  assert.equal(engine.activeAt(at('2026-10-12T08:30:00')).length, 0);
  assert.equal(engine.tripInstances('trip-1', at('2026-10-12T08:30:00')).length, 0);
  assert.equal(engine.diagnostics.invalidTrips[0].reason, 'timetable rejected by data compiler');
});

test('pass-through and simultaneous zero-length timing events select the next actual segment', () => {
  const data = fixture();
  data.trips[0].stops = [[0, 8 * HOUR, 8 * HOUR, 0], [1, 8 * HOUR, 8 * HOUR, 0], [2, 10 * HOUR, 10 * HOUR, 2 * ONE_DEGREE_METRES]];
  const engine = createEngine(data), now = at('2026-10-12T08:00:00');
  const position = engine.positionAt(engine.activeAt(now)[0], now, shape);
  assert.equal(position.status, 'running');
  assert.equal(position.fromIndex, 1);
  assert.equal(position.toIndex, 2);
  assert.equal(position.progress, 0);
});

test('invalid metadata and invalid queried timestamps fail explicitly', () => {
  const data = fixture();
  assert.throws(() => createEngine({ ...data, schemaVersion: 2 }), TypeError);
  assert.throws(() => createEngine({ ...data, meta: { ...data.meta, timezone: 'UTC' } }), RangeError);
  assert.throws(() => createEngine({ ...data, meta: { ...data.meta, feedStartDate: '20260230' } }), RangeError);
  assert.throws(() => createEngine({ ...data, meta: { ...data.meta, feedEndDate: '20261011' } }), RangeError);
  const engine = createEngine(data);
  assert.throws(() => engine.activeAt(NaN), RangeError);
  assert.throws(() => engine.positionAt({ trip: data.trips[0], serviceDate: '20261013' }, at('2026-10-13T09:00:00'), shape), RangeError);
});

test('engine dates and active instances are identical under two different process timezones', () => {
  const moduleURL = new URL('../src/train-core.mjs', import.meta.url).href;
  const program = `import { createEngine, chinaDate, clock } from ${JSON.stringify(moduleURL)};
const data = ${JSON.stringify(fixture())};
const epoch = Date.parse('2026-10-12T00:30:00Z');
console.log(JSON.stringify({date: chinaDate(epoch), clock: clock(epoch), keys: createEngine(data).activeAt(epoch).map(x => x.key)}));`;
  const outputs = ['Pacific/Honolulu', 'Europe/London'].map(TZ => {
    const result = spawnSync(process.execPath, ['--input-type=module', '-e', program], {
      encoding: 'utf8', env: { ...process.env, TZ },
    });
    assert.equal(result.status, 0, result.stderr);
    return JSON.parse(result.stdout);
  });
  assert.deepEqual(outputs[0], outputs[1]);
  assert.deepEqual(outputs[0], { date: '20261012', clock: '08:30:00', keys: ['trip-1@20261012'] });
});
