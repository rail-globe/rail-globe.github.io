// The page's own costs while it starts and while the map moves (2026-10-21, "现在网页很卡"): each
// piece of src/app.html is run on its own against a stand-in map.
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
const page = readFileSync(root + 'src/app.html', 'utf8');
const between = (from, to) => {
  const start = page.indexOf(from);
  assert.ok(start >= 0, from);
  const end = page.indexOf(to, start);
  assert.ok(end > start, to);
  return page.slice(start, end);
};
let count = 0;
const test = (name, fn) => { fn(); count++; console.log('PASS', name); };

test('the page\'s layers, sources and filters skip MapLibre\'s whole-style check', () => {
  const calls = [];
  const map = {
    style: { addLayer: (...a) => calls.push(['addLayer', ...a]), addSource: (...a) => calls.push(['addSource', ...a]) },
    _update: () => map,
    setFilter: (...a) => calls.push(['setFilter', ...a]),
    setPaintProperty: (...a) => calls.push(['setPaintProperty', ...a]),
    setLayoutProperty: (...a) => calls.push(['setLayoutProperty', ...a]),
  };
  vm.runInNewContext(between('  const unchecked = { validate: false };', '\n  // Until the viewer moves the map'), { map });
  map.addLayer({ id: 'a' }, 'b');
  map.addSource('s', { type: 'geojson' });
  map.setFilter('a', ['==', 1, 1]);
  map.setPaintProperty('a', 'line-color', '#fff', { other: 1 });
  map.setLayoutProperty('a', 'visibility', 'none');
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    ['addLayer', { id: 'a' }, 'b', { validate: false }],
    ['addSource', 's', { type: 'geojson' }, { validate: false }],
    ['setFilter', 'a', ['==', 1, 1], { validate: false }],
    ['setPaintProperty', 'a', 'line-color', '#fff', { other: 1, validate: false }],
    ['setLayoutProperty', 'a', 'visibility', 'none', { validate: false }],
  ]);
});

test('a layer\'s exclusion of the lines drawn with continuous offsets is a lookup', () => {
  const scope = { offsetKeyExpr: ['get', 'k'] };
  vm.runInNewContext(between('    const offsetExcluded =', '    const offsetDisplayFilter') + 'this.f = offsetExcluded;', scope);
  assert.deepEqual(JSON.parse(JSON.stringify(scope.f({}, ['a', 'b']))), ['match', ['get', 'k'], ['a', 'b'], false, true]);
  assert.deepEqual(JSON.parse(JSON.stringify(scope.f({ filter: ['has', 'x'] }, ['a']))),
    ['all', ['has', 'x'], ['match', ['get', 'k'], ['a'], false, true]]);
  assert.equal(scope.f({}, []), true);                        // (a match needs a label)
  assert.ok(!/\['in', offsetKeyExpr/.test(page));
});

test('an offset line keeps its ends and every point that shows at its zoom', () => {
  const ctx = vm.createContext({});
  vm.runInContext(readFileSync(root + 'src/continuous-offset.js', 'utf8') + '\nthis.ContinuousOffset = ContinuousOffset;', ctx);
  vm.runInContext(between('    const SLIM_PX = .3;', '    const offsetRender =') + 'this.slim = slim; this.SLIM_PX = SLIM_PX;', ctx);
  const line = [];
  for (let i = 0; i <= 200; i++) line.push([116 + i * 1e-4, 40 + 2e-3 * Math.sin(i / 20)]);
  for (const zoom of [3, 8, 12, 16]) {
    const display = ctx.slim({ features: [{ geometry: { type: 'LineString', coordinates: line.map(p => [...p]) } }, { properties: {} }] }, zoom);
    const kept = display.features[0].geometry.coordinates, world = 512 * 2 ** zoom, M = ctx.ContinuousOffset.mercator;
    assert.deepEqual(kept[0], line[0]);
    assert.deepEqual(kept.at(-1), line.at(-1));
    // every point left out lies within SLIM_PX of the line kept
    const px = kept.map(p => M(p).map(v => v * world));
    for (const p of line.map(q => M(q).map(v => v * world))) {
      let best = Infinity;
      for (let i = 1; i < px.length; i++) {
        const [a, b] = [px[i - 1], px[i]], dx = b[0] - a[0], dy = b[1] - a[1], l = dx * dx + dy * dy;
        const t = l ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l)) : 0;
        best = Math.min(best, Math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1]));
      }
      assert.ok(best <= ctx.SLIM_PX + 1e-9, `${best} px at z${zoom}`);
    }
    if (zoom <= 8) assert.ok(kept.length < line.length / 4, `z${zoom}: ${kept.length} of ${line.length}`);
  }
});

test('a file of offsets waits for the zoom its layers show from', () => {
  const specs = new Map([['a', { minzoom: 6 }], ['b', { minzoom: 4.5 }], ['c', {}]]);
  const source = new Map([['a', 'cn:metro'], ['b', 'cn:metro'], ['c', 'cn:conv']]);
  const scope = { offsetSpecs: new Map([...specs].map(([id, s]) => [id, { ...s, id }])), offsetSourceOf: s => source.get(s.id) };
  vm.runInNewContext(between('    const offsetFrom =', '    const offsetInstall =') + 'this.f = offsetFrom;', scope);
  assert.equal(scope.f('cn:metro'), 4.5);
  assert.equal(scope.f('cn:conv'), 0);
  assert.equal(scope.f('de:metro'), 0);                      // no layer of its own yet: as before, not held back
  assert.ok(/if \(offsetPending\.has\(key\) \|\| map\.getZoom\(\) < offsetFrom\(key\) - \.5\) continue;/.test(page));
  assert.ok(/if \(zoom < offsetFrom\(key\) - 1\) continue;/.test(page));
});

test('the capsules are worked out as the zoom changes, not on every frame of a move', () => {
  let zoom = 9, view = [100, 13, 100.1, 13.1], now = 0, next = 0, computed = 0, written = 0;
  const handlers = new Map(), timers = new Map();
  const scope = {
    map: { getZoom: () => zoom, getBounds: () => ({ getWest: () => view[0], getSouth: () => view[1], getEast: () => view[2], getNorth: () => view[3] }),
      getSource: () => ({ setData: () => written++ }), on: (name, fn) => handlers.set(name, fn) },
    RAIL_CAPSULES_FROM: 11, EMPTY: { type: 'FeatureCollection', features: [] },
    inBox: ([x, y], b) => x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3],
    capsuleData: () => { computed++; return { features: [{}] }; },
    performance: { now: () => now },
    setTimeout: fn => { timers.set(++next, fn); return next; }, clearTimeout: id => timers.delete(id),
    refreshCapsules: null,
  };
  vm.runInNewContext(between('    const CAPSULES_FROM =', "    map.on('moveend', capsuleMove);") + "map.on('moveend', capsuleMove); this.refresh = refreshCapsules;", scope);
  const move = () => { now += 16; handlers.get('move')(); };
  const flush = () => { const due = [...timers.values()]; timers.clear(); due.forEach(fn => fn()); };
  for (let i = 0; i < 30; i++) move();                       // below z11 there are none
  assert.equal(computed, 0);
  assert.equal(written, 1);                                   // (emptied once)
  zoom = 13; move();
  assert.equal(computed, 1);
  for (let i = 0; i < 10; i++) { view = view.map((v, k) => v + (k % 2 ? 0 : 1e-3)); move(); }   // (a quarter of the view is .025)
  assert.equal(computed, 1);                                  // a pan within the box worked out
  view = [101, 13, 101.1, 13.1]; now += 200; move();
  assert.equal(computed, 2);                                  // out of it
  for (let i = 0; i < 30; i++) { zoom += .01; move(); }       // a zoom: at most every CAPSULE_MS
  assert.ok(computed <= 2 + Math.ceil(30 * 16 / 100) + 1, `${computed}`);
  const before = computed;
  now += 200; handlers.get('moveend')(); flush();
  assert.ok(computed <= before + 1);
  handlers.get('moveend')();
  const settled = computed;
  handlers.get('moveend')(); flush();
  assert.equal(computed, settled);                            // nothing changed: nothing to do
  scope.refresh();
  assert.equal(computed, settled + 1);                        // a switch or new data: at once
  assert.ok(!/map\.on\('move',\s*refreshCapsules\)/.test(page));
});

console.log(`${count} page speed contracts passed`);
