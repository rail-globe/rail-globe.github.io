import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
const ctx = vm.createContext({});
vm.runInContext(readFileSync(root + 'src/continuous-offset.js', 'utf8') + '\nthis.C = ContinuousOffset;', ctx);
const C = ctx.C;
const f = (co, off = 0, more = {}) => ({ type: 'Feature', properties: { n: 'A', off, ...more },
  geometry: { type: 'LineString', coordinates: co } });
const plain = x => JSON.parse(JSON.stringify(x));
let count = 0;
const test = (name, fn) => { fn(); count++; console.log('PASS', name); };
const near = (a, b, tol = 1e-10) => assert.ok(Math.hypot(a[0] - b[0], a[1] - b[1]) < tol, `${a} != ${b}`);
const co = [[2, 48], [2.01, 48], [2.02, 48]];
test('same-name same-colour Basel network/rid stays independent', () => {
  const input = [f([[7.59, 47.55], [7.59, 47.57]], .5, { n: 'Tram 8', col: '#808080', network: 'BVB', rid: '1,2' }),
    f([[7.59, 47.57], [7.59, 47.59]], -.5, { n: 'Tram 8', col: '#808080', network: 'RVL', rid: '3,4' })];
  const chains = C.prepare(input);
  assert.equal(chains.length, 2);
  assert.notEqual(C.identity(input[0].properties), C.identity(input[1].properties));
});
test('zero seat stays on every source vertex', () => {
  const input = [f(co)], before = JSON.stringify(input);
  const out = C.render(C.prepare(input), 12, 'rail');
  out.features[0].geometry.coordinates.forEach((p, i) => near(p, co[i]));
  assert.equal(JSON.stringify(input), before);
});
test('quintic is not a staircase and has flat end derivatives', () => {
  const spec = { v: 1, base: 0, ramps: [[0, 1, 0, 2]], origin: 0, direction: 1 };
  assert.ok(C.value(spec, .50001) > C.value(spec, .5));
  assert.ok(C.value(spec, .001) < 1e-7);
  assert.ok(2 - C.value(spec, .999) < 1e-7);
});
test('malformed profiles fail before installing a display source', () => {
  const base = { v: 1, base: 0, ramps: [] };
  assert.equal(C.parse(base).direction, 1);
  for (const more of [{ direction: 0 }, { period: -1 }, { origin: Infinity },
    { ramps: [[1, 1, 0, 1]] }, { ramps: [[0, 2, 0, 1], [1, 3, 1, 2]] }]) {
    assert.throws(() => C.parse({ ...base, ...more }), /Invalid offset profile/);
  }
});
test('legacy eased staircase becomes one monotone curve', () => {
  const input = [f([[2, 48], [2.01, 48]], 0), ...[1, 2, 3, 4].map(i =>
    f([[2.01 + (i - 1) * .0005, 48], [2.01 + i * .0005, 48]], i / 10)),
    f([[2.012, 48], [2.03, 48]], .5)];
  const chain = C.prepare(input)[0];
  assert.equal(chain.ramps.length, 1);
  const [lo, hi] = chain.ramps[0];
  const values = [0, .1, .3, .5, .7, .9, 1].map(t => C.properties(chain, chain.members[0], lo + (hi - lo) * t).off);
  assert.ok(values.every((v, i) => !i || v > values[i - 1]));
});
test('op rendered curve has quarter-point adaptive samples', () => {
  const input = [f([[2, 48], [2.02, 48]], 1, { op: JSON.stringify({
    v: 1, base: 0, ramps: [[0, .02, 0, 2]], origin: 0, direction: 1 }) })];
  const out = C.render(C.prepare(input), 12, 'metro');
  assert.ok(out.features[0].geometry.coordinates.length > 8);
});
test('reverse geometry and seat give identical physical display', () => {
  const a = C.render(C.prepare([f(co, .5)]), 13, 'metro').features[0].geometry.coordinates;
  const b = C.render(C.prepare([f([...co].reverse(), -.5)]), 13, 'metro').features[0].geometry.coordinates.reverse();
  assert.equal(a.length, b.length);
  a.forEach((p, i) => near(p, b[i]));
});
test('speed boundaries use one tangent and exact shared endpoint', () => {
  const input = [f([[2, 48], [2.01, 48]], .5, { c: 'main' }),
    f([[2.01, 48], [2.02, 48.002]], .5, { c: 'hsr200' })];
  const out = C.render(C.prepare(input), 13, 'rail');
  near(out.features[0].geometry.coordinates.at(-1), out.features[1].geometry.coordinates[0]);
  assert.notEqual(out.features[0].properties.c, out.features[1].properties.c);
});
test('profile port also interpolates shared weight and group offset', () => {
  const op = JSON.stringify({ v: 1, base: 1, ramps: [] });
  const input = [f([[2, 48], [2.01, 48]], 1, { op, sh: 0, goff: .5 }),
    f([[2.01, 48], [2.02, 48.002]], 1, { op, sh: 1, goff: 0 })];
  for (const z of [12, 13, 16]) {
    const out = C.render(C.prepare(input), z, 'rail');
    near(out.features[0].geometry.coordinates.at(-1), out.features[1].geometry.coordinates[0]);
  }
});
test('partial highlights reuse full-path normals and ramp distances', () => {
  const input = [f([[2, 48], [2.01, 48]], 0),
    f([[2.01, 48], [2.02, 48.01]], 1)];
  const chain = C.prepare(input)[0], member = chain.members[1];
  const props = { ...member.f.properties, kind: 'metro' };
  const stroke = { ...member.f, properties: props };
  C.bindStroke(props, chain, member, 0, member.len / 2);
  for (const z of [12, 13, 16]) {
    const normal = C.render([chain], z, 'metro').features[1].geometry.coordinates;
    const highlight = C.renderStrokes([stroke], z, 'metro').features[0].geometry.coordinates;
    near(normal[0], highlight[0]);
    assert.equal(highlight.at(-1)[0] < normal.at(-1)[0], true);
  }
  assert.ok(!Object.keys(props).some(k => k.includes('context')));
});
test('legacy ramp values agree at every original cut, including reversal', () => {
  const input = [f([[2, 48], [2.01, 48]], 0),
    f([[2.02, 48], [2.01, 48]], -.5),
    f([[2.02, 48], [2.03, 48]], 1)];
  const out = C.render(C.prepare(input), 12, 'metro');
  near(out.features[0].geometry.coordinates.at(-1), out.features[1].geometry.coordinates.at(-1));
  near(out.features[1].geometry.coordinates[0], out.features[2].geometry.coordinates[0]);
});
test('branch ports stay anchored, no guessed continuation', () => {
  const port = [2.01, 48], input = [f([[2, 48], port], .5),
    f([port, [2.02, 48]], 1), f([port, [2.01, 48.01]], -.5)];
  const chains = C.prepare(input);
  assert.equal(chains.length, 3);
  const out = C.render(chains, 12, 'metro');
  near(out.features[0].geometry.coordinates.at(-1), port);
  near(out.features[1].geometry.coordinates[0], port);
  near(out.features[2].geometry.coordinates[0], port);
});
test('closed ring retains original start and continuous periodic seam', () => {
  const ring = [[2, 48], [2.01, 48], [2.01, 48.01], [2, 48.01], [2, 48]];
  const len = .04, op = { v: 1, base: 0, ramps: [[.036, .042, 1, 0]], origin: 0, direction: 1, period: len };
  near([C.value(op, 0), 0], [C.value(op, len), 0]);
  const out = C.render(C.prepare([f(ring, 0, { op: JSON.stringify(op) })]), 13, 'metro');
  near(out.features[0].geometry.coordinates[0], out.features[0].geometry.coordinates.at(-1));
});
test('independent returns continuously, shared keeps exactly eight pixels', () => {
  let previous = Infinity;
  for (let z = 14.5; z <= 16.5; z += .05) {
    const px = C.pixels({ off: 1 }, z, 'rail');
    assert.ok(px <= previous + 1e-9); previous = px;
  }
  assert.equal(C.pixels({ off: 1 }, 16.5, 'rail'), 0);
  assert.equal(C.pixels({ off: 1, sh: 1 }, 19, 'rail'), 8);
  assert.equal(C.pixels({ off: 1, goff: 1, sh: 1 }, 19, 'rail'), 0);
  assert.equal(C.pixels({ off: 1, sh: .5 }, 19, 'rail'), 4);
});
test('light-rail and tram seats stay side by side at every zoom, a quarter of a line width apart, in every country', () => {
  assert.equal(C.pixels({ off: 1, g: 'de', jk: 'urban' }, 4.5, 'metro'), 0.375);
  assert.equal(C.pixels({ off: 1, g: 'de', jk: 'urban' }, 9, 'metro'), 1);
  assert.equal(C.pixels({ off: 1, g: 'de', jk: 'urban' }, 11, 'metro'), 1.75);
  assert.equal(C.pixels({ off: 1, g: 'de', jk: 'urban' }, 12, 'metro'), 2);
  assert.equal(C.pixels({ off: 1, g: 'de', jk: 'urban' }, 13, 'metro'), 2.25);
  assert.equal(C.pixels({ off: 1, g: 'de', jk: 'urban' }, 14, 'metro'), 2.625);
  assert.equal(C.pixels({ off: 1, g: 'de', jk: 'urban' }, 16, 'metro'), 5.625);
  assert.equal(C.pixels({ off: 1, g: 'de', jk: 'subway' }, 12, 'metro'), 5);
  assert.equal(C.pixels({ off: 1, g: 'uk' }, 6, 'metro'), 1.8);
  assert.equal(C.pixels({ off: 1, jk: 'urban' }, 12, 'metro'), 2);                  // China's light rail (no g), as every country's
  assert.equal(C.pixels({ off: 1, g: 'uk', jk: 'urban' }, 12, 'metro'), 2);
  assert.equal(C.pixels({ off: 1, jk: 'subway' }, 12, 'metro'), 5);
  assert.equal(C.pixels({ off: 1, g: 'uk' }, 12, 'metro'), 5);
});
test('rendered light-rail bundles are one thin line width apart, not the metro step', () => {
  // render() once passed pixels() only ap, so Barcelona's T1/T2/T3 stood 5.6 px apart at z13
  for (const z of [11, 13, 16]) {
    const tram = { g: 'es', jk: 'urban', bn: 2 };
    const p = C.render(C.prepare([f(co, .5, tram), f(co, -.5, { n: 'B', ...tram })]), z, 'metro').features;
    const a = C.mercator(p[0].geometry.coordinates[0]), b = C.mercator(p[1].geometry.coordinates[0]);
    assert.ok(Math.abs(Math.hypot(a[0] - b[0], a[1] - b[1]) * 512 * 2 ** z - C.pixels({ off: 1, ...tram }, z, 'metro')) < 1e-7);
  }
});
test('512-pixel scale gives the contract spacing at 12/13/16', () => {
  for (const z of [12, 13, 16]) {
    const p = C.render(C.prepare([f(co, .5), f(co, -.5, { n: 'B' })]), z, 'metro').features;
    const a = C.mercator(p[0].geometry.coordinates[0]), b = C.mercator(p[1].geometry.coordinates[0]);
    assert.ok(Math.abs(Math.hypot(a[0] - b[0], a[1] - b[1]) * 512 * 2 ** z - C.pixels({ off: 1 }, z, 'metro')) < 1e-7);
  }
});
test('display generated once before clipping, not from clipped MVT ends', () => {
  const input = [f([[2, 48], [2.01, 48], [2.02, 48]], 1)];
  const a = C.render(C.prepare(input), 12, 'metro');
  const b = C.render(C.prepare(input), 12, 'metro');
  assert.deepEqual(plain(a), plain(b));
  const html = readFileSync(root + 'src/app.html', 'utf8');
  assert.ok(html.includes("tolerance: 0, buffer: 256, maxzoom: 18"));
  assert.ok(html.includes("offsetFilter(copy, offsetDisplayFilter(spec)"));
  assert.ok(html.includes("property !== 'line-offset'"));
});
test('viewport keeps crossing segments and separates exits from re-entry', () => {
  const input = [f([[1, 48], [2, 48], [3, 48], [3, 49], [2, 49], [1, 49]], .5)];
  const chains = C.prepare(input);
  const full = C.render(chains, 13, 'metro').features[0].geometry.coordinates;
  const out = C.render(chains, 13, 'metro', [1.9, 47.9, 2.1, 49.1]).features;
  assert.equal(out.length, 2);
  for (const feature of out) for (const p of feature.geometry.coordinates) {
    assert.ok(full.some(q => Math.hypot(q[0] - p[0], q[1] - p[1]) < 1e-10));
  }
  assert.ok(out[0].geometry.coordinates.every(p => p[1] < 48.1));
  assert.ok(out[1].geometry.coordinates.every(p => p[1] > 48.9));
  const crossing = C.render(C.prepare([f([[1, 48], [3, 48]], 1)]), 13, 'metro', [1.9, 47.9, 2.1, 48.1]);
  assert.equal(crossing.features.length, 1);
});
test('viewport clipping preserves full-path profile positions and normals', () => {
  const coords = Array.from({ length: 101 }, (_, i) => [2 + i * .0001, 48 + Math.sin(i / 8) * .0001]);
  const input = [f(coords, 1, { op: JSON.stringify({ v: 1, base: 0, ramps: [[0, .012, 0, 2]] }) })];
  const chains = C.prepare(input), before = JSON.stringify(input);
  for (const z of [12, 13, 16]) {
    const full = C.render(chains, z, 'metro').features[0].geometry.coordinates;
    const clipped = C.render(chains, z, 'metro', [2.0045, 47.999, 2.0055, 48.001]).features;
    assert.ok(clipped[0].geometry.coordinates.length < full.length);
    for (const feature of clipped) for (const p of feature.geometry.coordinates) {
      assert.ok(full.some(q => Math.hypot(q[0] - p[0], q[1] - p[1]) < 1e-10));
    }
  }
  assert.equal(JSON.stringify(input), before);
});
test('viewport retains seats shifted into view from just outside', () => {
  const input = [f([[2, 48], [2.01, 48]], 4)];
  const chains = C.prepare(input), z = 13;
  const shifted = C.render(chains, z, 'metro').features[0].geometry.coordinates;
  const y = shifted[0][1];
  assert.ok(Math.abs(y - 48) > .00001);
  assert.equal(C.render(chains, z, 'metro', [2.002, y - .00001, 2.008, y + .00001]).features.length, 1);
});
test('constant-seat shortcut retains the pixel tolerance on long high-latitude segments', () => {
  for (const latitude of [48, 75, 82]) for (const z of [12, 16]) {
    const chain = C.prepare([f([[2, latitude], [2.01, latitude + .04]], .5)])[0];
    const rendered = C.render([chain], z, 'metro').features[0].geometry.coordinates.map(C.mercator);
    const world = 512 * 2 ** z, shift = C.pixels({ off: .5 }, z, 'metro') / world;
    for (let i = 0; i <= 100; i++) {
      const t = i / 100, p = C.mercator([2 + .01 * t, latitude + .04 * t]);
      const normal = chain.normals[0];
      p[0] += normal[0] * shift; p[1] += normal[1] * shift;
      let error = Infinity;
      for (let j = 1; j < rendered.length; j++) {
        const a = rendered[j - 1], b = rendered[j], dx = b[0] - a[0], dy = b[1] - a[1];
        const u = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)));
        error = Math.min(error, Math.hypot(p[0] - a[0] - u * dx, p[1] - a[1] - u * dy) * world);
      }
      assert.ok(error <= .041, `z${z} latitude ${latitude}: ${error}px`);
    }
  }
});
test('indexed profiles agree with linear evaluation at ties, gaps and periodic seams', () => {
  const linear = (p, d) => {
    let at = p.origin + p.direction * d;
    if (p.period) at = ((at % p.period) + p.period) % p.period;
    let v = p.base;
    for (const [lo, hi, a, b] of p.ramps) {
      for (const x of p.period ? [at, at + p.period] : [at]) {
        if (x >= lo && x <= hi) return p.direction * (a + (b - a) * C.smooth((x - lo) / (hi - lo)));
      }
      if (at >= hi) v = b;
    }
    return p.direction * v;
  };
  for (const period of [null, 10]) for (const direction of [1, -1]) {
    const p = { base: 3, ramps: [[1, 2, 0, 1], [2, 3, 2, 3], [5, 6, -2, 1], [9, 11, 1, 0]], origin: .5, direction, period };
    for (let i = -200; i <= 200; i++) assert.ok(Math.abs(C.value(p, i / 8) - linear(p, i / 8)) < 1e-12);
  }
});
test('camera gestures defer work, reuse buffered pans and rebuild once after zoom', () => {
  const html = readFileSync(root + 'src/app.html', 'utf8');
  const camera = html.slice(html.indexOf('    const offsetBounds ='), html.indexOf('    const offsetInstall ='));
  const events = html.slice(html.indexOf('    let offsetTimer ='), html.indexOf('    const EMPTY =', html.indexOf('    let offsetTimer =')));
  let zoom = 13, view = [2, 48, 2.1, 48.1], next = 0, renders = 0, writes = 0;
  const handlers = new Map(), timers = new Map();
  const loaded = { zoom, bounds: [1.97, 47.97, 2.13, 48.13], empty: false, chains: [], sources: new Map([['metro', 'display']]) };
  const scope = {
    map: { getZoom: () => zoom, getBounds: () => ({
      getWest: () => view[0], getSouth: () => view[1], getEast: () => view[2], getNorth: () => view[3] }),
      getSource: () => ({ setData: () => writes++ }), on: (name, fn) => handlers.set(name, fn) },
    offsetLoaded: new Map([['test', loaded]]), offsetDynamic: new Map(), tiles: false,
    offsetSpecs: new Map(), offsetSourceOf: () => null,
    ContinuousOffset: { render: () => { renders++; return { features: [{}] }; } },
    setTimeout: fn => { timers.set(++next, fn); return next; }, clearTimeout: id => timers.delete(id),
  };
  vm.runInNewContext(camera + events, scope);
  const flush = () => { const due = [...timers.values()]; timers.clear(); due.forEach(fn => fn()); };
  view = [2.01, 48.01, 2.11, 48.11];
  handlers.get('moveend')(); flush();
  assert.equal(renders, 0);
  zoom = 12.8; handlers.get('movestart')(); handlers.get('zoom')?.();
  zoom = 12.6; handlers.get('zoom')?.();
  assert.equal(renders, 0);
  handlers.get('moveend')(); handlers.get('movestart')(); flush();
  assert.equal(renders, 0);
  handlers.get('moveend')(); flush();
  assert.equal(renders, 1); assert.equal(writes, 1); assert.equal(loaded.zoom, zoom);
  handlers.get('moveend')(); flush();
  assert.equal(renders, 1);
  view = [2.2, 48.01, 2.3, 48.11];
  handlers.get('moveend')(); flush();
  assert.equal(renders, 2);
});
test('screenshot clock is paced in background and restores native frames in foreground', () => {
  const html = readFileSync(root + 'src/app.html', 'utf8');
  const start = html.indexOf('  if (SHOT) {'), end = html.indexOf('  const map = new maplibregl.Map', start);
  const timers = new Map(), native = new Map(), events = new Map();
  let next = 0, called = 0;
  const window = { requestAnimationFrame: fn => { native.set(++next, fn); return next; },
    cancelAnimationFrame: id => native.delete(id) };
  const document = { hidden: true, addEventListener: (name, fn) => events.set(name, fn) };
  vm.runInNewContext(html.slice(start, end), { SHOT: true, window, document, performance: { now: () => 16 },
    setTimeout: (fn, ms) => { assert.equal(ms, 16); timers.set(++next, fn); return next; },
    clearTimeout: id => timers.delete(id) });
  const a = window.requestAnimationFrame(() => called++);
  window.requestAnimationFrame(() => called++);
  assert.equal(timers.size, 1); assert.equal(native.size, 0); assert.equal(called, 0);
  window.cancelAnimationFrame(a);
  const due = [...timers.values()]; timers.clear(); due.forEach(fn => fn());
  assert.equal(called, 1); assert.equal(timers.size, 0);
  window.requestAnimationFrame(() => called++);
  document.hidden = false; events.get('visibilitychange')();
  assert.equal(timers.size, 0); assert.equal(native.size, 1);
  [...native.values()][0](32);
  assert.equal(called, 2);
});
console.log(`${count} continuous offset contracts passed`);
