// Dedicated executable boundary contracts. These do not claim visual acceptance.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const app = readFileSync(join(root, 'src/app.html'), 'utf8');
const view = JSON.parse(readFileSync(join(root, 'data/view_boundaries.json'), 'utf8'));
const borderData = process.env.BORDERS_DATA_DIR || join(root, 'data');
const canonicalBytes = readFileSync(join(borderData, 'europe_borders.geojson'));
const canonical = JSON.parse(canonicalBytes);
const packed = JSON.parse(readFileSync(join(borderData, 'europe_borders.packed.json'), 'utf8'));
const codes = ['de', 'fr', 'ch', 'es', 'nl', 'be', 'it'];
const core = app.split('/*VIEW-CORE*/')[1].split('/*VIEW-CORE-END*/')[0]
  .replace('/*VIEW_BOUNDARIES*/{}', JSON.stringify(Object.fromEntries(
    Object.entries(view.countries).map(([g, geometry]) => [g, geometry.coordinates]))));
const { viewDepth, unpackViewRing } = new Function(core + '\nreturn {viewDepth, unpackViewRing};')();
const declarations = app.slice(app.indexOf('  const emptyBorders ='), app.indexOf('  const PLACE_RANKS ='));
const { unpackBorders } = new Function('unpackViewRing', declarations + '\nreturn {unpackBorders};')(unpackViewRing);
const foreignText = app.slice(app.indexOf('  const FOREIGN ='), app.indexOf('  for (const g of Object.keys(FOREIGN))'));
const flags = ['jp', 'kr', 'uk', ...codes, 'la', 'my', 'sg', 'th', 'id'].map(g => `const WITH_${g.toUpperCase()} = true;`).join('\n');
const countries = new Function('viewDepth', 'VIEW_BOUNDARIES', flags + foreignText + '\nreturn FOREIGN;')(
  viewDepth, view.countries);

test('packed visible boundaries decode without any coordinate loss', () => {
  assert.equal(packed.canonical_sha256, createHash('sha256').update(canonicalBytes).digest('hex'));
  const decoded = packed.features.map(f => ({ ...f, geometry: {
    ...f.geometry, coordinates: f.geometry.coordinates.map(unpackViewRing),
  } }));
  assert.deepEqual(decoded, canonical.features);
});

test('page packed wrapper must accept actual inland boundaries', () => {
  // Inland borders are open except genuine source loops; never close them to
  // satisfy a page wrapper's former polygon-ring contract.
  assert.deepEqual(unpackBorders(packed).features, canonical.features);
});

test('page packed wrapper rejects malformed boundary encodings', () => {
  assert.throws(() => unpackBorders({ ...packed, encoding: 'unknown' }), /encoding/);
  const malformed = { ...packed, features: [{ ...packed.features[0],
    geometry: { type: 'MultiLineString', coordinates: ['?'] } }] };
  assert.throws(() => unpackBorders(malformed), /boundary/);
});

test('finer than six decimals retain exact float64 coordinates', () => {
  const points = [[4.123456789012345, 51.12345678901234], [-0, -12.3456789012345]];
  const bytes = Buffer.alloc(points.length * 16);
  points.forEach(([x, y], i) => { bytes.writeDoubleLE(x, i * 16); bytes.writeDoubleLE(y, i * 16 + 8); });
  assert.deepEqual(unpackViewRing({ f64: bytes.toString('base64') }), points);
  assert.throws(() => unpackViewRing({ f64: 'AQ==' }), /float64/);
});

test('polyline6 open lines need not close and decode losslessly', () => {
  assert.deepEqual(unpackViewRing('??A@'), [[0, 0], [0.000001, -0.000001]]);
});

test('page packed wrapper must accept two-point open national lines', () => {
  const encoded = { type: 'FeatureCollection', encoding: 'polyline6-xy', features: [{
    type: 'Feature', properties: { g: 'fr', k: 'land' },
    geometry: { type: 'MultiLineString', coordinates: ['??A@'] },
  }] };
  assert.deepEqual(unpackBorders(encoded).features[0].geometry.coordinates,
    [[[0, 0], [0.000001, -0.000001]]]);
});

test('page packed wrapper accepts an open LineString and genuine closed source loop', () => {
  const line = {
    type: 'Feature', properties: { g: 'fr', k: 'land' },
    geometry: { type: 'LineString', coordinates: '??A@' },
  };
  const closed = {
    type: 'Feature', properties: { g: 'be', k: 'land' },
    geometry: { type: 'MultiLineString', coordinates: ['??A??A@@'] },
  };
  const encoded = { type: 'FeatureCollection', encoding: 'polyline6-xy', features: [line, closed] };
  const decoded = unpackBorders(encoded).features;
  assert.deepEqual(decoded[0].geometry.coordinates, [[0, 0], [0.000001, -0.000001]]);
  assert.deepEqual(decoded[1].geometry.coordinates,
    [[[0, 0], [0.000001, 0], [0.000001, 0.000001], [0, 0]]]);
});

test('page packed wrapper rejects degenerate and out-of-range national lines', () => {
  const feature = coordinates => ({
    type: 'Feature', properties: { g: 'fr', k: 'land' },
    geometry: { type: 'MultiLineString', coordinates: [coordinates] },
  });
  const encodeFloat64 = points => {
    const bytes = Buffer.alloc(points.length * 16);
    points.forEach(([x, y], i) => {
      bytes.writeDoubleLE(x, i * 16);
      bytes.writeDoubleLE(y, i * 16 + 8);
    });
    return { f64: bytes.toString('base64') };
  };
  for (const points of [[[0, 0], [0, 0]], [[0, 0]], [[0, 0], [181, 40]],
    [[0, 0], [1, 91]], [[0, 0], [NaN, 40]]]) {
    assert.throws(() => unpackBorders({
      type: 'FeatureCollection', encoding: 'polyline6-xy',
      features: [feature(encodeFloat64(points))],
    }), /boundary/);
  }
});

test('actual land boundaries are open except genuine source loops, with every neighbor', () => {
  assert.match(canonical.purpose, /no coastlines or maritime/);
  assert.equal(canonical.selection.COAS_FLAG, 'F');
  assert.equal(canonical.selection.unique_in_scope_boundaries, 29);
  assert.deepEqual(canonical.features.map(f => f.properties.g).sort(), [...codes].sort());
  const neighbors = {
    de: ['AUT', 'BEL', 'CHE', 'CZE', 'DNK', 'FRA', 'LUX', 'NLD', 'POL'],
    fr: ['AND', 'BEL', 'CHE', 'DEU', 'ESP', 'ITA', 'LUX', 'MCO'],
    ch: ['AUT', 'DEU', 'FRA', 'ITA', 'LIE'], es: ['AND', 'FRA', 'GIB', 'MAR', 'PRT'],
    nl: ['BEL', 'DEU'], be: ['DEU', 'FRA', 'LUX', 'NLD'],
    it: ['AUT', 'CHE', 'FRA', 'SMR', 'SVN', 'VAT'],
  };
  for (const feature of canonical.features) {
    const g = feature.properties.g;
    assert.deepEqual(feature.properties, { g, k: 'land' });
    const parts = feature.geometry.coordinates;
    assert.ok(parts.some(p => JSON.stringify(p[0]) !== JSON.stringify(p.at(-1))), g);
    assert.deepEqual(canonical.counts[g].neighbors, neighbors[g]);
    assert.equal(canonical.counts[g].display_vertices, parts.reduce((sum, p) => sum + p.length, 0));
    assert.ok(canonical.counts[g].boundaries.every(p => p.COAS_FLAG === 'F'));
    for (const p of parts.flat()) {
      assert.ok(p.length === 2 && p.every(Number.isFinite));
      assert.ok(p[0] >= -25 && p[0] <= 45 && p[1] >= 34 && p[1] <= 72);
      assert.ok(!(p[0] >= -18.5 && p[0] <= -13 && p[1] >= 27.5 && p[1] <= 29.5));
    }
  }
  assert.equal(canonical.selection.excluded.filter(p => p.reason === 'coastline').length, 6);
  const es = canonical.features.find(f => f.properties.g === 'es');
  for (const [west, south, east, north] of [[-5.39, 35.86, -5.33, 35.92], [-2.98, 35.26, -2.92, 35.33]]) {
    assert.ok(es.geometry.coordinates.some(points => points.every(([x, y]) =>
      x >= west && x <= east && y >= south && y <= north)));
  }
});

test('shared source lines occur unchanged under both country g switches', () => {
  const iso = { de: 'DEU', fr: 'FRA', ch: 'CHE', es: 'ESP', nl: 'NLD', be: 'BEL', it: 'ITA' };
  const sourceParts = (g, id) => {
    let offset = 0;
    const feature = canonical.features.find(f => f.properties.g === g);
    for (const boundary of canonical.counts[g].boundaries) {
      const points = feature.geometry.coordinates.slice(offset, offset + boundary.parts.length);
      if (boundary.id === id) return points;
      offset += boundary.parts.length;
    }
    return undefined;
  };
  for (const g of codes) for (const boundary of canonical.counts[g].boundaries) {
    const other = codes.find(c => c !== g && [boundary.left, boundary.right].includes(iso[c]));
    if (other) assert.deepEqual(sourceParts(g, boundary.id), sourceParts(other, boundary.id));
  }
});

test('seven configurations use sourced ownership instead of country boxes', () => {
  for (const g of codes) {
    assert.equal(countries[g].on, true);
    assert.equal(countries[g].name, g);
    assert.equal(countries[g].optional, true);
    assert.deepEqual(countries[g].rail.map(r => r[0]), ['hs', 'main', 'branch', 'heritage']);
  }
  const locations = [
    ['de', 13.405, 52.52], ['fr', 2.35, 48.856], ['fr', 8.737, 41.926],
    ['ch', 7.447, 46.948], ['es', -3.704, 40.417], ['es', -16.25, 28.46],
    ['es', -5.316, 35.889], ['es', -2.94, 35.292],
    ['nl', 4.90, 52.37], ['nl', 5.69, 50.85], ['nl', 4.80, 53.06],
    ['be', 4.35, 50.85], ['be', 4.931, 51.442],
    ['it', 12.49, 41.90], ['it', 13.36, 38.115], ['it', 9.122, 39.224],
    ['ch', 6.143, 46.204], ['fr', 6.235, 46.193],
    ['fr', 7.75, 48.58], ['de', 7.814, 48.573],
  ];
  for (const [g, x, y] of locations) {
    assert.deepEqual(codes.filter(code => countries[code].inside(x, y)), [g], `${g}: ${x},${y}`);
  }
  for (const [x, y] of [[-9.14, 38.72], [6.13, 49.61], [5, 38], [4, 55]]) {
    assert.deepEqual(codes.filter(g => countries[g].inside(x, y)), []);
  }
});

test('three new names and national boundary switch are bilingual and shared', () => {
  for (const [g, zh, en] of [['nl', '荷兰', 'Netherlands'], ['be', '比利时', 'Belgium'], ['it', '意大利', 'Italy']]) {
    assert.ok(app.includes(`'${g}': ['${zh}', '${en}']`));
  }
  assert.ok(app.includes("'row.border': ['国界', 'National boundary']"));
  assert.ok(app.includes("const SHARED_ROWS = ['build', 'stations', 'cities', 'border']"));
  assert.ok(app.includes("set(`${id}@${g}`, rowOn('border', g))"));
  assert.ok(app.includes("European boundaries unavailable; railway data remains usable."));
});

test('executed shared border switches isolate all seven countries and preserve China sea layers', () => {
  const state = app.slice(app.indexOf('  const sharedOff ='), app.indexOf('  // ---- search:'));
  const start = app.indexOf('    for (const id of [\'border-halo\', \'border-casing\', \'border\', \'border-sea-halo\'');
  const end = app.indexOf("    set('hsr-glow'", start);
  const setBorders = new Function('set', 'visible', 'borderCountries', 'BORDER_LINES', 'sharedOff', 'rowOn',
    app.slice(start, end));
  const visible = { border: true };
  const { sharedOff, rowOn } = new Function('visible', state + '\nreturn {sharedOff,rowOn};')(visible);
  const countrySet = new Set(['cn', ...codes]);
  const styles = ['border-halo', 'border-casing', 'border'];
  const run = () => {
    const result = {};
    setBorders((id, on) => { result[id] = on; }, visible, countrySet, styles, sharedOff, rowOn);
    return result;
  };
  for (const g of codes) {
    sharedOff[g + '-border'] = true;
    const result = run();
    for (const other of codes) for (const style of styles) {
      assert.equal(result[style + '@' + other], g !== other);
    }
    for (const id of [...styles, 'border-sea-halo', 'border-sea']) assert.equal(result[id], true);
    delete sharedOff[g + '-border'];
  }
  visible.border = false;
  const result = run();
  for (const id of [...styles, 'border-sea-halo', 'border-sea']) assert.equal(result[id], false);
  for (const g of codes) for (const style of styles) assert.equal(result[style + '@' + g], true);
});

test('seven-country assembled page remains below existing 32 MB capture limit', () => {
  const site = { tiles: true, ...Object.fromEntries(['jp', 'kr', 'uk', ...codes].map(g => [g, true])) };
  const html = execFileSync(process.env.PYTHON || '/private/tmp/cnrail-europe-venv/bin/python',
    ['-B', join(root, 'scripts/build.py'), '--stdout', '--site-json', JSON.stringify(site)],
    { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024, env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } });
  assert.ok(Buffer.byteLength(html) < 32 * 1024 * 1024);
  assert.ok(Buffer.byteLength(html) < 5 * 1024 * 1024);
});
