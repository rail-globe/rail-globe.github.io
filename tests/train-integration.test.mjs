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
  const scope = { state, mapInstalled: false, routeLayers: [{ id: 'cn-train-route-rail' }, { id: 'cn-train-route-plain' }], window: { __app: native },
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
const COLORS = { G: '#f8cf85', D: '#88ddd8', C: '#b4db9a', other: '#d0d8e9' };
const setupSource = [trains.match(/^const COLORS = .+;$/m)[0], between(trains, 'const hull =', 'function renderDataDate()'), 'this.setupMap = setupMap;'].join('\n');
function installedMap({ ratio } = {}) {
  const images = new Map(), layers = [], sources = [], order = [];
  const map = {
    addSource: id => sources.push(id),
    hasImage: name => images.has(name),
    addImage: (name, image, options) => { order.push(name); images.set(name, { image, options: plain(options) }); },
    addLayer: layer => { order.push(layer.id); layers.push(plain(layer)); },
    on: () => {}, getCanvas: () => ({ style: {} }),
    ...(ratio ? { getPixelRatio: () => ratio } : null),          // (a map that cannot say is taken for a plain screen)
  };
  const scope = { state: {}, mapInstalled: false, routeLayers: [], fc: features => ({ type: 'FeatureCollection', features }),
    update: () => {}, choose: () => {}, renderDetail: () => {}, renderList: () => {} };
  runInNewContext(setupSource, scope);
  scope.setupMap({ map });
  return { images, layers, sources, order, layer: id => layers.find(layer => layer.id === id) };
}
// The value of the few expressions the marker layers choose a picture with.
function evaluate(expression, properties) {
  if (!Array.isArray(expression)) return expression;
  const [operator, ...args] = expression, value = arg => evaluate(arg, properties);
  if (operator === 'get') return properties[args[0]];
  if (operator === '==') return value(args[0]) === value(args[1]);
  if (operator === 'concat') return args.map(value).join('');
  if (operator === 'case') { for (let i = 0; i + 1 < args.length; i += 2) if (value(args[i])) return value(args[i + 1]); return value(args.at(-1)); }
  if (operator === 'match') { const input = value(args[0]); for (let i = 1; i + 1 < args.length; i += 2) if (args[i] === input) return value(args[i + 1]); return value(args.at(-1)); }
  throw new Error(`an expression this test does not know: ${operator}`);
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
  const scope = { state: { selected: null }, mapInstalled: false, routeLayers: [], fc: features => ({ type: 'FeatureCollection', features }),
    update: () => {}, choose: () => {}, renderDetail: () => {}, renderList: () => {}, unchoose: () => calls.push('unchoose') };
  runInNewContext(setupSource, scope);
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
  assert.deepEqual(layers.map(layer => layer.id), ['cn-train-route',
    'cn-trains-stop', 'cn-trains-dot', 'cn-trains-body', 'cn-trains-label', 'cn-trains-hit']);
  // (the route's layers are the page's: hidden with the rest through the list the page gave)
  for (const { id } of layers) assert.ok(id.startsWith('cn-train-route') ? syncSource.includes('...routeLayers.map(layer => layer.id)') : syncSource.includes(`'${id}'`), `${id} is not hidden with the overlay`);
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

test('every marker is a picture in the colour of its train, with no outline of the layer, and none is dropped for another', () => {
  const { layer, images } = installedMap();
  assert.deepEqual(COLORS, plain(runInNewContext(`(${trains.match(/^const COLORS = (.+);$/m)[1]})`)));
  for (const [id, shape] of [['cn-trains-stop', 'ringed'], ['cn-trains-dot', 'pointed'], ['cn-trains-body', 'bullet']]) {
    const { layout, paint } = layer(id);
    // (a layer draws all its outlines under all its fills: trains that overlapped ran together into one blob)
    assert.deepEqual(Object.keys(paint), ['icon-opacity']);
    assert.equal(layout['icon-allow-overlap'], true);
    assert.equal(layout['icon-ignore-placement'], true);
    assert.deepEqual(layout['symbol-sort-key'], ['get', 'chosen']);
    for (const [kind, color] of Object.entries(COLORS)) for (const chosen of [0, 1]) {
      const name = evaluate(layout['icon-image'], { color, chosen });
      assert.equal(name, `train-${shape}-${kind}${chosen ? '-chosen' : ''}`);
      assert.ok(images.has(name), `${id} uses a picture that was never added: ${name}`);
    }
    // a colour no picture was made for, and a feature with none, are drawn as the other trains are
    assert.equal(evaluate(layout['icon-image'], { color: '#123456', chosen: 0 }), `train-${shape}-other`);
    assert.equal(evaluate(layout['icon-image'], { chosen: 1 }), `train-${shape}-other-chosen`);
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

test('the chosen train is the larger at every zoom, and every picture is made for the sizes it is drawn at', () => {
  for (const ratio of [1, 2, 3]) {
    const { layer, images } = installedMap({ ratio });
    for (const id of ['cn-trains-stop', 'cn-trains-dot', 'cn-trains-body']) {
      const { layout } = layer(id), stops = layout['icon-size'].slice(3);
      const density = chosen => images.get(evaluate(layout['icon-image'], { color: COLORS.G, chosen })).options.pixelRatio;
      for (let i = 0; i < stops.length; i += 2) {
        const [operator, test, chosen, usual] = stops[i + 1];
        assert.equal(operator, 'case');
        assert.deepEqual(test, ['==', ['get', 'chosen'], 1]);
        assert.ok(chosen >= usual * 1.35, `${id} at zoom ${stops[i]}`);
        // Texels of the picture to a pixel of the screen. The map scales a picture without smoothing it down: shrunk
        // to less than half its edges are jagged, stretched by more than a quarter they are soft.
        for (const [which, size] of [[1, chosen], [0, usual]]) {
          const texels = density(which) / (size * ratio);
          assert.ok(texels >= 0.799 && texels <= 2, `${id}${which ? ', chosen,' : ''} at zoom ${stops[i]} on a screen of ${ratio}: ${texels}`);
        }
      }
    }
  }
});

test('the marker pictures are plain pictures, one for each shape and colour, each with its own dark outline', () => {
  for (const ratio of [1, 2]) {
    const { images, order } = installedMap({ ratio });
    assert.deepEqual([...images.keys()].sort(), ['ringed', 'pointed', 'bullet'].flatMap(shape =>
      Object.keys(COLORS).flatMap(kind => [`train-${shape}-${kind}`, `train-${shape}-${kind}-chosen`])).sort());
    assert.ok(order.findLastIndex(name => images.has(name)) < order.indexOf('cn-trains-stop'), 'pictures are added before the layers that use them');
    const hex = value => [1, 3, 5].map(at => parseInt(value.slice(at, at + 2), 16)), dark = hex('#0b1418');
    for (const [name, { image: { width, height, data }, options }] of images) {
      const [, shape, kind, chosen] = name.split('-'), fill = hex(COLORS[kind]);
      // not a distance field for the layer to colour: the colours are the picture's own
      assert.deepEqual(Object.keys(options), ['pixelRatio']);
      assert.equal(options.pixelRatio, images.get(`train-${shape}-G${chosen ? '-chosen' : ''}`).options.pixelRatio);
      if (chosen) assert.ok(options.pixelRatio > images.get(`train-${shape}-${kind}`).options.pixelRatio, `${name} is no finer than the usual picture`);
      assert.equal(data.length, width * height * 4);
      const at = (i, j) => [...data.slice((j * width + i) * 4, (j * width + i) * 4 + 4)];
      const far = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
      // what a texel shows: nothing, the train's colour, or the outline
      const shows = (i, j) => { const [r, g, b, a] = at(i, j); return a < 128 ? 'none' : far([r, g, b], fill) < far([r, g, b], dark) ? 'fill' : 'line'; };
      const filled = [], solid = [];
      for (let j = 0; j < height; j++) for (let i = 0; i < width; i++) {
        const [r, g, b, a] = at(i, j);
        assert.deepEqual(at(width - 1 - i, j), [r, g, b, a], `${name} is not mirrored at ${i},${j}`);
        if (Math.min(i, j, width - 1 - i, height - 1 - j) === 0) assert.equal(a, 0, `${name} reaches the edge at ${i},${j}`);
        // every texel is the train's colour, the outline's, or between the two
        for (const c of [0, 1, 2]) assert.ok(at(i, j)[c] >= dark[c] && at(i, j)[c] <= fill[c], `${name} has another colour at ${i},${j}`);
        if (shows(i, j) === 'fill') { filled.push([i, j]); assert.equal(a, 255); }
        if (a === 255) solid.push([i, j]);
      }
      const box = points => [Math.min(...points.map(p => p[0])), Math.min(...points.map(p => p[1])), Math.max(...points.map(p => p[0])), Math.max(...points.map(p => p[1]))];
      const inner = box(filled), outer = box(solid);
      // the outline is around the colour on every side
      assert.ok(outer[0] < inner[0] && outer[1] < inner[1] && outer[2] > inner[2] && outer[3] > inner[3], `${name} has no outline on a side`);
      // from the middle to the right: the colour, the outline, nothing; and the standing train's dot, gap and ring
      const runs = [], middle = Math.floor(height / 2);
      for (let i = Math.floor(width / 2); i < width; i++) if (shows(i, middle) !== runs.at(-1)) runs.push(shows(i, middle));
      assert.deepEqual(runs, shape === 'ringed' ? ['fill', 'line', 'fill', 'line', 'none'] : ['fill', 'line', 'none'], name);
      const across = j => filled.filter(point => point[1] === j).length, length = inner[3] - inner[1] + 1, breadth = inner[2] - inner[0] + 1;
      if (shape === 'pointed') {
        // a round dot about the middle of the picture, where the train is, with its point ahead (up)
        assert.ok(height / 2 - inner[1] > 1.4 * (inner[3] + 1 - height / 2), `${name} has no point ahead`);
        assert.ok(Math.abs(inner[3] + 1 - height / 2 - breadth / 2) <= 1, `${name} is not round behind`);
        assert.ok(across(inner[1]) < breadth / 2);
      }
      if (shape === 'bullet') {
        // about three times as long as wide, its middle on the middle of the picture, a narrow nose ahead and a blunt tail behind
        assert.ok(length / breadth > 2.6 && length / breadth < 3.4, `${name} is ${length} by ${breadth}`);
        assert.ok(Math.abs(height / 2 - inner[1] - (inner[3] + 1 - height / 2)) <= 1);
        assert.ok(across(inner[1] + Math.round(length / 8)) < 0.75 * breadth, `${name} has no nose`);
        assert.ok(across(inner[3] - Math.round(length / 8)) === breadth, `${name} has no blunt tail`);
      }
      if (shape === 'ringed') assert.ok(Math.abs(length - breadth) <= 1 && Math.abs(height / 2 - inner[1] - (inner[3] + 1 - height / 2)) <= 1);
    }
  }
});

// The real draw, with the real timetable engine, on a map that keeps what it is given. The map is at `zoom` and shows
// what `inView` says; `snapToLine` is the page's function (or none: an older page), `routeParts` the chosen train's lit route.
function drawn({ time, selected = null, zoom = 6, inView = () => true, snapToLine, routeParts, following = false }) {
  const metres = 85000;
  const data = {
    schemaVersion: 1, meta: { feedStartDate: '20261012', feedEndDate: '20261012', timezone: 'Asia/Shanghai' },
    stops: [{ id: 'a', name: '甲', lon: 116, lat: 40 }, { id: 'b', name: '乙', lon: 117, lat: 40 }, { id: 'c', name: '丙', lon: 118, lat: 40 }],
    services: { s: ['20261012'] }, shapeFiles: {},
    trips: [
      { id: 'east', number: 'G1', type: 'G', serviceId: 's', shapeId: 'east', renderable: true, stops: [[0, 28800, 28800, 0], [1, 32400, 33000, metres], [2, 36000, 36000, 2 * metres]] },
      { id: 'west', number: 'D2', type: 'D', serviceId: 's', shapeId: 'west', renderable: true, stops: [[2, 28800, 28800, 0], [1, 32400, 33000, metres], [0, 36000, 36000, 2 * metres]] },
      { id: 'south', number: 'K3', type: 'K', serviceId: 's', shapeId: 'south', renderable: true, stops: [[0, 28800, 28800, 0], [1, 36000, 36000, metres]] },
    ],
  };
  const shapes = { east: [[116, 40], [117, 40], [118, 40]], west: [[118, 40], [117, 40], [116, 40]], south: [[116, 40], [116, 39]] };
  const engine = createEngine(data), now = Date.parse(time + '+08:00'), sets = {}, text = {}, asked = { bounds: 0, eased: [] };
  const active = engine.activeAt(now), chosen = selected ? active.find(instance => instance.trip.number === selected) : null;
  const map = { getSource: id => ({ setData: value => { sets[id] = plain(value); } }), getZoom: () => zoom,
    getBounds: () => { asked.bounds++; return { contains: inView }; }, easeTo: options => asked.eased.push(plain(options)) };
  const scope = {
    state: { rail: { map, padding: () => ({}), ...(snapToLine ? { snapToLine } : null) }, engine, active, visible: true, selected: chosen, following, lastFollow: 0,
      ...(routeParts ? { routeParts: { key: chosen.key, parts: routeParts } } : null) },
    matchMedia: () => ({ matches: true }),
    mapInstalled: true, inChina: () => true, validType: () => true, failures: new Set(),
    shapeFor: trip => shapes[trip.shapeId], requestShape: () => {}, showError: () => {},
    position: instance => engine.positionAt(instance, now, shapes[instance.trip.shapeId]),
    $: id => (text[id] ||= {}), count: String, tr: (key, values) => key.replace('{n}', values?.n),
  };
  const source = [trains.match(/^const COLORS = .+;$/m)[0], trains.match(/^const fc = .+;$/m)[0], trains.match(/^const color = .+;$/m)[0],
    between(trains, 'function draw()', 'function listItems()'), 'this.draw = draw;'].join('\n');
  runInNewContext(source, scope);
  scope.draw();
  return { features: sets['cn-trains'].features, route: sets['cn-train-route'], text, asked, state: scope.state,
    at: number => sets['cn-trains'].features.find(feature => feature.properties.number === number) };
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

// Zoomed in, a train is drawn on its line. Here the page's function moves every train 0.001 degrees north and turns it 3 degrees.
const RAW = { G1: [116.5, 40], D2: [117.5, 40], K3: [116, 39.809] };      // where the timetable has the three trains at 08:30, nearly
const near = (actual, expected) => assert.ok(Math.hypot(actual[0] - expected[0], actual[1] - expected[1]) < 3e-3, `${actual} is not at ${expected}`);
function page() {
  const calls = [];
  return { calls, snapToLine: (at, heading, options) => {
    calls.push(plain([at, heading, options]));
    return { coordinate: [at[0], at[1] + 0.001], heading: heading === null ? null : heading + 3 };
  } };
}

test('zoomed in, draw puts the trains in view where the page says their line is, turned as the line runs', () => {
  const { calls, snapToLine } = page();
  const { features, at } = drawn({ time: '2026-10-12T08:30:00', zoom: 12, snapToLine });
  assert.deepEqual(features.map(feature => feature.properties.heading), [93, 273, 183]);
  for (const [number, raw] of Object.entries(RAW)) {
    const [lng, lat] = at(number).geometry.coordinates, asked = calls.find(call => Math.abs(call[0][0] - lng) < 1e-9);
    near([lng, lat], raw);
    assert.ok(Math.abs(lat - asked[0][1] - 0.001) < 1e-12, `${number} was not moved`);
  }
  // each is asked for once, with the place and heading the timetable gives; a G, D, C or S train is a fast train
  assert.deepEqual(calls.map(call => [Math.round(call[1]), call[2]]), [[90, { fast: true }], [270, { fast: true }], [180, { fast: false }]]);
});

test('a standing train is moved onto its line too, and still has no heading', () => {
  const { calls, snapToLine } = page();
  const { at } = drawn({ time: '2026-10-12T09:05:00', zoom: 12, snapToLine });
  const [[lng, lat], heading, options] = calls[0];
  near([lng, lat], [117, 40]);
  assert.deepEqual([heading, options], [null, { fast: true }]);
  assert.deepEqual(at('G1').geometry.coordinates, [lng, lat + 0.001]);
  assert.deepEqual(at('G1').properties, { key: 'east@20261012', number: 'G1', color: '#f8cf85', chosen: 0, dwell: 1 });
});

test('a page without snapToLine, or a train with no line near, leaves every train where the timetable has it', () => {
  const far = drawn({ time: '2026-10-12T08:30:00' }).features;
  assert.deepEqual(drawn({ time: '2026-10-12T08:30:00', zoom: 12 }).features, far);
  assert.deepEqual(drawn({ time: '2026-10-12T08:30:00', zoom: 12, snapToLine: () => null }).features, far);
  for (const feature of far) near(feature.geometry.coordinates, RAW[feature.properties.number]);
});

test('below zoom 10.5 the page is not asked at all, and from there only for the trains in view', () => {
  for (const zoom of [3, 8.5, 10.49]) {
    const { calls, snapToLine } = page();
    const { features, asked } = drawn({ time: '2026-10-12T08:30:00', zoom, snapToLine });
    assert.deepEqual(calls, []);
    assert.equal(asked.bounds, 0);
    assert.deepEqual(features, drawn({ time: '2026-10-12T08:30:00' }).features);
  }
  const { calls, snapToLine } = page();
  const { features, asked } = drawn({ time: '2026-10-12T08:30:00', zoom: 10.5, snapToLine, inView: point => point[0] > 117 });
  assert.equal(asked.bounds, 1);                       // (the view is read once, not once a train)
  assert.equal(calls.length, 1);
  assert.deepEqual(features.map(feature => feature.properties.heading), [90, 273, 180]);
});

test('the chosen train is kept on its own lit route, and on the page\'s line only where that route is not near', () => {
  // the route as the page lit it: a part 60 m north of the timetable's drawing, written east to west
  const parts = [{ coords: [[118, 40.00054], [117.4, 40.00054]], props: { kind: 'rail' } }, { coords: [[117.4, 40.00054], [116, 40.00054]], props: { kind: 'rail' } }];
  const first = page(), lit = drawn({ time: '2026-10-12T08:30:00', zoom: 12, selected: 'G1', snapToLine: first.snapToLine, routeParts: parts });
  const [lng, lat] = lit.at('G1').geometry.coordinates;
  near([lng, lat], RAW.G1);
  assert.ok(Math.abs(lat - 40.00054) < 1e-9, `${lat} is not on the route`);
  assert.equal(lit.at('G1').properties.heading, 90);           // (the way the train runs, not the way the part is written)
  assert.deepEqual(first.calls.map(call => call[2].fast), [true, false]);        // the two other trains
  assert.deepEqual(plain(lit.state.shown), { key: 'east@20261012', coordinate: [lng, lat] });
  // a route that is 300 m off is not this place's line: the page is asked, as for any train
  const second = page(), off = drawn({ time: '2026-10-12T08:30:00', zoom: 12, selected: 'G1', snapToLine: second.snapToLine, routeParts: [{ coords: [[118, 40.0027], [116, 40.0027]], props: {} }] });
  assert.equal(second.calls.length, 3);
  assert.equal(off.at('G1').properties.heading, 93);
  // and a route does nothing for a train that is not the chosen one, nor below the zoom
  assert.deepEqual(drawn({ time: '2026-10-12T08:30:00', zoom: 9, selected: 'G1', routeParts: parts }).at('G1').geometry.coordinates, drawn({ time: '2026-10-12T08:30:00' }).at('G1').geometry.coordinates);
});

test('following and locating the chosen train go to where it is drawn', () => {
  const { snapToLine } = page();
  const moved = drawn({ time: '2026-10-12T08:30:00', zoom: 12, selected: 'D2', snapToLine, following: true });
  assert.deepEqual(moved.asked.eased.map(options => options.center), [moved.at('D2').geometry.coordinates]);
  assert.equal(moved.asked.eased[0].zoom, 12);
  const plainly = drawn({ time: '2026-10-12T08:30:00', zoom: 9, selected: 'D2', snapToLine, following: true });
  near(plainly.asked.eased[0].center, RAW.D2);
  assert.deepEqual(plainly.asked.eased[0].center, plainly.at('D2').geometry.coordinates);
  // locate: the drawn place of the chosen train if draw left one, else the timetable's
  const framed = [], scope = { state: { selected: { key: 'a' }, shown: { key: 'a', coordinate: [1, 2] }, rail: { frame: (what, ms) => framed.push(plain(what)), map: { getZoom: () => 12 } } },
    position: () => ({ coordinate: [5, 6] }) };
  runInNewContext(between(trains, 'function locate()', 'function wholeRoute()') + '\nthis.locate = locate;', scope);
  scope.locate(); scope.state.shown = { key: 'b', coordinate: [3, 4] }; scope.locate(); scope.state.shown = null; scope.locate();
  assert.deepEqual(framed, [{ point: [1, 2], zoom: 12 }, { point: [5, 6], zoom: 12 }, { point: [5, 6], zoom: 12 }]);
});

// The page's own snapToLine (src/app.html), on a map that returns the lines it is told to.
const M = 111320, COS40 = Math.cos(40 * Math.PI / 180);
const north = metres => 40 + metres / M, east = metres => 116 + metres / (M * COS40);
const lineEW = (layer, metresNorth, type = 'LineString') => ({ layer: { id: layer }, geometry: type === 'LineString'
  ? { type, coordinates: [[115.99, north(metresNorth)], [116.01, north(metresNorth)]] }
  : { type, coordinates: [[[115.9, north(metresNorth) + 1], [115.95, north(metresNorth) + 1]], [[115.99, north(metresNorth)], [116.01, north(metresNorth)]]] } });
const lineNS = (layer, metresEast) => ({ layer: { id: layer }, geometry: { type: 'LineString', coordinates: [[east(metresEast), 39.99], [east(metresEast), 40.01]] } });
function snapper({ features = [], zoom = 12, hidden = [], missing = [] } = {}) {
  const queries = [];
  const map = { getLayer: id => (missing.includes(id) ? undefined : {}), getLayoutProperty: id => (hidden.includes(id) ? 'none' : 'visible'),
    project: () => ({ x: 500, y: 400 }), getZoom: () => zoom,
    queryRenderedFeatures: (box, options) => { queries.push(plain({ box, layers: options.layers })); return features.filter(feature => options.layers.includes(feature.layer.id)); } };
  const scope = { map };
  runInNewContext([app.match(/^  const FAST = .+;$/m)[0], between(app, '    const SNAP = ', '    const lightRoute'), 'this.snapToLine = snapToLine;'].join('\n'), scope);
  return { queries, snap: (heading, options) => plain(scope.snapToLine([116, 40], heading, options)) };
}
const BANDS = ['hsr400', 'hsr350', 'hsr300', 'hsr250', 'hsr200', 'hsr160', 'hsrslow'];

test('snapToLine looks 150 m around, at the railway lines as drawn and at nothing that lights a line', () => {
  const { queries, snap } = snapper({ features: [lineEW('main', 50)] });
  const found = snap(92, {});
  assert.ok(Math.abs(found.coordinate[0] - 116) < 1e-9 && Math.abs(found.coordinate[1] - north(50)) < 1e-9);
  assert.deepEqual(queries[0].layers, [...BANDS, 'main', 'branch']);
  const half = 150 * 512 * 2 ** 12 / (40075017 * COS40);                   // 150 m in pixels at zoom 12: about 10
  assert.ok(half > 10 && half < 10.5);
  for (const [corner, sign] of [[0, -1], [1, 1]]) {
    assert.ok(Math.abs(queries[0].box[corner][0] - (500 + sign * half)) < 1e-9 && Math.abs(queries[0].box[corner][1] - (400 + sign * half)) < 1e-9);
  }
  // further in the box is no wider than 60 px a side, and a line beyond 150 m is not near though the box holds it
  const close = snapper({ features: [lineEW('main', 151)], zoom: 16 });
  assert.equal(close.snap(90, {}), null);
  assert.deepEqual(close.queries[0].box, [[440, 340], [560, 460]]);
  assert.equal(snapper().snap(90, {}), null);
});

test('snapToLine leaves out a class that is switched off, and does not ask the map when none is on', () => {
  const some = snapper({ features: [lineEW('main', 20), lineEW('branch', 60)], hidden: ['main'], missing: ['hsr400'] });
  assert.ok(Math.abs(some.snap(90, {}).coordinate[1] - north(60)) < 1e-9);
  assert.deepEqual(some.queries[0].layers, [...BANDS.slice(1), 'branch']);
  const none = snapper({ features: [lineEW('main', 20)], hidden: [...BANDS, 'main', 'branch'] });
  assert.equal(none.snap(90, {}), null);
  assert.deepEqual(none.queries, []);
});

test('snapToLine gives the line\'s direction, of the two the one the train runs', () => {
  const { snap } = snapper({ features: [lineEW('main', -40)] });
  assert.ok(Math.abs(snap(75, {}).heading - 90) < 1e-6);
  assert.ok(Math.abs(snap(290, {}).heading - 270) < 1e-6);
  assert.equal(snap(359, { fast: true }), null);               // the line runs across this train's way: not its line
  // a standing train has no heading: it takes the nearest line whichever way that runs, and gets no heading
  assert.deepEqual(snapper({ features: [lineNS('main', 30), lineEW('main', 80)] }).snap(null, {}).heading, null);
  assert.ok(Math.abs(snapper({ features: [lineNS('main', 30), lineEW('main', 80)] }).snap(null, {}).coordinate[0] - east(30)) < 1e-9);
  // a moving train passes the line it crosses by, for the line it runs along
  const crossing = snapper({ features: [lineNS('main', 5), lineEW('branch', 80)] }).snap(90, {});
  assert.ok(Math.abs(crossing.coordinate[1] - north(80)) < 1e-9 && Math.abs(crossing.heading - 90) < 1e-6);
});

test('snapToLine puts a fast train on a fast line and another train on a conventional one, where one is nearly as near', () => {
  const pair = (band, main) => snapper({ features: [lineEW('hsr350', band), lineEW('main', main)] });
  const on = (found, metres) => assert.ok(Math.abs(found.coordinate[1] - north(metres)) < 1e-9, `${found.coordinate[1]} is not ${metres} m north`);
  on(pair(45, 20).snap(90, { fast: true }), 45);
  on(pair(45, 20).snap(90, { fast: false }), 20);
  on(pair(45, 20).snap(90), 20);
  on(pair(60, 20).snap(90, { fast: true }), 20);              // 40 m further is not nearly as near
  on(pair(-10, 35).snap(90, { fast: false }), 35);
  on(pair(-10, 50).snap(90, { fast: false }), -10);
  on(snapper({ features: [lineEW('hsr200', 70)] }).snap(90, { fast: false }), 70);       // the only line there is
});

test('snapToLine reads a line in the pieces and parts the map gives it', () => {
  const pieces = [lineEW('main', 90, 'MultiLineString'), lineEW('main', 90), lineEW('main', 30, 'MultiLineString'),
    { layer: { id: 'main' }, geometry: { type: 'Point', coordinates: [116, 40] } },
    { layer: { id: 'main' }, geometry: { type: 'LineString', coordinates: [[116, north(10)], [116, north(10)]] } }];       // (a piece of no length is no line)
  const found = snapper({ features: pieces }).snap(270, {});
  assert.ok(Math.abs(found.coordinate[1] - north(30)) < 1e-9 && Math.abs(found.coordinate[0] - 116) < 1e-9);
  assert.ok(Math.abs(found.heading - 270) < 1e-6);
  // the nearest point of a slanting line is the foot of the perpendicular on the ground, not in degrees
  const slant = { layer: { id: 'main' }, geometry: { type: 'LineString', coordinates: [[east(-100), north(-50)], [east(100), north(150)]] } };
  const foot = snapper({ features: [slant] }).snap(40, {});
  assert.ok(Math.abs(foot.coordinate[0] - east(-25)) < 1e-9 && Math.abs(foot.coordinate[1] - north(25)) < 1e-9);
  assert.ok(Math.abs(foot.heading - 45) < 1e-6);
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
