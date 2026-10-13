/** China timetable overlay for Rail Globe. See LICENSE and docs/china-trains.md. */
import { createEngine, chinaDate, clock, formatTime } from './train-core.mjs';
import { getJSON } from './train-data.mjs';
import { translate, localisePanel } from './train-i18n.mjs';
import { panelHTML } from './train-panel.mjs';

const language = () => state.rail?.language() || (/^en/.test(document.documentElement.lang) ? 'en' : 'zh');
const tr = (key, values) => translate(key, values, language());
const count = value => Number(value).toLocaleString(language() === 'en' ? 'en-GB' : 'zh-CN');
const inChina = () => {
  const view = state.rail?.view();
  return Boolean(view && !view.world && view.country === 'cn' && !window.__app);
};

const $ = id => document.getElementById(id);
const BASE = new URL('../data/trains/', import.meta.url);
const COLORS = { G: '#f8cf85', D: '#88ddd8', C: '#b4db9a', other: '#d0d8e9' };
const fc = features => ({ type: 'FeatureCollection', features });
const color = trip => COLORS[/^[GDC]/.test(trip.number) ? trip.number[0] : 'other'];
const html = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const fmtDate = value => /^\d{8}$/.test(String(value)) ? `${value.slice(0,4)}-${value.slice(4,6)}-${value.slice(6,8)}` : String(value || tr('未知'));
const inputTime = ms => new Date(ms + 8 * 3600000).toISOString().slice(0,16);
const timeText = seconds => {
  if (!Number.isFinite(seconds)) return '—';
  const days = Math.floor(seconds / 86400), t = formatTime(seconds % 86400);
  return days ? tr('{time} +{days}日', { time: t, days }) : t;
};
const numericSort = new Intl.Collator('zh-CN', { numeric: true });
const state = { data: null, engine: null, rail: null, active: [], selected: null, type: 'all', query: '', time: null, visible: true, inView: false, following: false, limit: 40, lastList: 0, lastActive: 0, lastFollow: 0, lastDetail: '', loading: false, version: 0 };
const now = () => state.time ?? Date.now();
const shapeCache = new Map(), packs = new Map(), waiting = [], failures = new Set();
let downloads = 0, mapInstalled = false;
let routeLayers = [];          // the layers of a train's route, as the page gave them (setupMap)
const delayCache = new Map();
let lastDelayRequest = 0;

function shapeFor(trip) { return trip.shapeId ? shapeCache.get(trip.shapeId) : null; }
function requestShape(trip) {
  if (!trip.renderable || !trip.shapeId || shapeCache.has(trip.shapeId) || !state.data) return;
  const file = state.data.shapeFiles[trip.shapeId];
  if (!file || !/^shapes\/[a-zA-Z0-9_.-]+\.json$/.test(file) || packs.has(file)) return;
  packs.set(file, 'queued'); waiting.push(file); pump();
}
function pump() {
  while (downloads < 3 && waiting.length) {
    const file = waiting.shift(), version = state.version;
    downloads++; packs.set(file, 'loading');
    getJSON(new URL(file, BASE)).then(data => {
      if (version !== state.version) return;
      for (const [id, shape] of Object.entries(data)) {
        if (shape && typeof shape.p === 'string') shapeCache.set(id, shape);
      }
      packs.set(file, 'ready'); failures.delete(file);
    }).catch(() => { if (version === state.version) { packs.set(file, 'failed'); failures.add(file); } })
      .finally(() => { downloads--; pump(); if (state.engine) update(true); });
  }
}

function validType(trip) {
  if (state.type === 'all') return true;
  if (state.type === 'other') return !/^[GDC]/.test(trip.number);
  return trip.number.startsWith(state.type);
}
function position(instance) { return state.engine.positionAt(instance, now(), shapeFor(instance.trip)); }
function stopName(trip, i) { return state.data.stops[trip.stops[i]?.[0]]?.name || tr('未知站'); }
function inBounds(point) { return !!point && (!state.rail || state.rail.map.getBounds().contains(point)); }
function describe(instance, p) {
  const trip = instance.trip;
  if (p.status === 'scheduled') return tr('{date} {time} 始发', { date: fmtDate(instance.serviceDate), time: timeText(trip.stops[0][2]) });
  if (p.status === 'finished') return tr('图定已终到 · {date} 发车', { date: fmtDate(instance.serviceDate) });
  if (p.status === 'dwell') return tr('图定停站 · {station}', { station: stopName(trip, p.stopIndex ?? p.fromIndex) });
  return `${stopName(trip, p.fromIndex)} → ${stopName(trip, p.toIndex)}`;
}
function statusLabel(instance, p) {
  if (p.status === 'scheduled') return tr('待发车');
  if (p.status === 'finished') return tr('已终到');
  if (!instance.trip.renderable) return tr('缺有效路径');
  return tr(p.status === 'dwell' ? '图定停站' : '运行估算');
}

function draw() {
  if (!state.rail || !state.engine || !mapInstalled || !inChina()) return;
  const features = [];
  let renderable = 0, pending = 0;
  // Zoomed in, the trains in view are moved onto their lines (onLine, below); further out none is, and the map is not asked.
  const map = state.rail.map, view = map.getZoom() >= SNAP_ZOOM ? map.getBounds() : null;
  state.shown = null;            // where the chosen train is drawn: what locating and following it go to
  for (const instance of state.active) {
    if (!validType(instance.trip)) continue;
    if (!instance.trip.renderable) continue;
    renderable++;
    if (!shapeFor(instance.trip)) { pending++; requestShape(instance.trip); continue; }
    const p = position(instance);
    if (!p.coordinate || !state.visible || !['running','dwell'].includes(p.status)) continue;
    const chosen = state.selected?.key === instance.key;
    // Only a moving train has a heading. The marker layers tell the two apart by its presence (see setupMap).
    let coordinate = p.coordinate, heading = p.status === 'running' && Number.isFinite(p.heading) ? p.heading : null;
    const on = view?.contains(coordinate) ? onLine(instance, coordinate, heading) : null;
    if (on) { coordinate = on.coordinate; if (heading !== null && Number.isFinite(on.heading)) heading = on.heading; }
    if (chosen) state.shown = { key: instance.key, coordinate };
    const properties = { key: instance.key, number: instance.trip.number, color: color(instance.trip), chosen: chosen ? 1 : 0, dwell: p.status === 'dwell' ? 1 : 0 };
    if (heading !== null) properties.heading = Math.round(heading) % 360;
    features.push({ type: 'Feature', id: instance.key, properties, geometry: { type: 'Point', coordinates: coordinate } });
  }
  map.getSource('cn-trains').setData(fc(features));
  const matching = state.active.filter(i => validType(i.trip)).length;
  $('trainCount').textContent = count(matching);
  $('trainCoverage').textContent = [
    state.visible ? tr('地图已显示 {n} 列', { n: count(features.length) }) : tr('地图已隐藏列车'),
    tr('{n} 列缺有效路径', { n: count(matching - renderable) }),
    pending ? tr('{n} 列路径载入中', { n: count(pending) }) : '',
    failures.size ? tr('部分路径加载失败，可重试') : '',
  ].filter(Boolean).join(' · ');
  if (failures.size) showError('部分列车路径暂时无法读取。已加载的列车和铁路地图仍可使用。');
  const selected = state.selected;
  if (selected) {
    const raw = shapeFor(selected.trip), path = selected.trip.renderable && raw ? state.engine.tripPath(selected.trip,raw) : [];
    // Once the page has said which lines the path runs along (renderDetail), the route is drawn in its strokes,
    // on the map's own lines; until then as one plain line.
    const parts = state.routeParts?.key === selected.key && state.routeParts.parts.length ? state.routeParts.parts : null;
    const signature = `${selected.key}/${Boolean(raw)}/${state.visible}/${Boolean(parts)}`;
    if (state.routeSignature !== signature) {
      state.routeSignature = signature;
      const lines = parts ? parts.map(part => ({ type: 'Feature', properties: part.props, geometry: { type: 'LineString', coordinates: part.coords } }))
        : [{ type: 'Feature', properties: { kind: 'plain' }, geometry: { type: 'LineString', coordinates: path } }];
      map.getSource('cn-train-route').setData(fc(state.visible && path.length > 1 ? lines : []));
    }
    const p = position(selected);
    if (state.following && !['running','dwell'].includes(p.status)) { state.following=false; state.lastDetail=''; }
    if (state.following && p.coordinate && ['running','dwell'].includes(p.status) && Date.now() - state.lastFollow > 4000 && state.visible) {
      state.lastFollow = Date.now();
      // (the train is followed where it is drawn: on its line, when it was moved there)
      map.easeTo({ center: state.shown?.key === selected.key ? state.shown.coordinate : p.coordinate, zoom: Math.max(map.getZoom(), 8), padding: state.rail.padding(), duration: matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 900 });
    }
  } else if (state.routeSignature) {
    state.routeSignature = ''; map.getSource('cn-train-route').setData(fc([]));
  }
}
// Zoomed in, a train is drawn on its line. Its place comes from the timetable's own drawing of its route, which lies
// tens of metres, here and there a hundred, off the lines of this map, so that from near the marker floats beside
// its track. From zoom 10.5 a train in view is moved to the nearest point of a line within 150 m and turned the way
// the line runs there. The page finds the line among those it draws (src/app.html, snapToLine: a fast train is put
// on a fast line where it has the choice); the chosen train is kept on its own lit route (state.routeParts, see
// renderDetail) wherever that is near. Without either, or with no line near, a train stays where the timetable has it.
const SNAP_ZOOM = 10.5, SNAP_METRES = 150;
function onLine(instance, at, heading) {
  const parts = state.selected?.key === instance.key && state.routeParts?.key === instance.key ? state.routeParts.parts : null;
  return (parts && onParts(parts, at, heading)) || state.rail.snapToLine?.(at, heading, { fast: 'GDCS'.includes(instance.trip.type) }) || null;
}
// The nearest point of a route's parts, and the bearing of the part there: of its two directions the one nearer the heading.
// (A long route has a great many points and this runs once a second: a part's bounds are measured once, and only the
// parts that reach this place are gone along.)
const partBounds = new WeakMap();
function onParts(parts, at, heading) {
  const [x, y] = at, k = Math.cos(y * Math.PI / 180), turned = Number.isFinite(heading), reach = SNAP_METRES / 111320;
  let best = null, least = reach * reach;
  for (const part of parts) {
    const coords = part.coords;
    let box = partBounds.get(part);
    if (!box) {
      box = [Infinity, Infinity, -Infinity, -Infinity];
      for (const point of coords) { box[0] = Math.min(box[0], point[0]); box[1] = Math.min(box[1], point[1]); box[2] = Math.max(box[2], point[0]); box[3] = Math.max(box[3], point[1]); }
      partBounds.set(part, box);
    }
    if (x < box[0] - reach / k || x > box[2] + reach / k || y < box[1] - reach || y > box[3] + reach) continue;
    for (let i = 1; i < coords.length; i++) {
      const ax = (coords[i - 1][0] - x) * k, ay = coords[i - 1][1] - y, dx = (coords[i][0] - coords[i - 1][0]) * k, dy = coords[i][1] - coords[i - 1][1];
      const length = dx * dx + dy * dy, t = length ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / length)) : 0, d = (ax + t * dx) ** 2 + (ay + t * dy) ** 2;
      if (length && d < least) { least = d; best = [coords[i - 1], coords[i], t, Math.atan2(dx, dy) * 180 / Math.PI]; }
    }
  }
  if (!best) return null;
  const [a, b, t, along] = best, back = turned && Math.abs(((along - heading) % 360 + 540) % 360 - 180) > 90;
  return { coordinate: [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])], heading: turned ? (along + (back ? 180 : 0) + 360) % 360 : null };
}

function listItems() {
  let result;
  if (state.query) {
    const q = state.query.toLocaleUpperCase().replace(/\s+/g, '');
    const matches = trip => validType(trip) && (
      trip.number.toLocaleUpperCase().includes(q) || trip.stops.some(s => state.data.stops[s[0]].name.includes(q))
    );
    if (!state.inView) {
      const trips = state.validTrips.filter(matches);
      trips.sort((a,b) => (b.number.toUpperCase() === q) - (a.number.toUpperCase() === q) || numericSort.compare(a.number,b.number));
      return { total:trips.length, items:trips.slice(0,state.limit).map(trip=>state.activeByTrip.get(trip.id)||state.engine.preferredInstance(trip,now())).filter(Boolean) };
    }
    result = state.active.filter(instance=>matches(instance.trip));
    result.sort((a,b) => (b.trip.number.toUpperCase() === q) - (a.trip.number.toUpperCase() === q) || numericSort.compare(a.trip.number,b.trip.number));
  } else {
    result = state.active.filter(i => validType(i.trip));
    result.sort((a,b) => Number(b.trip.renderable) - Number(a.trip.renderable) || numericSort.compare(a.trip.number,b.trip.number));
  }
  if (state.inView) result = result.filter(i => i.trip.renderable && inBounds(position(i).coordinate));
  return {total:result.length,items:result.slice(0,state.limit)};
}
function renderList() {
  if (!state.engine || !inChina()) return;
  const {items,total} = listItems();
  const focusKey = $('trainList').contains(document.activeElement) ? document.activeElement.closest('[data-train]')?.dataset.train : null;
  $('trainListLabel').textContent = tr(state.query ? '匹配车次 · 含非当前在途' : '当前在途车次');
  $('trainListCount').textContent = tr('{n} 列', { n: count(total) });
  $('trainEmpty').hidden = total > 0;
  $('trainMore').hidden = total <= state.limit;
  $('trainList').innerHTML = items.map(instance => {
    const trip = instance.trip, p = position(instance), selected = state.selected?.key === instance.key;
    return `<li><button type="button" data-train="${html(instance.key)}" aria-pressed="${selected}"><span class="train-list-top"><i class="train-kind-dot" style="background:${color(trip)}"></i><b class="train-number">${html(trip.number)}</b><span class="train-status ${['scheduled','finished'].includes(p.status) ? 'inactive' : ''}">${statusLabel(instance,p)}</span></span><span class="train-od">${html(stopName(trip,0))} <span aria-hidden="true">→</span> ${html(stopName(trip,trip.stops.length-1))}</span><span class="train-route-sub">${html(describe(instance,p))}</span></button></li>`;
  }).join('');
  if (focusKey) [...$('trainList').querySelectorAll('[data-train]')].find(button=>button.dataset.train===focusKey)?.focus({preventScroll:true});
  state.listInstances = new Map(items.map(i => [i.key,i]));
  state.lastList = Date.now();
}

// No train is chosen any more: its card closes, its route goes, and the other lines are lit again.
function unchoose() { state.selected = null; state.following = false; state.lastDetail = ''; update(true); announce(); }
function choose(instance, focus = true) {
  state.selected = instance; state.following = false; state.lastDetail = ''; state.routeSignature = '';
  requestShape(instance.trip);
  state.rail?.showTab('trains');
  if (matchMedia('(max-width:720px)').matches) state.rail?.sheet.to('mid');
  renderDetail(); renderList(); draw(); announce();
  if (focus) locate();
  requestAnimationFrame(() => {
    const detail = $('trainDetail'), scroll = $('scroll');
    if (detail.hidden) return;
    scroll.scrollTop += detail.getBoundingClientRect().top - scroll.getBoundingClientRect().top - 8;
    detail.tabIndex = -1; detail.focus({ preventScroll: true });
  });
}
function locate() {
  if (!state.selected || !state.rail) return;
  // (to where the train is drawn, which zoomed in is on its line: see draw)
  const at = state.shown?.key === state.selected.key ? state.shown.coordinate : position(state.selected).coordinate;
  if (at) state.rail.frame({ point: at, zoom: Math.max(state.rail.map.getZoom(),8) },900);
}
function wholeRoute() {
  if (!state.selected || !state.rail) return;
  const raw = shapeFor(state.selected.trip), points = raw ? state.engine.tripPath(state.selected.trip,raw) : [];
  if (points.length < 2) return;
  const b = [Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1])),Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))];
  state.rail.frame({ bounds:[[b[0],b[1]],[b[2],b[3]]] },900);
}

function renderDetail() {
  const detail = $('trainDetail'), instance = state.selected;
  detail.hidden = !instance;
  if (!instance || !state.engine) return;
  const trip = instance.trip, p = position(instance), raw = shapeFor(trip), cached = delayCache.get(instance.key);
  const signature = `${language()}/${instance.key}/${p.status}/${p.fromIndex}/${p.toIndex}/${Boolean(raw)}/${cached?.fetchedAt || ''}/${cached?.loading || ''}/${cached?.error || ''}/${state.following}`;
  if (signature !== state.lastDetail) {
    const focused = detail.contains(document.activeElement)
      ? document.activeElement.closest('[data-action]')?.dataset.action : null;
    state.lastDetail = signature;
    const byCode = new Map((cached?.rows || []).map(row => [row.stationTelecode, row]));
    const byName = new Map((cached?.rows || []).map(row => [row.stationName, row]));
    const rows = trip.stops.map((s, i) => {
      const stop = state.data.stops[s[0]], actual = byCode.get(stop.id.replace(/\/$/, '')) || byName.get(stop.name);
      const current = p.status === 'dwell' ? i === p.fromIndex : p.status === 'running' ? i === p.toIndex : false;
      return `<tr class="${current ? 'current' : i < p.fromIndex ? 'past' : ''}">
        <td>${html(stop.name)}</td><td>${i === 0 ? tr('始发') : html(timeText(s[1]))}</td>
        <td>${i === trip.stops.length - 1 ? tr('终到') : html(timeText(s[2]))}</td>
        <td class="train-delay">${actual ? html(delayText(actual)) : '—'}</td></tr>`;
    }).join('');
    const button = (action, label, enabled = true, extra = '') => `<button type="button" data-action="${action}" class="train-button" ${enabled ? '' : 'disabled'} ${extra}>${tr(label)}</button>`;
    const locationLabel = p.status === 'scheduled' ? '定位始发站' : p.status === 'finished' ? '定位终到站' : !trip.renderable ? '定位车站' : '定位估算位置';
    const receipt = cached?.fetchedAt
      ? tr('查询于北京时间 {date} {time}；显示 {service} 发车行程，结果缓存 5 分钟。', { date: fmtDate(chinaDate(cached.fetchedAt)), time: clock(cached.fetchedAt), service: fmtDate(instance.serviceDate) })
      : '';
    // The lines of the map the route runs along, asked of the page once for a train (its path is
    // the timetable's drawing: the page lays it over its own network) and shown when the answer is there.
    if (trip.renderable && raw && state.linesKey !== `${language()}/${instance.key}` && state.rail?.linesAlong) {
      const key = state.linesKey = `${language()}/${instance.key}`;
      state.rail.linesAlong(state.engine.tripPath(trip, raw), { slow: !'GDCS'.includes(trip.type) }).then(found => {
        if (state.linesKey !== key) return;
        state.lines = { key, rows: found.rows }; state.routeParts = { key: instance.key, parts: found.parts };
        state.lastDetail = ''; renderDetail(); draw();
      }).catch(() => { if (state.linesKey === key) state.linesKey = ''; });
    }
    const along = state.lines?.key === `${language()}/${instance.key}` ? state.lines.rows : [];
    const lines = along.length ? `<div class="train-lines"><p class="train-lines-cap">${tr('经由线路')}</p><ul class="steps">${along.map(row =>
      `<li${row.minor ? ' class="minor"' : ''}><i style="background:${html(row.colour)}"></i><span>${html(row.name)}</span><span class="km">${row.km}\u00a0km</span></li>`).join('')}</ul></div>` : '';
    detail.innerHTML = `
      <div class="train-detail-title"><h2>${html(trip.number)}</h2><button type="button" data-action="close" class="train-close" aria-label="${tr('关闭列车详情')}">×</button></div>
      <p class="train-od">${html(stopName(trip, 0))} → ${html(stopName(trip, trip.stops.length - 1))}</p>
      <span class="train-mode">${statusLabel(instance, p)} · ${tr('{date} 始发', { date: fmtDate(instance.serviceDate) })}</span>
      <p class="train-detail-state" id="trainDetailState"></p><div class="train-progress"><i id="trainProgress"></i></div>
      <div class="train-actions">${button('locate', locationLabel, Boolean(p.coordinate))}
        ${button('route', '全程路径', Boolean(trip.renderable && raw))}
        ${button('follow', '跟随', Boolean(p.coordinate && ['running', 'dwell'].includes(p.status)), `aria-pressed="${state.following}"`)}</div>
      ${!trip.renderable ? `<p class="train-muted">${tr('此行程缺少可验证的有效路径，只显示时刻表。')}</p>` : !raw ? `<p class="train-muted">${tr('路径正在载入。')}</p>` : ''}${lines}
      <table class="train-stop-table"><thead><tr>${['经停站', '图定到达', '图定出发', '正晚点'].map(k => `<th scope="col">${tr(k)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table>
      <div class="train-actions">${button('delay', cached?.loading ? '正在查询…' : cached?.rows ? '刷新逐站正晚点' : '查询逐站正晚点', !cached?.loading)}
        <a class="link" href="https://railgo.dev/" target="_blank" rel="noopener">${tr('来源 RailGo')}</a></div>
      ${cached?.error || receipt ? `<p class="train-muted">${cached?.error ? html(tr(cached.error)) + ' ' : ''}${html(receipt)}</p>` : ''}
      ${cached?.rows ? `<p class="train-muted">${tr('“预计”表示到发预测；“—”表示尚未查询或该站无数据。')}</p>` : ''}`;
    if (focused) {
      const control = detail.querySelector(`[data-action="${focused}"]`);
      if (control && !control.disabled) control.focus({ preventScroll: true });
      else { detail.tabIndex = -1; detail.focus({ preventScroll: true }); }
    }
  }
  const mins = Number.isFinite(p.secondsToNext) ? Math.max(0, Math.ceil(p.secondsToNext / 60)) : null;
  const ending = mins === null ? '' : p.status === 'running' ? tr('图定 {n} 分钟后到站', { n: mins }) : p.status === 'dwell' ? tr('图定 {n} 分钟后发车', { n: mins }) : '';
  $('trainDetailState').textContent = describe(instance, p) + (ending ? ' · ' + ending : '');
  const fraction = Math.max(0, Math.min(1, (now() - instance.startMs) / (instance.endMs - instance.startMs || 1)));
  $('trainProgress').style.width = `${fraction * 100}%`;
}

function delayText(row) {
  const code = String(row.delayStatusCode || ''), prediction = code.endsWith('_PREDICTION') ? tr('预计') : '';
  const amount = row.delayTime == null || row.delayTime === '' ? NaN : Number(row.delayTime);
  if (code === 'MAINTAINCE_MISSING' || code === 'MAINTENANCE_MISSING') return tr('暂无维护');
  if (code.startsWith('ON_TIME')) return prediction + tr('正点');
  if (code.startsWith('EARLY')) return prediction + tr(Number.isFinite(amount) ? '早点 {n}分' : '早点', { n: Math.abs(amount) });
  if (code.startsWith('DELAY')) return prediction + tr(Number.isFinite(amount) ? '晚点 {n}分' : '晚点', { n: Math.abs(amount) });
  return String(row.delayStatus || tr('暂无数据'));
}

async function queryDelay() {
  const instance = state.selected;
  if (!instance) return;
  const cached = delayCache.get(instance.key), at = Date.now();
  if (cached?.loading) return;
  if (cached?.rows && at-cached.fetchedAt < 300000) {
    delayCache.set(instance.key,{...cached,error:'已显示最近 5 分钟内的查询结果，请稍后再刷新。'}); state.lastDetail=''; renderDetail(); return;
  }
  if (at-lastDelayRequest < 15000) {
    delayCache.set(instance.key,{...cached,error:'请间隔至少 15 秒再查询其他车次。'}); state.lastDetail=''; renderDetail(); return;
  }
  lastDelayRequest=at; delayCache.set(instance.key,{...cached,loading:true,error:null}); state.lastDetail=''; renderDetail();
  try {
    const url=new URL('https://rg-api.zenglingkun.cn/api/v2/getTrainDelayAll');
    url.searchParams.set('trainNum',instance.trip.number.split('/')[0]); url.searchParams.set('date',instance.serviceDate);
    const response=await getJSON(url,18000);
    if (response.success !== true || !Array.isArray(response.data)) throw new Error('暂无此行程的正晚点数据');
    const rows=response.data.filter(row=>row && typeof row.stationName==='string');
    delayCache.set(instance.key,{rows,fetchedAt:Date.now(),loading:false,error:rows.length?null:'此行程尚无逐站正晚点数据。'});
  } catch (error) {
    delayCache.set(instance.key,{...cached,loading:false,error:'正晚点查询暂不可用。之前的查询结果（如有）仍保留；请稍后重试或使用 12306 查询。'});
  }
  state.lastDetail=''; renderDetail();
}

function showError(key, values = {}) {
  state.error = { key, values };
  $('trainError').hidden = false;
  $('trainError').querySelector('p').textContent = tr(key, values);
}
function update(force = false) {
  if (!state.rail || !inChina()) return;
  $('trainClock').textContent = `${tr(state.time === null ? '北京' : '查看')} ${fmtDate(chinaDate(now())).slice(5)} ${clock(now())}`;
  $('trainMapBadge').dataset.paused = String(state.time !== null);
  $('trainMapBadge').querySelector('span').textContent = tr(state.time === null ? '列车 · 时刻表估算' : '时刻查看 · 估算位置');
  $('trainMapBadge').hidden = !state.engine || !state.visible;
  if (!state.engine) return;
  if (force || Date.now() - state.lastActive >= 1000) {
    state.active = state.engine.activeAt(now());
    state.activeByTrip = new Map(state.active.map(instance => [instance.trip.id, instance]));
    state.lastActive = Date.now();
  }
  draw(); renderDetail();
  if (force || (Date.now() - state.lastList > 15000 && !$('trainList').contains(document.activeElement))) renderList();
}

// The train markers: a pointed dot from afar, a train seen from above from near, a ringed dot for a
// train that stands. Each shape is a distance from its edge (negative within), in units of which two
// are a CSS pixel at size 1: heading north, x to the right and y to the front of the middle. From it
// a picture is computed for every colour of train, with no canvas and no file: the shape in the colour,
// a dark outline around it, nothing outside. The outline is in the picture, not the layer's (a layer
// draws all its outlines and then all its fills, so trains that overlap ran together into one blob
// inside one outline; owner, 2026-10-13): a train drawn over another covers it, outline and all.
const hull = (x, y, r1, r2, h) => {          // a circle of r1 at the middle, drawn out to a circle of r2 at h ahead
  const b = (r1 - r2) / h, a = Math.sqrt(1 - b * b), k = a * y - b * Math.abs(x);
  return k < 0 ? Math.sqrt(x * x + y * y) - r1 : k > a * h ? Math.sqrt(x * x + (y - h) * (y - h)) - r2 : a * Math.abs(x) + b * y - r1;
};
const slab = (x, y, w, h, r) => {            // a box of half-width w and half-length h, its corners rounded to r
  const u = Math.max(Math.abs(x) - w + r, 0), v = Math.max(Math.abs(y) - h + r, 0);
  return Math.sqrt(u * u + v * v) + Math.min(Math.max(Math.abs(x) - w, Math.abs(y) - h) + r, 0) - r;
};
const MARKERS = {                            // width, height, the coloured shape, and what the outline goes around if not that
  pointed: [26, 38, (x, y) => hull(x, y, 7, .8, 12)],
  bullet: [24, 48, (x, y) => Math.min(slab(x, y + 6, 6, 12, 3.2), hull(x, y - 3, 6, 2.2, 12.8))],
  // (a dot and a ring: the outline goes around the ring and fills the gap between the two, at every size)
  ringed: [32, 32, (x, y) => Math.min(Math.hypot(x, y) - 4.6, Math.abs(Math.hypot(x, y) - 8.7) - 1.3), (x, y) => Math.hypot(x, y) - 10],
};
// A marker's sizes in CSS pixels, as [zoom, usual, chosen], of the measure given first, which is its size 1: the ring's
// and the dot's radius (the circle these replaced went from 2.4 to 4 to 5, chosen 6 to 8 to 9), the train's length.
const SIZES = { ringed: [5, [3, 3.4, 7], [8, 5.6, 10], [14, 7, 12]], pointed: [3.5, [3, 2.4, 6], [8, 4, 8], [9, 4.3, 8.3]], bullet: [18, [8.25, 12.5, 17.5], [9, 14, 19.5], [14, 30, 42]] };
const OUTLINE = '#0b1418';
// The pictures of one shape, one in each of the colours: `density` texels to a unit, the outline `edge` units wide.
// A texel on an edge is covered in part, so the edges are smooth; the colours are not multiplied by the alpha (the
// map does that). The shape is measured once for all its colours.
function markerImages([width, height, shape, body = shape], colours, density, edge) {
  const w = Math.ceil(width * density), h = Math.ceil(height * density), within = new Float32Array(w * h), solid = new Float32Array(w * h);
  const cover = distance => Math.max(0, Math.min(1, .5 - distance * density));
  for (let j = 0, at = 0; j < h; j++) for (let i = 0; i < w; i++, at++) {
    const x = (i + .5 - w / 2) / density, y = (h / 2 - j - .5) / density, from = shape(x, y);
    within[at] = cover(from); solid[at] = cover((body === shape ? from : body(x, y)) - edge);
  }
  const rgb = hex => [1, 3, 5].map(at => parseInt(hex.slice(at, at + 2), 16)), line = rgb(OUTLINE);
  return colours.map(colour => {
    const fill = rgb(colour), data = new Uint8ClampedArray(w * h * 4);
    for (let at = 0; at < w * h; at++) {
      for (let c = 0; c < 3; c++) data[at * 4 + c] = line[c] + (fill[c] - line[c]) * within[at];
      data[at * 4 + 3] = 255 * solid[at];
    }
    return { width: w, height: h, data };
  });
}

function setupMap(rail) {
  state.rail=rail;
  if (mapInstalled) return;
  mapInstalled=true;
  const map=rail.map;
  map.addSource('cn-train-route',{type:'geojson',data:fc([])});
  // A train's route is lit as the page lights a found route (src/app.html, strokeLayers): in strokes, each a part of a line
  // as the map draws it, bolder, in that line's colour and at its place beside the lines it runs with. The page gives the
  // layers; before it has said which lines the route runs along the route is one plain stroke.
  routeLayers = (rail.strokeLayers ? rail.strokeLayers('cn-train-route') : [{id:'cn-train-route',type:'line',source:'cn-train-route',paint:{'line-color':'#d7ecff','line-width':4}}]);
  for (const layer of routeLayers) map.addLayer(layer);
  map.addSource('cn-trains',{type:'geojson',data:fc([])});
  // The style is never replaced (no setStyle anywhere), so the pictures are added once, before the layers that use them:
  // of each shape one for every colour of train, and of each of those one for the usual sizes and one for the chosen
  // train's ('train-bullet-G', 'train-bullet-G-chosen'). A picture is scaled by the map without smoothing down, so each
  // is made for the sizes it is drawn at on this screen: at its largest it is stretched by a quarter at most (the chosen
  // train at zoom 14 stays sharp), at its smallest shrunk to no less than half. Its outline grows with it, and is
  // 1.5 CSS pixels, the stroke the circles had, in the middle of its sizes.
  const ratio=Math.min(3,Math.max(1,map.getPixelRatio?.()||1)), chosen=['==',['get','chosen'],1];
  for (const [shape,[unit,...stops]] of Object.entries(SIZES)) for (const [suffix,which] of [['',1],['-chosen',2]]) {
    const sizes=stops.map(stop=>stop[which]/unit), largest=Math.max(...sizes), density=.4*ratio*largest, edge=3/Math.sqrt(largest*Math.min(...sizes));
    const pictures=markerImages(MARKERS[shape],Object.values(COLORS),density,edge);
    Object.keys(COLORS).forEach((kind,n)=>{const name=`train-${shape}-${kind}${suffix}`;if(!map.hasImage(name))map.addImage(name,pictures[n],{pixelRatio:2*density});});
  }
  // A feature's colour is its train's kind (color, above); a colour no picture was made for is drawn as the other trains are.
  const picture=shape=>['concat',['match',['get','color'],...Object.entries(COLORS).filter(([kind])=>kind!=='other').flatMap(([kind,colour])=>[colour,`train-${shape}-${kind}`]),`train-${shape}-other`],['case',chosen,'-chosen','']];
  // A moving train carries a heading (see draw): it is the pointed dot below zoom 8.25 and the train from 8.75,
  // one fading into the other between. A train without a heading is the ringed dot at every zoom.
  const moving=['has','heading'];
  const sized=(unit,...stops)=>['interpolate',['linear'],['zoom'],...stops.flatMap(([zoom,usual,large])=>[zoom,['case',chosen,large/unit,usual/unit]])];
  // The chosen train is drawn over its neighbours.
  const marker=(id,shape,layer,layout,opacity)=>map.addLayer({id,type:'symbol',source:'cn-trains',...layer,
    layout:{'icon-image':picture(shape),'icon-size':sized(...SIZES[shape]),'icon-allow-overlap':true,'icon-ignore-placement':true,'symbol-sort-key':['get','chosen'],...layout},
    paint:{'icon-opacity':opacity}});
  // Turned with the map, so a marker lies along its track whichever way the map faces. The train also lies
  // flat on the map, as its track does; the dot stays round, as the circle did.
  const turned=pitch=>({'icon-rotate':['get','heading'],'icon-rotation-alignment':'map','icon-pitch-alignment':pitch});
  marker('cn-trains-stop','ringed',{filter:['!',moving]},{},.98);
  marker('cn-trains-dot','pointed',{filter:moving,maxzoom:8.75},turned('viewport'),['interpolate',['linear'],['zoom'],8.25,.98,8.75,0]);
  marker('cn-trains-body','bullet',{filter:moving,minzoom:8.25},turned('map'),['interpolate',['linear'],['zoom'],8.25,0,8.75,.98]);
  // The number stands above its marker, further off as the train grows.
  map.addLayer({id:'cn-trains-label',type:'symbol',source:'cn-trains',minzoom:7,layout:{'text-field':['get','number'],'text-font':['sans'],'text-size':11,'text-anchor':'bottom','text-offset':['interpolate',['linear'],['zoom'],8,['literal',[0,-.85]],14,['literal',[0,-1.4]]],'text-allow-overlap':false,'symbol-sort-key':['case',['==',['get','chosen'],1],-1,1]},paint:{'text-color':'#ffffff','text-halo-color':'rgba(8,14,18,0.9)','text-halo-width':1.4}});
  map.addLayer({id:'cn-trains-hit',type:'circle',source:'cn-trains',paint:{'circle-radius':['interpolate',['linear'],['zoom'],3,5,8,10,14,13],'circle-opacity':0}});
  map.on('click','cn-trains-hit',event=>{
    const key=event.features?.[0]?.properties?.key, instance=state.active.find(i=>i.key===key);
    if (instance) choose(instance,false);
  });
  // A click anywhere else on the map lets the chosen train go, as it lets a chosen line go.
  map.on('click',event=>{if(state.selected && !map.queryRenderedFeatures(event.point,{layers:['cn-trains-hit']}).length)unchoose();});
  map.on('mouseenter','cn-trains-hit',()=>{map.getCanvas().style.cursor='pointer';});
  map.on('mouseleave','cn-trains-hit',()=>{map.getCanvas().style.cursor='';});
  map.on('movestart',e=>{if(e.originalEvent && state.following){state.following=false;state.lastDetail='';renderDetail();}});
  map.on('moveend',()=>{if(state.inView)renderList();});
  update(true);
}

function renderDataDate() {
  if (!state.data) return;
  const meta = state.data.meta;
  $('trainDataDate').textContent = tr('社区数据快照：{release}；数据所载开行日历：{start} 至 {end}，每个车次分别判断开行日。共 {n} 条行程。此页不会自动下载新的整包时刻表。', {
    release: meta.release || meta.feedVersion || '—', start: fmtDate(meta.feedStartDate), end: fmtDate(meta.feedEndDate), n: count(state.data.trips.length),
  });
}
async function loadData() {
  if (state.loading || state.engine) return;
  state.loading = true; state.error = null; $('trainError').hidden = true;
  $('trainCoverage').textContent = tr('正在读取全国列车时刻表…');
  try {
    const data = await getJSON(new URL('index.json', BASE), 45000);
    if (data.schemaVersion !== 1 || !Array.isArray(data.trips) || !data.meta || !data.shapeFiles || !data.services || !data.stops) throw new Error(tr('时刻表格式不受支持'));
    const engine = createEngine(data);
    state.data = data; state.engine = engine; state.active = []; state.lastActive = 0;
    const invalid = new Set(engine.diagnostics.invalidTrips.map(trip => trip.id));
    state.validTrips = data.trips.filter(trip => !invalid.has(trip.id) && data.services[trip.serviceId]?.length);
    renderDataDate();
    const day = String(data.meta.feedVersion || (data.meta.release || '').match(/\d{8}/)?.[0] || '');
    if (/^\d{8}$/.test(day) && Date.now() - Date.parse(`${fmtDate(day)}T00:00:00+08:00`) > 3 * 86400000) {
      showError('时刻表为 {date} 快照，可能已发生调图。请更新数据后使用；当前仍按此快照的开行日历估算。', { date: fmtDate(day) });
    }
    update(true);
  } catch (error) {
    $('trainCoverage').textContent = tr('时刻表尚未载入');
    const reason = error.status === 401 ? tr('请刷新页面以重新验证登录（HTTP 401）') : error.name === 'AbortError' ? tr('网络超时') : error.message;
    showError('列车时刻表载入失败：{reason}。', { reason });
  } finally { state.loading = false; }
}

// The trains have a switch on their own tab and one among the map's layers (src/app.html):
// either sets this, and both are told. From the layers the timetable is fetched as on a first
// visit to the tab. The layers' switch is on only while there are trains to show.
let announced = null, dimmed = false;
function announce() {
  // A chosen train's route is lit as a chosen line is: the page dims every other line for it.
  const lit = Boolean(mapInstalled && state.selected && state.visible && inChina());
  if (lit !== dimmed) {
    dimmed = lit; dispatchEvent(new CustomEvent('rail:dim', { detail: lit }));
    // ... and the other trains are dimmed with the lines (owner, 2026-10-13): the markers and numbers of all but the chosen one.
    const map = state.rail.map, chosen = ['==', ['get', 'chosen'], 1], shown = lit ? ['case', chosen, .98, .32] : .98;
    map.setPaintProperty('cn-trains-stop', 'icon-opacity', shown);
    map.setPaintProperty('cn-trains-dot', 'icon-opacity', ['interpolate', ['linear'], ['zoom'], 8.25, shown, 8.75, 0]);
    map.setPaintProperty('cn-trains-body', 'icon-opacity', ['interpolate', ['linear'], ['zoom'], 8.25, 0, 8.75, shown]);
    map.setPaintProperty('cn-trains-label', 'text-opacity', lit ? ['case', chosen, 1, .4] : 1);
  }
  const visible = Boolean(state.visible && inChina() && (state.engine || state.loading));
  if (visible === announced) return;
  announced = visible;
  dispatchEvent(new CustomEvent('rail:trains-state', { detail: { visible } }));
}
function setVisible(visible, load) {
  state.visible = visible; state.routeSignature = '';
  if ($('trainsVisible')) $('trainsVisible').checked = visible;
  if (!visible) state.following = false;
  if (visible && load && inChina()) {
    if (!mapInstalled) setupMap(state.rail);
    if (!state.engine && !state.loading && !state.error) loadData();
  }
  syncView(); update(true); announce();
}
function bindControls() {

$('trainQuery').addEventListener('input',event=>{state.query=event.target.value.trim();state.limit=40;renderList();});
$('trainQuery').addEventListener('focus',()=>{if(matchMedia('(max-width:720px)').matches)state.rail?.sheet.to('large');});
$('trainTypes').addEventListener('click',event=>{const button=event.target.closest('button[data-type]');if(!button)return;state.type=button.dataset.type;state.limit=40;for(const b of $('trainTypes').querySelectorAll('button'))b.setAttribute('aria-pressed',String(b===button));update(true);});
$('trainsVisible').addEventListener('change',event=>setVisible(event.target.checked,false));
$('trainInView').addEventListener('change',event=>{state.inView=event.target.checked;state.limit=40;renderList();});
$('trainList').addEventListener('click',event=>{const button=event.target.closest('button[data-train]'), instance=button && state.listInstances?.get(button.dataset.train);if(instance)choose(instance);});
$('trainMore').addEventListener('click',()=>{state.limit+=40;renderList();});
$('trainDetail').addEventListener('click',event=>{
  const action=event.target.closest('[data-action]')?.dataset.action;
  if(action==='close')unchoose();
  if(action==='locate')locate();
  if(action==='route')wholeRoute();
  if(action==='follow'){state.following=!state.following;state.lastFollow=0;state.lastDetail='';update(true);}
  if(action==='delay')queryDelay();
});
$('trainTimeToggle').addEventListener('click',()=>{const panel=$('trainTimePanel');panel.hidden=!panel.hidden;$('trainTimeToggle').setAttribute('aria-expanded',String(!panel.hidden));$('trainTimeInput').value=inputTime(now());});
function changeTime(value){
  state.time=value;state.lastActive=0;state.lastDetail='';state.following=false;
  if(state.selected)state.selected=state.engine.preferredInstance(state.selected.trip,now())||null;
  update(true);
}
state.changeTime = changeTime;
$('trainTimeApply').addEventListener('click',()=>{const value=$('trainTimeInput').value,ms=Date.parse(value+'+08:00');if(!value||!Number.isFinite(ms)){showError('请选择有效的北京时间。');return;}changeTime(ms);});
$('trainTimeNow').addEventListener('click',()=>{changeTime(null);$('trainTimeInput').value=inputTime(now());});
$('trainRetry').addEventListener('click',()=>{for(const file of failures)packs.delete(file);failures.clear();state.error=null;$('trainError').hidden=true;if(state.selected)requestShape(state.selected.trip);if(state.engine)update(true);else loadData();});
}

// UI mounts only after Rail Globe is ready. The first visit to the China Trains tab
// creates the overlay and fetches its data; browsing other countries stays unchanged.
function syncView() {
  if (!state.rail) return;
  const here = inChina(), view = state.rail.view();
  if (!here) { state.following = false; state.lastDetail = ''; }
  $('trainMapBadge').hidden = !here || !state.engine || !state.visible;
  if (mapInstalled) {
    for (const id of ['cn-trains-stop', 'cn-trains-dot', 'cn-trains-body', 'cn-trains-label', 'cn-trains-hit', ...routeLayers.map(layer => layer.id)]) {
      state.rail.map.setLayoutProperty(id, 'visibility', here && state.visible ? 'visible' : 'none');
    }
  }
  if (here && view.tab === 'trains' && !view.finding) {
    if (!mapInstalled) setupMap(state.rail);
    if (!state.engine && !state.loading && !state.error) loadData();
  }
  if (here && state.engine) update(true);
}
function relabel() {
  localisePanel($('tab-trains'), language());
  if (state.data) renderDataDate();
  else $('trainCoverage').textContent = tr(state.loading ? '正在读取全国列车时刻表…' : '尚未打开列车功能');
  if (state.error) showError(state.error.key, state.error.values);
  state.lastDetail = ''; update(true);
}
function boot(rail) {
  if (state.rail || window.__app || !$('tab-trains')) return;
  state.rail = rail;
  $('tab-trains').innerHTML = panelHTML;
  const badge = document.createElement('div');
  badge.id = 'trainMapBadge'; badge.className = 'train-map-badge'; badge.hidden = true;
  badge.innerHTML = '<i></i><span></span>'; document.body.append(badge);
  bindControls(); relabel(); syncView();
  window.addEventListener('rail:view', syncView);
  window.addEventListener('rail:view', announce);
  window.addEventListener('rail:trains', event => setVisible(Boolean(event.detail?.visible), true));
  window.addEventListener('rail:language', relabel);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) update(true); });
  const timer = setInterval(() => { announce(); if (!document.hidden && inChina()) update(); }, 1000);     // (the layers' switch follows within a second)
  rail.map.on('remove', () => { clearInterval(timer); window.removeEventListener('rail:view', syncView); window.removeEventListener('rail:language', relabel); });
  // Diagnostics for tests and debugging; this is not a live-position API.
  window.__chinaTrains = {
    get data() { return state.data; }, get active() { return state.active; },
    get selected() { return state.selected; }, get mapReady() { return mapInstalled; },
    setTime(value) {
      if (value !== null && !Number.isFinite(value)) throw new TypeError('Expected an epoch time or null');
      state.changeTime(value);
    },
  };
}
if (window.__rail?.ready) boot(window.__rail);
else window.addEventListener('rail:ready', event => boot(event.detail), { once: true });
