import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { EN, translate } from '../src/train-i18n.mjs';
import { panelHTML } from '../src/train-panel.mjs';

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
  assert.equal(visibility.length,5);
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
