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
  for (const instance of state.active) {
    if (!validType(instance.trip)) continue;
    if (!instance.trip.renderable) continue;
    renderable++;
    if (!shapeFor(instance.trip)) { pending++; requestShape(instance.trip); continue; }
    const p = position(instance);
    if (!p.coordinate || !state.visible || !['running','dwell'].includes(p.status)) continue;
    features.push({ type: 'Feature', id: instance.key, properties: { key: instance.key, number: instance.trip.number, color: color(instance.trip), chosen: state.selected?.key === instance.key ? 1 : 0, dwell: p.status === 'dwell' ? 1 : 0 }, geometry: { type: 'Point', coordinates: p.coordinate } });
  }
  const map = state.rail.map;
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
    const signature = `${selected.key}/${Boolean(raw)}/${state.visible}`;
    if (state.routeSignature !== signature) {
      state.routeSignature = signature;
      map.getSource('cn-train-route').setData(fc(state.visible && path.length > 1 ? [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: path } }] : []));
    }
    const p = position(selected);
    if (state.following && !['running','dwell'].includes(p.status)) { state.following=false; state.lastDetail=''; }
    if (state.following && p.coordinate && ['running','dwell'].includes(p.status) && Date.now() - state.lastFollow > 4000 && state.visible) {
      state.lastFollow = Date.now();
      map.easeTo({ center: p.coordinate, zoom: Math.max(map.getZoom(), 8), padding: state.rail.padding(), duration: matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 900 });
    }
  } else if (state.routeSignature) {
    state.routeSignature = ''; map.getSource('cn-train-route').setData(fc([]));
  }
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

function choose(instance, focus = true) {
  state.selected = instance; state.following = false; state.lastDetail = ''; state.routeSignature = '';
  requestShape(instance.trip);
  state.rail?.showTab('trains');
  if (matchMedia('(max-width:720px)').matches) state.rail?.sheet.to('mid');
  renderDetail(); renderList(); draw();
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
  const p = position(state.selected);
  if (p.coordinate) state.rail.frame({ point: p.coordinate, zoom: Math.max(state.rail.map.getZoom(),8) },900);
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
      : tr('按需查询所选车次，正晚点与地图位置分开显示。');
    detail.innerHTML = `
      <div class="train-detail-title"><h2>${html(trip.number)}</h2><button type="button" data-action="close" class="train-close" aria-label="${tr('关闭列车详情')}">×</button></div>
      <p class="train-od">${html(stopName(trip, 0))} → ${html(stopName(trip, trip.stops.length - 1))}</p>
      <span class="train-mode">${statusLabel(instance, p)} · ${tr('{date} 始发', { date: fmtDate(instance.serviceDate) })}</span>
      <p class="train-detail-state" id="trainDetailState"></p><div class="train-progress"><i id="trainProgress"></i></div>
      <div class="train-actions">${button('locate', locationLabel, Boolean(p.coordinate))}
        ${button('route', '全程路径', Boolean(trip.renderable && raw))}
        ${button('follow', '跟随', Boolean(p.coordinate && ['running', 'dwell'].includes(p.status)), `aria-pressed="${state.following}"`)}</div>
      <p class="train-muted">${tr(trip.renderable ? '当前位置按时刻表与线路距离估算，未按正晚点修正。' : '此行程缺少可验证的有效路径，只显示时刻表。')} ${!raw && trip.renderable ? tr('路径正在载入。') : ''}</p>
      <table class="train-stop-table"><thead><tr>${['经停站', '图定到达', '图定出发', '正晚点'].map(k => `<th scope="col">${tr(k)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table>
      <div class="train-actions">${button('delay', cached?.loading ? '正在查询…' : cached?.rows ? '刷新逐站正晚点' : '查询逐站正晚点', !cached?.loading)}
        <a class="link" href="https://railgo.dev/" target="_blank" rel="noopener">${tr('来源 RailGo')}</a></div>
      <p class="train-muted">${cached?.error ? html(tr(cached.error)) + ' ' : ''}${html(receipt)}</p>
      <p class="train-muted">${tr('“预计”表示到发预测；“—”表示尚未查询或该站无数据。')}</p>`;
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

function setupMap(rail) {
  state.rail=rail;
  if (mapInstalled) return;
  mapInstalled=true;
  const map=rail.map;
  map.addSource('cn-train-route',{type:'geojson',data:fc([])});
  map.addLayer({id:'cn-train-route-casing',type:'line',source:'cn-train-route',paint:{'line-color':'#111a23','line-width':7,'line-opacity':.8}});
  map.addLayer({id:'cn-train-route',type:'line',source:'cn-train-route',paint:{'line-color':'#f6d8a5','line-width':3,'line-opacity':.86}});
  map.addSource('cn-trains',{type:'geojson',data:fc([])});
  map.addLayer({id:'cn-trains-dot',type:'circle',source:'cn-trains',paint:{'circle-color':['get','color'],'circle-radius':['interpolate',['linear'],['zoom'],3,['case',['==',['get','chosen'],1],6,2.4],8,['case',['==',['get','chosen'],1],8,4],14,['case',['==',['get','chosen'],1],9,5]],'circle-stroke-color':'#152432','circle-stroke-width':1.5,'circle-opacity':.98}});
  map.addLayer({id:'cn-trains-label',type:'symbol',source:'cn-trains',minzoom:7,layout:{'text-field':['get','number'],'text-font':['sans'],'text-size':11,'text-anchor':'bottom','text-offset':[0,-.85],'text-allow-overlap':false,'symbol-sort-key':['case',['==',['get','chosen'],1],-1,1]},paint:{'text-color':'#fff7e7','text-halo-color':'#0b1520','text-halo-width':2}});
  map.addLayer({id:'cn-trains-hit',type:'circle',source:'cn-trains',paint:{'circle-radius':['interpolate',['linear'],['zoom'],3,5,8,10],'circle-opacity':0}});
  map.on('click','cn-trains-hit',event=>{
    const key=event.features?.[0]?.properties?.key, instance=state.active.find(i=>i.key===key);
    if (instance) choose(instance,false);
  });
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

function bindControls() {

$('trainQuery').addEventListener('input',event=>{state.query=event.target.value.trim();state.limit=40;renderList();});
$('trainQuery').addEventListener('focus',()=>{if(matchMedia('(max-width:720px)').matches)state.rail?.sheet.to('large');});
$('trainTypes').addEventListener('click',event=>{const button=event.target.closest('button[data-type]');if(!button)return;state.type=button.dataset.type;state.limit=40;for(const b of $('trainTypes').querySelectorAll('button'))b.setAttribute('aria-pressed',String(b===button));update(true);});
$('trainsVisible').addEventListener('change',event=>{state.visible=event.target.checked;state.routeSignature='';if(!state.visible)state.following=false;syncView();update(true);});
$('trainInView').addEventListener('change',event=>{state.inView=event.target.checked;state.limit=40;renderList();});
$('trainList').addEventListener('click',event=>{const button=event.target.closest('button[data-train]'), instance=button && state.listInstances?.get(button.dataset.train);if(instance)choose(instance);});
$('trainMore').addEventListener('click',()=>{state.limit+=40;renderList();});
$('trainDetail').addEventListener('click',event=>{
  const action=event.target.closest('[data-action]')?.dataset.action;
  if(action==='close'){state.selected=null;state.following=false;state.lastDetail='';update(true);}
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
    for (const id of ['cn-trains-dot', 'cn-trains-label', 'cn-trains-hit', 'cn-train-route', 'cn-train-route-casing']) {
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
  window.addEventListener('rail:language', relabel);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) update(true); });
  const timer = setInterval(() => { if (!document.hidden && inChina()) update(); }, 1000);
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
