import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { EN, translate } from '../src/train-i18n.mjs';
import { panelHTML } from '../src/train-panel.mjs';
import { createEngine } from '../src/train-core.mjs';

const app = readFileSync(new URL('../src/app.html', import.meta.url), 'utf8');
const trains = readFileSync(new URL('../src/trains.mjs', import.meta.url), 'utf8');
const css = readFileSync(new URL('../src/trains.css', import.meta.url), 'utf8');
const site = JSON.parse(readFileSync(new URL('../site.json', import.meta.url), 'utf8'));

function between(text, first, next) {
  const start = text.indexOf(first), end = text.indexOf(next, start);
  assert.ok(start >= 0 && end > start);
  return text.slice(start, end);
}
const syncSource = between(trains, 'function syncView()', 'function relabel()');
function lifecycle({ country = 'cn', world = false, tab = 'trains', finding = false, native = false, engine = null, loading = false, error = null } = {}) {
  const view = { country, world, tab, finding };
  const calls = [], badge = {};
  const state = { rail: { view: () => view, map: { setLayoutProperty: (...args) => calls.push(['visibility', ...args]) } }, engine, loading, error, visible: true, following: true };
  const scope = { state, mapInstalled: false, window: { __app: native },
    inChina: () => !view.world && view.country === 'cn' && !native,
    $: () => badge, setupMap: () => { calls.push(['setup']); scope.mapInstalled = true; },
    loadData: () => { calls.push(['load']); state.loading = true; }, update: () => calls.push(['update']) };
  runInNewContext(syncSource + '\nthis.syncView = syncView;', scope);
  return { ...scope, scope, view, calls, badge };
}

for (const context of [
  {world:true,tab:'route'}, {country:'cn',tab:'route'}, {country:'jp'}, {country:'kr'}, {country:'uk'}, {native:true}, {finding:true},
]) test(`no train data fetched for ${JSON.stringify(context)}`, () => {
  const c = lifecycle(context); c.scope.syncView();
  assert.ok(!c.calls.some(([name]) => name === 'load'));
});

test('opening China trains loads once, not once per view event', () => {
  const c = lifecycle(); c.scope.syncView(); c.scope.syncView();
  assert.equal(c.calls.filter(([name]) => name === 'load').length, 1);
  assert.equal(c.calls.filter(([name]) => name === 'setup').length, 1);
});
test('a failed load is not retried in an unbounded view-event loop', () => {
  const c = lifecycle({error:{key:'failed'}}); c.scope.syncView(); c.scope.syncView();
  assert.equal(c.calls.filter(([name]) => name === 'load').length, 0);
});
test('leaving China hides every overlay layer and stops following', () => {
  const c = lifecycle({engine:{}}); c.scope.mapInstalled = true; c.view.country='jp'; c.scope.syncView();
  assert.equal(c.state.following, false); assert.equal(c.badge.hidden,true);
  const visibility = c.calls.filter(([name]) => name === 'visibility');
  assert.equal(visibility.length,7);
  assert.ok(visibility.every(row => row[3] === 'none'));
});
test('return to China restores an already-loaded overlay without reloading data', () => {
  const c = lifecycle({engine:{},tab:'route'}); c.scope.mapInstalled = true; c.scope.syncView();
  assert.equal(c.calls.filter(([name]) => name === 'load').length, 0);
  assert.ok(c.calls.filter(([name]) => name === 'visibility').every(row => row[3] === 'visible'));
});
test('hidden train checkbox also hides the hit-testing layer', () => {
  const c=lifecycle({engine:{}});c.scope.mapInstalled=true;c.state.visible=false;c.scope.syncView();
  assert.ok(c.calls.some(row=>row[1]==='cn-trains-hit' && row[3]==='none'));
});

// Objects made inside the vm context have that context's prototypes; compare them as plain data.
const plain = value => JSON.parse(JSON.stringify(value));

// The real setupMap, with the marker pictures it computes, on a map that records what it is given.
function installedMap() {
  const images = new Map(), layers = [], sources = [], order = [];
  const map = {
    addSource: id => sources.push(id),
    hasImage: name => images.has(name),
    addImage: (name, image, options) => { order.push(name); images.set(name, { image, options }); },
    addLayer: layer => { order.push(layer.id); layers.push(plain(layer)); },
    on: () => {}, getCanvas: () => ({ style: {} }),
  };
  const scope = { state: {}, mapInstalled: false, fc: features => ({ type: 'FeatureCollection', features }),
    update: () => {}, choose: () => {}, renderDetail: () => {}, renderList: () => {} };
  runInNewContext(between(trains, 'const hull =', 'function renderDataDate()') + '\nthis.setupMap = setupMap;', scope);
  scope.setupMap({ map });
  return { images, layers, sources, order, layer: id => layers.find(layer => layer.id === id) };
}
// The value of ['interpolate', ['linear'], ['zoom'], ...stops] with plain numbers at its stops.
function linear(expression, zoom) {
  assert.deepEqual(expression.slice(0, 3), ['interpolate', ['linear'], ['zoom']]);
  const stops = expression.slice(3);
  if (zoom <= stops[0]) return stops[1];
  for (let i = 2; i < stops.length; i += 2) {
    if (zoom <= stops[i]) return stops[i - 1] + (stops[i + 1] - stops[i - 1]) * (zoom - stops[i - 2]) / (stops[i] - stops[i - 2]);
  }
  return stops.at(-1);
}

test('a click elsewhere on the map lets the chosen train go, a click on a train does not', () => {
  const handlers = [], calls = [];
  let under = [];
  const map = { addSource: () => {}, hasImage: () => true, addImage: () => {}, addLayer: () => {}, getCanvas: () => ({ style: {} }),
    on: (...args) => handlers.push(args), queryRenderedFeatures: (point, options) => { calls.push(plain(options)); return under; } };
  const scope = { state: { selected: null }, mapInstalled: false, fc: features => ({ type: 'FeatureCollection', features }),
    update: () => {}, choose: () => {}, renderDetail: () => {}, renderList: () => {}, unchoose: () => calls.push('unchoose') };
  runInNewContext(between(trains, 'const hull =', 'function renderDataDate()') + '\nthis.setupMap = setupMap;', scope);
  scope.setupMap({ map });
  const anywhere = handlers.filter(args => args[0] === 'click' && typeof args[1] === 'function');
  assert.equal(anywhere.length, 1);
  const click = () => anywhere[0][1]({ point: { x: 1, y: 2 } });
  click();                                         // no train is chosen: nothing to do, the map is not even asked
  assert.deepEqual(calls, []);
  scope.state.selected = { key: 'a' };
  under = [{}]; click();                           // on a train: that train's own handler chooses it
  assert.deepEqual(calls, [{ layers: ['cn-trains-hit'] }]);
  under = []; click();                             // on anything else
  assert.deepEqual(calls.at(-1), 'unchoose');
});

test('the train markers lie between the route and the labels, and every layer is switched with the overlay', () => {
  const { layers } = installedMap();
  assert.deepEqual(layers.map(layer => layer.id), ['cn-train-route-casing', 'cn-train-route',
    'cn-trains-stop', 'cn-trains-dot', 'cn-trains-body', 'cn-trains-label', 'cn-trains-hit']);
  for (const { id } of layers) assert.ok(syncSource.includes(`'${id}'`), `${id} is not hidden with the overlay`);
});

test('moving trains are drawn turned to their heading, standing trains as a dot that is not', () => {
  const { layer } = installedMap();
  for (const id of ['cn-trains-dot', 'cn-trains-body']) {
    const { type, filter, layout } = layer(id);
    assert.equal(type, 'symbol');
    assert.deepEqual(filter, ['has', 'heading']);
    assert.deepEqual(layout['icon-rotate'], ['get', 'heading']);
    assert.equal(layout['icon-rotation-alignment'], 'map');
  }
  const standing = layer('cn-trains-stop');
  assert.deepEqual(standing.filter, ['!', ['has', 'heading']]);
  assert.ok(!('icon-rotate' in standing.layout));
  assert.equal(standing.minzoom, undefined);
  assert.equal(standing.maxzoom, undefined);
});

test('every marker keeps the colour of its train and the dark outline, and none is dropped for another', () => {
  const { layer, images } = installedMap();
  for (const id of ['cn-trains-stop', 'cn-trains-dot', 'cn-trains-body']) {
    const { layout, paint } = layer(id);
    assert.deepEqual(paint['icon-color'], ['get', 'color']);
    assert.equal(paint['icon-halo-color'], '#0b1418');
    assert.equal(layout['icon-allow-overlap'], true);
    assert.equal(layout['icon-ignore-placement'], true);
    assert.ok(images.has(layout['icon-image']), `${id} uses a picture that was never added`);
  }
  assert.equal(layer('cn-trains-label').layout['text-allow-overlap'], false);
  assert.equal(layer('cn-trains-hit').paint['circle-opacity'], 0);
});

test('the pointed dot gives way to the train over half a zoom level with no gap between them', () => {
  const { layer } = installedMap();
  const dot = layer('cn-trains-dot'), body = layer('cn-trains-body');
  assert.equal(dot.maxzoom - body.minzoom, 0.5);
  for (const zoom of [body.minzoom, 8.4, 8.5, 8.6, dot.maxzoom]) {
    const sum = linear(dot.paint['icon-opacity'], zoom) + linear(body.paint['icon-opacity'], zoom);
    assert.ok(Math.abs(sum - 0.98) < 1e-9, `opacity ${sum} at zoom ${zoom}`);
  }
  assert.equal(linear(dot.paint['icon-opacity'], dot.maxzoom), 0);
  assert.equal(linear(body.paint['icon-opacity'], body.minzoom), 0);
});

test('the chosen train is the larger at every zoom, and no marker is too small for its outline', () => {
  const { layer } = installedMap();
  for (const id of ['cn-trains-stop', 'cn-trains-dot', 'cn-trains-body']) {
    const { layout, paint } = layer(id), stops = layout['icon-size'].slice(3);
    for (let i = 0; i < stops.length; i += 2) {
      const [operator, test, chosen, usual] = stops[i + 1];
      assert.equal(operator, 'case');
      assert.deepEqual(test, ['==', ['get', 'chosen'], 1]);
      assert.ok(chosen >= usual * 1.35, `${id} at zoom ${stops[i]}`);
      // The outline is paint['icon-halo-width'] / size texels wide. The distance field holds six, and
      // the blur of its edge (0.84 texels on a plain screen) must fit as well, or the whole square of
      // the picture takes the outline's colour.
      assert.ok(paint['icon-halo-width'] / usual + 0.84 / usual <= 6, `${id} is ${usual} of its size at zoom ${stops[i]}`);
    }
  }
});

test('the marker pictures are distance fields of shapes that point north', () => {
  const { images, order } = installedMap();
  assert.deepEqual([...images.keys()], ['train-pointed', 'train-bullet', 'train-ringed']);
  assert.ok(order.indexOf('train-ringed') < order.indexOf('cn-trains-stop'), 'pictures are added before the layers that use them');
  const shapes = {};
  for (const [name, { image: { width, height, data }, options }] of images) {
    assert.deepEqual(plain(options), { sdf: true, pixelRatio: 2 });
    assert.equal(data.length, width * height * 4);
    const alpha = (i, j) => data[(j * width + i) * 4 + 3], inside = (i, j) => alpha(i, j) > 191;
    const rows = [], columns = [];
    for (let j = 0; j < height; j++) for (let i = 0; i < width; i++) {
      // Mirrored left to right, and empty for a margin of six texels: room for the outline.
      assert.equal(alpha(i, j), alpha(width - 1 - i, j));
      if (Math.min(i, j, width - 1 - i, height - 1 - j) === 0) assert.equal(alpha(i, j), 0, `${name} reaches the edge at ${i},${j}`);
      if (inside(i, j)) {
        assert.ok(Math.min(i, j, width - 1 - i, height - 1 - j) >= 6, `${name} is too near the edge at ${i},${j}`);
        rows.push(j); columns.push(i);
      }
    }
    const widthAt = j => columns.filter((_, k) => rows[k] === j).length;
    shapes[name] = { top: Math.min(...rows), bottom: Math.max(...rows), left: Math.min(...columns), right: Math.max(...columns), middle: height / 2, widthAt, inside };
  }
  const pointed = shapes['train-pointed'], bullet = shapes['train-bullet'], ringed = shapes['train-ringed'];
  // The dot is round about the middle of its picture, where the train is; its point is ahead (up).
  assert.equal(pointed.bottom + 1 - pointed.middle, 7);
  assert.equal(pointed.right - pointed.left + 1, 14);
  assert.ok(pointed.middle - pointed.top >= 11 && pointed.middle - pointed.top <= 13);
  assert.ok(pointed.widthAt(pointed.top) <= 2);
  // The train is about three times as long as wide, its middle on the middle of the picture, with
  // a narrow nose ahead and a wide blunt tail behind.
  const length = bullet.bottom - bullet.top + 1, breadth = bullet.right - bullet.left + 1;
  assert.equal(length, 36); assert.equal(breadth, 12);
  assert.equal(bullet.middle - bullet.top, bullet.bottom + 1 - bullet.middle);
  assert.ok(bullet.widthAt(bullet.top) <= 4 && bullet.widthAt(bullet.top + 4) <= 8);
  assert.ok(bullet.widthAt(bullet.bottom) >= 8 && bullet.widthAt(bullet.bottom - 4) === 12);
  // The standing train: a dot, a gap, a ring.
  const j = ringed.middle, runs = [];
  for (let i = 0; i < 34; i++) if (ringed.inside(i, j) !== ringed.inside(i - 1, j)) runs.push(i);
  assert.equal(runs.length, 6);
});

// The real draw, with the real timetable engine, on a map that keeps what it is given.
function drawn({ time, selected = null }) {
  const metres = 85000;
  const data = {
    schemaVersion: 1, meta: { feedStartDate: '20261012', feedEndDate: '20261012', timezone: 'Asia/Shanghai' },
    stops: [{ id: 'a', name: '甲', lon: 116, lat: 40 }, { id: 'b', name: '乙', lon: 117, lat: 40 }, { id: 'c', name: '丙', lon: 118, lat: 40 }],
    services: { s: ['20261012'] }, shapeFiles: {},
    trips: [
      { id: 'east', number: 'G1', serviceId: 's', shapeId: 'east', renderable: true, stops: [[0, 28800, 28800, 0], [1, 32400, 33000, metres], [2, 36000, 36000, 2 * metres]] },
      { id: 'west', number: 'D2', serviceId: 's', shapeId: 'west', renderable: true, stops: [[2, 28800, 28800, 0], [1, 32400, 33000, metres], [0, 36000, 36000, 2 * metres]] },
      { id: 'south', number: 'K3', serviceId: 's', shapeId: 'south', renderable: true, stops: [[0, 28800, 28800, 0], [1, 36000, 36000, metres]] },
    ],
  };
  const shapes = { east: [[116, 40], [117, 40], [118, 40]], west: [[118, 40], [117, 40], [116, 40]], south: [[116, 40], [116, 39]] };
  const engine = createEngine(data), now = Date.parse(time + '+08:00'), sets = {}, text = {};
  const active = engine.activeAt(now);
  const scope = {
    state: { rail: { map: { getSource: id => ({ setData: value => { sets[id] = plain(value); } }) } }, engine, active, visible: true,
      selected: selected ? active.find(instance => instance.trip.number === selected) : null, following: false },
    mapInstalled: true, inChina: () => true, validType: () => true, failures: new Set(),
    shapeFor: trip => shapes[trip.shapeId], requestShape: () => {}, showError: () => {},
    position: instance => engine.positionAt(instance, now, shapes[instance.trip.shapeId]),
    $: id => (text[id] ||= {}), count: String, tr: (key, values) => key.replace('{n}', values?.n),
  };
  const source = [trains.match(/^const COLORS = .+;$/m)[0], trains.match(/^const fc = .+;$/m)[0], trains.match(/^const color = .+;$/m)[0],
    between(trains, 'function draw()', 'function listItems()'), 'this.draw = draw;'].join('\n');
  runInNewContext(source, scope);
  scope.draw();
  return { features: sets['cn-trains'].features, route: sets['cn-train-route'], text };
}

test('draw gives every running train its heading and its colour', () => {
  const { features, text } = drawn({ time: '2026-10-12T08:30:00' });
  assert.deepEqual(features.map(feature => feature.properties), [
    { key: 'east@20261012', number: 'G1', color: '#f8cf85', chosen: 0, dwell: 0, heading: 90 },
    { key: 'west@20261012', number: 'D2', color: '#88ddd8', chosen: 0, dwell: 0, heading: 270 },
    { key: 'south@20261012', number: 'K3', color: '#d0d8e9', chosen: 0, dwell: 0, heading: 180 },
  ]);
  assert.ok(features.every(feature => feature.geometry.type === 'Point' && feature.geometry.coordinates.length === 2));
  assert.equal(text.trainCount.textContent, '3');
});

test('draw gives a train standing at a station no heading, and marks the chosen train', () => {
  const { features, route } = drawn({ time: '2026-10-12T09:05:00', selected: 'D2' });
  const byNumber = Object.fromEntries(features.map(feature => [feature.properties.number, feature.properties]));
  assert.deepEqual(byNumber.G1, { key: 'east@20261012', number: 'G1', color: '#f8cf85', chosen: 0, dwell: 1 });
  assert.deepEqual(byNumber.D2, { key: 'west@20261012', number: 'D2', color: '#88ddd8', chosen: 1, dwell: 1 });
  assert.equal(byNumber.K3.heading, 180);
  assert.equal(route.features[0].geometry.type, 'LineString');
});

function tabs() {
  const buttons = ['route','trains','lines','layers'].map(id => ({dataset:{tab:id},isConnected:true}));
  const children = buttons.slice();
  for (const b of buttons) b.remove = () => { const i=children.indexOf(b); if(i>=0)children.splice(i,1); b.isConnected=false; };
  const bar={querySelector:()=>buttons[2],querySelectorAll:()=>children,insertBefore(b,anchor){children.splice(children.indexOf(anchor),0,b);b.isConnected=true;},style:{setProperty(k,v){this[k]=v;}}};
  const source=between(app,'  const syncRouteTab = () => {','  // Route state');
  const scope={document:{getElementById:()=>bar},country:'cn',FOREIGN:{jp:{},kr:{},uk:{}},tabButtons:buttons,window:{}};
  runInNewContext(source+'\nthis.run=syncRouteTab;',scope);
  return {scope,children,bar};
}
test('country switches retain route / trains / lines / layers order', () => {
  const t=tabs();t.scope.run();
  for(const country of ['jp','kr','uk']) {t.scope.country=country;t.scope.run();assert.deepEqual(t.children.map(b=>b.dataset.tab),['lines','layers']);}
  t.scope.country='cn';t.scope.run();t.scope.run();
  assert.deepEqual(t.children.map(b=>b.dataset.tab),['route','trains','lines','layers']);
  assert.equal(t.bar.style['--n'],4);
});
test('native app keeps its three original Chinese tabs', () => {
  const t=tabs();t.scope.window.__app={};t.scope.run();
  assert.deepEqual(t.children.map(b=>b.dataset.tab),['route','lines','layers']);
});
test('leaving the trains tab for a foreign country selects Lines', () => {
  const source=app.match(/const onRoute = [^;]+;\s*if \(FOREIGN\[g\] && onRoute\) showTab\('lines'\);/)[0];
  const called=[];
  runInNewContext(source,{shownTab:'trains',FOREIGN:{jp:{}},g:'jp',showTab:k=>called.push(k)});
  assert.deepEqual(called,['lines']);
});
test('the extension does not force Chinese or hide upstream navigation', () => {
  assert.ok(!trains.includes("setLanguage('zh')"));
  assert.ok(!/#toWorld\s*,\s*#lang/.test(css));
  assert.ok(app.includes("let shownTab = 'route'"));
  assert.ok(app.includes('if (!startIn) setWorld();'));
  assert.ok(!app.includes('tileBaseUrl'));
});
test('all panel Chinese copy has an English entry', () => {
  for(const key of [...panelHTML.matchAll(/data-train-(?:t|aria-label|placeholder)="([^"]+)"/g)].map(m=>m[1])) {
    assert.ok(EN[key],`English missing for ${key}`);
  }
});
test('localisation substitutes variables without translating station names', () => {
  assert.equal(translate('图定停站 · {station}',{station:'北京南'},'en'),'Scheduled stop · 北京南');
  assert.equal(translate('图定停站 · {station}',{station:'北京南'},'zh'),'图定停站 · 北京南');
});
test('all dataset URLs stay relative to the installed module including project subpaths', () => {
  for(const module of ['https://example.test/src/trains.mjs','https://example.test/my-fork/src/trains.mjs']) {
    const base=new URL('../data/trains/',module);
    const expected=module.replace('/src/trains.mjs','/data/trains/index.json');
    assert.equal(new URL('index.json',base).href,expected);
  }
});
test('delay API stays manual and the module does not call it during boot', () => {
  const boot=between(trains,'function boot(rail)',"if (window.__rail?.ready)");
  assert.ok(!boot.includes('queryDelay('));
  assert.ok(trains.includes("if(action==='delay')queryDelay();"));
});
