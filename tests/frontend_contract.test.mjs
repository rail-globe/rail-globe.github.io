// Deterministic contract regression for the country-switch frontend (reads the built index.html).
// Not a runtime DOM test (no jsdom/maplibre here); it asserts the wiring each required behavior
// depends on, so a future edit that drops a hook fails the build check. The search is the
// exception: it is two plain functions that need no page, so they are run, on a small made-up
// network and on the data files.
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(join(root, 'index.html'), 'utf8');

const checks = [
  // 1. route tab keeps three tabs but Japan gets an empty state, not the Chinese OD form
  ['route empty-state container', /id="routeCn"/],
  ['route JP empty state', /id="routeJp"/],
  ['route -> lines button', /id="routeGoLines"/],
  ['route empty-state toggle', /syncRouteTab\s*\(/],
  // 2. setCountry clears route state and re-syncs the route empty state
  ['setCountry cleans route', /if \(routeCleanup\) routeCleanup\(\)/],
  ['setCountry syncs route tab', /syncRouteTab\(\);/],
  // 3. switching to a country abroad off the route tab moves to lines (no dead tab), but 路线 still opens empty
  ['auto-switch route->lines abroad', /FOREIGN\[g\] && onRoute\) showTab\('lines'\)/],
  ['route empty state names the country', /routeJpNote'\)\.textContent = `\$\{c\.name\}暂不支持线路网寻路/],
  // 4. the Chinese rows give way to the rows of the country abroad
  ['Chinese-only rows hidden abroad', /hideAbroad = \{ metro: true/],
  ['Chinese band rows hidden abroad', /for \(const id of \[\.\.\.FAST, 'unknown'\]\) if \(rowEls\[id\]\) rowEls\[id\]\.hidden = !cn;/],
  // 5. a station abroad does not offer 设为出发/到达
  ['station abroad blocked', /f\.properties\.g == null \|\| FOREIGN\[f\.properties\.g\]/],
  // 6. countries abroad are entries of one configuration: classes, layers, rows and buttons come from it
  ['countries abroad are configured, not branched on', /const FOREIGN = \{/],
  ['no branch on one country', /^(?![\s\S]*country === 'jp')(?![\s\S]*country === 'uk')/],
  ['Japan: its classes', /rail: \[\['shinkansen', '新干线'\], \['jr', 'JR在来'\], \['private_big', '大手私铁'\],\s+\['private_local', '地方私铁·第三セク', \['third_sector', 'private_local'\]\], \['unknown', '其他'\]\]/],
  ['Japan: its metro classes', /metro: \[\['subway', '地下铁'\], \['urban', '城市轨道'\]\]/],
  ['UK: its classes', /rail: \[\['hs', '高速铁路'\], \['main', '干线铁路'\], \['branch', '支线铁路'\], \['heritage', '遗产铁路'\]\]/],
  ['UK: its metro classes', /metro: \[\['subway', '地铁'\], \['urban', '轻轨·有轨电车'\]\]/],
  ['UK in the country switch', /data-g="uk"/],
  ['Korea in the country switch', /data-g="kr"/],
  ['Korea: its classes, two of them fast', /fast: \['hs', 'semi'\][\s\S]{0,200}rail: \[\['hs', '高速铁路'\], \['semi', '准高速铁路'\], \['main', '干线铁路'\], \['branch', '支线铁路'\]\]/],
  ['the country switch has a row of its own', /<p class="facts" id="facts">[^\n]*\n\s*<div class="segmented mini" id="country"/],
  ['the thumb reaches a fourth and fifth choice', /nth-of-type\(5\)[^{]*\{ --i: 4; \}/],
  ['a country that is off leaves the switch', /b\.dataset\.g !== 'cn' && !FOREIGN\[b\.dataset\.g\]\) b\.remove\(\)/],
  // 6b. one colour rule: the band of the design speed, else the line's own colour, else neutral; never the company's
  ['a row per speed band the country has', /bands\[kind\]\.map\(band => \(\{ id: `\$\{g\}-\$\{kind\}-\$\{band\}`, label, band \}\)\)/],
  ['the bands come from the data', /FAST\.filter\(band => rail\.features\.some\(f => f\.properties\.c === band && jkOf\(g, kind\)\.includes\(f\.properties\.jk\)\)\)/],
  ['a layer per band, in the band colour', /'line-color': col\(band\), 'line-width': lineW\(abroadW\.fast\)/],
  ['other lines: own colour, else neutral', /'line-color': \['coalesce', \['get', 'lc'\], col\('main'\)\]/],
  ['colour note says no company colours', /不按公司上色/],
  ['no company list, no operator colours', /^(?![\s\S]*opList)(?![\s\S]*OP_COLOR)(?![\s\S]*_operators)/],
  // 6c. every country is on the map all the time; the country of the card only decides whose
  // switches the card shows (2026-10-09, replacing "the other countries are hidden")
  ['layers abroad answer to their own switch only', /for \(const id of Object\.keys\(abroadVisible\)\) \{\s+set\(id, abroadVisible\[id\]\);/],
  ['China layers answer to China switches only', /for \(const id of \[\.\.\.FAST, 'main', 'branch'\]\) set\(id, visible\[id\]\);/],
  ['no layer is hidden for being in another country', /^(?![\s\S]*cn && visible)(?![\s\S]*startsWith\(country \+ '-'\) && abroadVisible)(?![\s\S]*countryFilter)/],
  ['shared layers show the countries whose switch is on', /const where = \['any', \.\.\.countries\.map\(g => \(g === 'cn' \? NOT_ABROAD : \['==', \['get', 'g'\], g\]\)\)\];/],
  ['stations: one switch per country', /among\('stations', withStations, /],
  ['lines being built: one switch per country', /among\('build', everyCountry\.filter\(g => rowOn\('build', g\)/],
  ['a shared row changes the switch of the country of the card', /if \(SHARED_ROWS\.includes\(c\.id\) && country !== 'cn'\) sharedOff\[country \+ '-' \+ c\.id\] = !e\.target\.checked;/],
  ['a shared row shows the switch of the country of the card', /box\.checked = rowOn\(id, country\);/],
  ['the rows are still those of the country of the card', /rowEls\[id\]\.hidden = !id\.startsWith\(country \+ '-'\);/],
  ['a selection dims the lines abroad too', /for \(const id of abroadBand\) map\.setPaintProperty\(id, 'line-opacity', sel \? 0\.4 : 1\);/],
  ['a tap on a line of another country moves the card there', /if \(abroad\(f\.properties\.g\) !== country\) setCountry\(abroad\(f\.properties\.g\), false\);/],
  ['dragging the map does not change the country', /^(?![\s\S]*map\.on\('(?:move|moveend|drag|dragend|zoomend)'[^\n]*setCountry)/],
  // 6d. yards and depots: one switch for every country, each country fetched when first seen
  ['yards and depots: one switch, no country filter', /for \(const id of \['yards', 'depots', 'depot-labels'\]\) set\(id, visible\.yards\);\s+loadYards\(\);/],
  ['yards and depots are not fetched at start', /^(?![\s\S]*\.map\(pre => getJSON\()/],
  ['yards wait for the switch and the zoom', /if \(!visible\.yards \|\| map\.getZoom\(\) < YARD_ZOOM - 0\.5\) return;/],
  ['yards of the countries in view', /\.map\(\(\[lng, lat\]\) => countryAt\(lng, lat\)\);/],
  ['a country is fetched once', /if \(!g \|\| yardsAsked\.has\(g\)\) continue;\s+yardsAsked\.add\(g\);/],
  ['yards of every country: China without a prefix', /getJSON\(`data\/\$\{g === 'cn' \? '' : g \+ '_'\}\$\{kind\}\.geojson`\)/],
  ['yards are looked for when the map stops', /map\.on\('moveend', \(\) => loadYards\(\)\);/],
  ['a picture gets every country at once', /if \(SHOT\) loadYards\(true\);/],
  ['a start-up failure gives its reason first', /window\.__bootError = stack\.includes\(reason\) \? stack\.slice\(stack\.indexOf\(reason\)\) : reason \+/],
  ['the yards row stays abroad', /^(?![\s\S]*yards: true)/],
  ['setCountry updates the colour section', /colourSection\(g\);/],
  // 6e. one search field for everything (2026-10-09): first thing in the card, its results take
  // the place of the tabs, the lines tab has no search of its own, the route fields use the same function
  ['the search field is the first thing in the card', /<div class="grabber" aria-hidden="true"><\/div>\s+<label class="searchbar">[\s\S]{0,400}<input id="query" type="search"/],
  ['three search inputs: the field and the two route fields', page => (page.match(/type="search"/g) || []).length === 3],
  ['the lines tab has no search of its own', /^(?![\s\S]*id="search")(?![\s\S]*search\.value)(?![\s\S]*搜索线路，如)(?![\s\S]*输入关键词缩小范围)/],
  ['the results take the place of the tab', /t\.hidden = t\.id !== 'tab-' \+ \(finding \? 'find' : shownTab\)/],
  ['the header steps aside while something is typed', /#panel\.finding :is\(\.title-row, \.facts, #country, #tabs\) \{ display: none; \}/],
  ['showing a tab ends a search', /if \(finding\) endSearch\(\); else paintTabs\(\);/],
  ['what the lists hold is what is found, each line once', /lines: \[\.\.\.\[\.\.\.LISTS\.fast, \.\.\.LISTS\.conv\]\.filter\(l => !FOREIGN\[l\.g\]\), \.\.\.Object\.values\(ABROAD_RAIL\)/],
  ['the selection is cleared before the country changes', /function setCountry\(g, fly\) \{\n(?:\s+\/\/[^\n]*\n)*\s+if \(selMetro\) selectMetro\(null, null\);\s+if \(selected\) select\(null\);\s+country = g;/],
  ['the card searches every country, its own first', /return searchIndex\(searchData, q, \{ country, near: \[c\.lng, c\.lat\], \.\.\.options \}\);/],
  ['the route fields use the same search, China only', /searchAll\(q, \{ country: 'cn', kinds: \['station'\], countries: \['cn'\], routable: true, limit: 40, merge: false \}\)/],
  ['no second station search', /^(?![\s\S]*routable\.filter\(f => label)/],
  ['search and open are reachable without the card', /window\.__rail = \{ search: searchAll, open: openResult \};/],
  ['a result is acted on by its kind', /function openResult\(r\) \{[\s\S]*?select\(e\.name, true\);[\s\S]*?selectMetro\(e\.ref\[0\], e\.ref\[1\], true\);[\s\S]*?setCountry\(e\.country, true\);[\s\S]*?openCity\(e\.ref, true\);[\s\S]*?offerStation\(e\.ref\);/],
  ['a station or a city abroad moves the card there', /if \(e\.country !== country\) setCountry\(e\.country, false\);/],
  ['a metro line abroad opens the list of its own class', /const want = FOREIGN\[country\] \? l\.jk : 'metro';/],
  ['search waits for an input method that is still typing letters', /if \(!\(e\.isComposing && \/\[a-z\]\/i\.test\(e\.data \|\| ''\)\)\) renderFound\(\);[\s\S]{0,120}addEventListener\('compositionend', renderFound\)/],
  // 6f. the field on a phone: the sheet rises, the list ends where the keyboard begins
  ['the sheet rises for the search field', /queryEl\.addEventListener\('focus', \(\) => \{\s+if \(isPhone\(\)\) \{ if \(!typing\) rest = sheet\.detent\(\); sheet\.to\('large'\); \}/],
  ['and goes back when the field is left empty', /if \(isPhone\(\) && !finding && rest && sheet\.detent\(\) === 'large'\) sheet\.to\(rest\);/],
  ['the list ends where the keyboard begins', /\.scroll \{[^}]*- var\(--kb, 0px\)\);/],
  ['the sheet keeps its place if the page is panned', /translateY\(calc\(var\(--sheet-y, 70%\) \+ var\(--vv-top, 0px\)\)\)/],
  ['a focused field does not zoom the page on a phone', /\.searchbar input, \.odf input \{ font-size: 16px; \}/],
  ['a tap on the field does not toggle the sheet', /closest\('button, a, \.searchbar'\)/],
  // 7. the content has one width whether the list scrolls or not, so nothing moves between tabs:
  // the track leaves its right margin to the (thin) scrollbar, and the header reserves nothing
  ['thin scrollbar, no gutter', /scrollbar-width: thin/],
  ['content width does not depend on the scrollbar', /\.tab \{[^}]*width: calc\(var\(--card-w\) - 32px\)/],
  ['track leaves its right margin to the scrollbar', /\.scroll \{[^}]*padding: 4px 0 16px 16px;/],
  ['header has plain margins', /\.head \{ padding: 16px 16px 12px;/],
  ['no measured scrollbar width', /^(?![\s\S]*--sbw)/],
  // 7b. Japan's seven classes are chips that wrap; China's three keep the segmented thumb
  ['class chips for more than three classes', /classList\.toggle\('chips', chips\)/],
  ['chips wrap', /\.segmented\.chips \{ display: flex; flex-wrap: wrap;/],
  // 8. grid children may not stretch the tab beyond the card (overflow clipping the toggles)
  ['tab items can shrink', /\.tab > \* \{ min-width: 0; \}/],
];

let failed = 0;
const report = (name, ok) => { if (!ok) { failed++; console.error('FAIL', name); } else console.log('ok  ', name); };
for (const [name, re] of checks) report(name, typeof re === 'function' ? re(html) : re.test(html));

// ---- the search, run: the block of the page between the two marks holds the two functions ----
const core = html.match(/\/\*SEARCH-CORE\*\/([\s\S]*?)\/\*SEARCH-CORE-END\*\//);
report('the search functions stand apart from the page', !!core && !/(^|[^.\w])(?:document|window|FOREIGN|map\.|col\()/.test(core[1].replace(/\/\/[^\n]*/g, '')));
if (core) {
  const { buildSearchIndex, searchIndex } = new Function(core[1] + '\nreturn { buildSearchIndex, searchIndex };')();
  const point = (n, x, y, more) => ({ type: 'Feature', properties: { n, ...more }, geometry: { type: 'Point', coordinates: [x, y] } });
  const colours = { hsr350: '#c995dd', hsr250: '#2787d5', main: '#d7ecff' };
  const small = buildSearchIndex({
    countries: [{ g: 'cn', name: '中国' },
      { g: 'jp', name: '日本', kindName: { jr: 'JR在来线', shinkansen: '新干线' }, metro: [['subway', '地下铁']] },
      { g: 'uk', name: '英国', kindName: { main: '干线铁路' }, metro: [['subway', '地铁']] }],
    lines: [
      { n: '京沪高速线', g: 'cn', kind: 'fast', c: 'hsr350', design: [350] },
      { n: '京沪线', g: 'cn', kind: 'conv', c: 'main', design: [120, 160] },
      { n: 'JR山手線', g: 'jp', jk: 'jr', c: 'main', lc: '#9acd32' },
      { n: '東海道新幹線', g: 'jp', jk: 'shinkansen', c: 'hsr250', d: 260 },
      { n: 'Central Wales Line', g: 'uk', jk: 'main', c: 'main' }],
    cities: [
      { n: '北京', lines: [{ n: '北京地铁1号线', col: '#a12830' }] },
      { n: '南京', lines: [{ n: '南京地铁2号线', col: '#c7003f' }] },
      { n: '东京', g: 'jp', lines: [{ n: '銀座線', col: '#ff9500', jk: 'subway' }] },
      { n: '伦敦', g: 'uk', lines: [{ n: 'Central line', col: '#dc241f', jk: 'subway' }] }],
    stations: [
      point('奥体中心', 118.72, 32.0, { m: 1, ct: '南京', g: 101 }),
      point('奥体中心', 116.39, 39.98, { m: 1, ct: '北京', g: 102 }),
      point('北京南', 116.38, 39.86, { h: 1, g: 5 }),
      point('北京东', 116.48, 39.9, {}),                    // not on the route network
      point('東京', 139.767, 35.681, { g: 'jp' }),
      point('新宿', 139.7, 35.69, { g: 'jp', m: 1, ct: '东京' }),
      point('新宿', 139.702, 35.691, { g: 'jp', m: 1, ct: '东京' })],
    colours,
  });
  const names = group => (group ? group.results.map(r => r.name) : []);
  const find = (q, options) => searchIndex(small, q, options);
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

  report('search: nothing typed, nothing found', same(find(''), []) && same(find('   '), []));
  const jing = find('京', { country: 'cn' });
  report('search: every country at once, grouped by country', same(jing.map(g => g.country), ['cn', 'jp']) && same(jing.map(g => g.name), ['中国', '日本']));
  report('search: the country of the card comes first', same(find('京', { country: 'jp' }).map(g => g.country), ['jp', 'cn']));
  report('search: railway lines, metro lines, cities and stations all answer',
    ['line', 'metro', 'city', 'station'].every(kind => jing[0].results.some(r => r.kind === kind)));
  report('search: a result is a plain object with six fields',
    jing.every(g => g.results.every(r => same(Object.keys(r), ['kind', 'country', 'name', 'sub', 'colour', 'id']) && typeof r.id === 'string')));
  const line = find('京沪高速', { country: 'cn' })[0].results[0];
  report('search: a line says what it is and has its colour', line.kind === 'line' && line.sub === '高铁 · 350 km/h' && line.colour === '#c995dd');
  report('search: a conventional line has no speed', find('京沪线')[0].results[0].sub === '普速铁路');
  const yamanote = find('山手', { country: 'cn' })[0].results[0];
  report('search: a line abroad carries its class and its own colour', yamanote.country === 'jp' && yamanote.sub === 'JR在来线' && yamanote.colour === '#9acd32');
  report('search: a high-speed line abroad carries its band colour and speed', (r => r.sub === '新干线 · 260 km/h' && r.colour === '#2787d5')(find('新幹線')[0].results[0]));
  const ginza = find('銀座')[0].results[0];
  report('search: a metro line names its city and has its colour', ginza.kind === 'metro' && ginza.sub === '地下铁 · 东京' && ginza.colour === '#ff9500');
  report('search: a country is found by its name', (r => r.kind === 'country' && r.id === 'country:jp')(find('日本')[0].results[0]));
  report('search: exact names first, then cities before lines before stations',
    same(names(find('北京', { country: 'cn' })[0]), ['北京', '北京地铁1号线', '北京南', '北京东']));
  report('search: Latin names whatever the case', same(names(find('central', { country: 'uk' })[0]), ['Central line', 'Central Wales Line']) && names(find('CENTRAL LINE')[0])[0] === 'Central line');
  report('search: names are matched as written, 东京 the city and 東京 the station',
    same(find('东京').flatMap(g => g.results.map(r => r.kind)), ['city']) && same(find('東京').flatMap(g => g.results.map(r => r.kind)), ['station']));
  report('search: city and station name together, with or without a space',
    same(find('南京 奥体中心')[0].results.map(r => r.sub), ['地铁站 · 南京']) && same(find('南京奥体中心')[0].results.map(r => r.sub), ['地铁站 · 南京']));
  report('search: a city alone does not list its stations', !names(find('南京')[0]).includes('奥体中心'));
  report('search: stations of one name, the nearest to the view first',
    same(find('奥体中心', { near: [116.4, 39.9] })[0].results.map(r => r.sub), ['地铁站 · 北京', '地铁站 · 南京'])
    && same(find('奥体中心', { near: [118.8, 32.05] })[0].results.map(r => r.sub), ['地铁站 · 南京', '地铁站 · 北京']));
  const routeFields = { country: 'cn', kinds: ['station'], countries: ['cn'], routable: true, limit: 40, merge: false };
  report('search: the route fields get stations in China on the route network only',
    same(names(find('京', routeFields)[0]), ['北京南']) && find('東京', routeFields).length === 0);
  report('search: one station mapped as two points is listed once', find('新宿')[0].total === 1 && find('新宿', { merge: false })[0].total === 2);
  report('search: the first country gets more rows than the others',
    (found => found[0].results.length === 2 && found[0].total === 8 && found[1].results.length === 1 && found[1].total === 2)(find('京', { country: 'cn', limit: 2, rest: 1 })));
  // twenty metro lines of one city must not push its stations off the list, and "广州南" is a station
  const crowd = buildSearchIndex({ countries: [{ g: 'cn', name: '中国' }], colours, lines: [],
    cities: [{ n: '上海', lines: Array.from({ length: 20 }, (_, i) => ({ n: `上海地铁${i + 1}号线`, col: '#e4002b' })) },
      { n: '广州', lines: [] }],
    stations: [point('上海', 121.45, 31.25, { g: 1 }), point('上海南', 121.43, 31.15, { g: 2 }), point('上海虹桥', 121.32, 31.19, { g: 3 }),
      point('上海火车站', 121.455, 31.25, { g: 4, m: 1, ct: '上海' }), point('人民广场', 121.47, 31.23, { g: 5, m: 1, ct: '上海' }),
      point('广州南', 113.27, 22.99, { g: 6 }), point('南海神庙', 113.5, 23.08, { g: 7, m: 1, ct: '广州' }), point('广州南站', 113.27, 22.99, { g: 8, m: 1, ct: '广州' })] });
  report('search: exact names, then three of each kind in turn',
    same(names(searchIndex(crowd, '上海', { limit: 9 })[0]), ['上海', '上海', '上海地铁1号线', '上海地铁2号线', '上海地铁3号线', '上海南', '上海虹桥', '上海火车站', '上海地铁4号线'])
    && searchIndex(crowd, '上海')[0].total === 25);
  report('search: 广州南 is the station, not the stations of 广州 that begin with 南',
    same(names(searchIndex(crowd, '广州南')[0]), ['广州南', '广州南站']) && same(names(searchIndex(crowd, '广州 南海')[0]), ['南海神庙']) && same(names(searchIndex(crowd, '广州南海')[0]), ['南海神庙']));
  const twice = buildSearchIndex({ countries: [{ g: 'cn', name: '中国' }], colours, cities: [],
    lines: [{ n: '京沪线', g: 'cn', kind: 'conv', c: 'main' }, { n: '京沪线', g: 'cn', kind: 'conv', c: 'main' }],
    stations: [point('汉阳', 114.2, 30.55, { g: 1 }), point('汉阳', 114.2, 30.55, { g: 2 })] });
  report('search: a line given twice is one line, two stations on one spot stay two',
    searchIndex(twice, '京沪')[0].total === 1 && searchIndex(twice, '汉阳', { merge: false })[0].total === 2 && new Set(searchIndex(twice, '汉阳', { merge: false })[0].results.map(r => r.id)).size === 2);
  report('search: an id leads back to the thing',
    small.byId.get(line.id).ref.n === '京沪高速线' && small.byId.get(ginza.id).ref[0].n === '东京' && small.byId.get(find('東京')[0].results[0].id).ref.geometry.coordinates[0] === 139.767);

  // The same on the data the page loads, put together as the page does.
  const data = f => JSON.parse(readFileSync(join(root, 'data', f), 'utf8'));
  const abroad = ['jp', 'kr', 'uk'].filter(g => new RegExp(`\\n    ${g}: \\{ name: `).test(html) && existsSync(join(root, 'data', `${g}_lines.json`)));
  if (existsSync(join(root, 'data', 'lines.json'))) {
    const lines = data('lines.json'), cities = data('metro_cities.json');
    const stations = [...data('stations.geojson').features, ...data('metro_stations.geojson').features.map(f => ((f.properties.m = 1), f))];
    for (const g of abroad) {
      lines.push(...data(`${g}_lines.json`));
      cities.push(...data(`${g}_metro_cities.json`).map(c => ({ ...c, g })));
      stations.push(...data(`${g}_stations.geojson`).features);
    }
    const names_ = { jp: '日本', kr: '韩国', uk: '英国' };
    const real = buildSearchIndex({ countries: [{ g: 'cn', name: '中国' }, ...abroad.map(g => ({ g, name: names_[g], kindName: {}, metro: [] }))], lines, cities, stations, colours });
    const t0 = performance.now();
    const tokyo = searchIndex(real, '東京', { country: 'cn' });
    const took = performance.now() - t0;
    report(`search on the data: ${real.entries.length} things, one query in ${took.toFixed(1)} ms`, real.entries.length > 20000 && took < 200);
    if (abroad.includes('jp')) report('search on the data: 東京 finds the station in Japan from the card of China',
      tokyo.some(g => g.country === 'jp' && g.results.some(r => r.kind === 'station' && r.name === '東京')));
    report('search on the data: 上海虹桥 is a station, 上海 a city first', searchIndex(real, '上海虹桥')[0].results[0].kind === 'station' && searchIndex(real, '上海', { country: 'cn' })[0].results[0].kind === 'city');
    // what the field suggests typing must be findable in that country
    const hints = { cn: (html.match(/const HINT_CN = '([^']+)'/) || [])[1], ...Object.fromEntries(abroad.map(g => [g, (html.match(new RegExp(`\\n    ${g}: \\{[\\s\\S]*?hint: '([^']+)'`)) || [])[1]])) };
    for (const [g, hint] of Object.entries(hints)) {
      report(`search on the data: the examples for ${g} (${hint}) are found there`,
        !!hint && hint.split('、').every(word => searchIndex(real, word, { country: g, countries: [g] }).length === 1));
    }
  }
}
process.exit(failed ? 1 : 0);
