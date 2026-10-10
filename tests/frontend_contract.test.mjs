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
  // 1. the route tab is there only in the country the route network covers (2026-10-09; before, an empty state abroad)
  ['no route page where there is no routing', page => !/routeJp|routeGoLines|暂不支持线路网寻路；/.test(page)],
  ['the route tab is in the bar only where routing applies', /if \(FOREIGN\[country\]\) tab\.remove\(\); else if \(!tab\.isConnected\) bar\.insertBefore\(tab, bar\.querySelector\('button'\)\);/],
  // 2. setCountry clears route state and re-syncs the route empty state
  ['setCountry cleans route', /if \(routeCleanup\) routeCleanup\(\)/],
  ['setCountry syncs route tab', /syncRouteTab\(\);/],
  // 3. a page that was on the route tab opens on the lines in a country abroad
  ['auto-switch route->lines abroad', /FOREIGN\[g\] && onRoute\) showTab\('lines'\)/],
  // 4. the Chinese rows give way to the rows of the country abroad
  ['Chinese-only rows hidden abroad', /for \(const id of \[\.\.\.HOME\.metro\.map\(\(\[kind\]\) => metroId\('cn', kind\)\), 'border'\]\) rowEls\[id\]\.hidden = !cn;/],
  ['Chinese band rows hidden abroad', /for \(const id of \[\.\.\.FAST, 'unknown'\]\) if \(rowEls\[id\]\) rowEls\[id\]\.hidden = !cn;/],
  // 5. a station abroad does not offer 设为出发/到达
  ['station abroad blocked', /f\.properties\.g == null \|\| FOREIGN\[f\.properties\.g\]/],
  // 6. countries abroad are entries of one configuration: classes, layers, rows and buttons come from it
  ['countries abroad are configured, not branched on', /const FOREIGN = \{/],
  ['no branch on one country', /^(?![\s\S]*country === 'jp')(?![\s\S]*country === 'uk')/],
  ['Japan: its classes', /rail: \[\['shinkansen', 'jp\.shinkansen'\], \['jr', 'jp\.jr'\], \['private_big', 'jp\.private_big'\],\s+\['private_local', 'jp\.private_local', \['third_sector', 'private_local'\]\], \['unknown', 'jp\.unknown'\]\]/],
  ['Japan: its metro classes', /metro: \[\['subway', 'jp\.subway'\], \['urban', 'jp\.urban'\]\]/],
  ['UK: its classes', /rail: \[\['hs', 'rail\.hs'\], \['main', 'rail\.main'\], \['branch', 'rail\.branch'\], \['heritage', 'rail\.heritage'\]\]/],
  ['UK: its metro classes', /metro: \[\['subway', 'uk\.subway'\], \['urban', 'uk\.urban'\]\]/],
  ['the list of countries is made from the countries the page has', /document\.getElementById\('countryList'\)\.replaceChildren\(\.\.\.everyCountry\.map\(g => \{/],
  ['no country is written into the card, and no segmented switch', page => !/data-g="/.test(page) && !/id="country"/.test(page) && !/segmented\.mini/.test(page)],
  ['Korea: its classes, two of them fast', /fast: \['hs', 'semi'\][\s\S]{0,200}rail: \[\['hs', 'rail\.hs'\], \['semi', 'rail\.semi'\], \['main', 'rail\.main'\], \['branch', 'rail\.branch'\]\]/],
  ['the card starts at the list of countries', /<aside id="panel" class="world"[\s\S]*<div class="tab" id="tab-world" role="region" aria-label="国家" data-ta="aria-label:world\.label">\s+<ul class="group linelist countries" id="countryList"><\/ul>/],
  ['a link that opens inside a country starts on its page', /const startIn = startView && countryAt\(map\.getCenter\(\)\.lng, map\.getCenter\(\)\.lat\);\s+setCountry\(startIn \|\| 'cn', false\);\s+if \(!startIn\) setWorld\(\);/],
  ['a country\'s page has a way back to the list', /<button type="button" class="back" id="toWorld" aria-label="返回国家列表" data-ta="aria-label:back\.label">[\s\S]*toWorld\.addEventListener\('click', \(\) => \{\s+setWorld\(\);/],
  ['going back does not move the map', page => { const m = page.match(/function setWorld\(\) \{[\s\S]*?\n    \}/); return !!m && !/fitBounds|jumpTo|flyTo/.test(m[0]) && /world = true;/.test(m[0]); }],
  ['at the list the header has no figures, tabs or way back', /#panel\.world :is\(\.back, \.facts, #tabs\) \{ display: none; \}/],
  ['a line, a station or a city is shown on its country\'s page', /const enter = g => \{ if \(world \|\| g !== country\) setCountry\(g, false\); \};/],
  ['a stop of a route opens China\'s page', /if \(f\) enter\('cn'\);/],
  ['at the list the quick jumps are the countries', /if \(world\) \{ for \(const g of everyCountry\) addJump\(nameOf\(g\), null, \(\) => setCountry\(g, 'auto'\)\); return; \}/],
  ['the phone sheet at rest shows the header clear of the home indicator, and at the list its start', /peek: Math\.max\(0, H - head\.offsetHeight - safe\('Bottom'\) - \(world && !finding \? 108 : 0\)\)/],
  ['the level is plain state the app can ask for', /level: \(\) => \(world \? null : country\), openCountry: \(g, fly\) => setCountry\(g, fly === undefined \? 'auto' : !!fly\), openWorld: setWorld,\s+language: \(\) => lang, setLanguage: to => setLanguage\(to, false\),\s+countries: \(\) => everyCountry\.map/],
  // the language, for the app: one call to ask, one to set (not remembered as the visitor's own choice), one event when it changes
  ['the app asks for the language, sets it, and hears when it changes', page => /relabel\(\);\s+sendCopy\(\);\s+dispatchEvent\(new CustomEvent\('rail:language', \{ detail: lang \}\)\);\s+if \(window\.__app\) window\.__app\.post\('language', lang\);/.test(page)
    && /if \(byHand\) \{\s+try \{ localStorage\.setItem\('lang', lang\);/.test(page)],
  ['the thumb reaches a fourth and fifth choice', /nth-of-type\(5\)[^{]*\{ --i: 4; \}/],
  // 6b. one colour rule: the band of the design speed, else the line's own colour, else neutral; never the company's
  ['a row per speed band the country has', /bands\[kind\]\.map\(band => \(\{ id: `\$\{g\}-\$\{kind\}-\$\{band\}`, g, rail: kind, band \}\)\)/],
  ['the bands come from the data', /FAST\.filter\(band => rail\.features\.some\(f => f\.properties\.c === band && jkOf\(g, kind\)\.includes\(f\.properties\.jk\)\)\)/],
  ['a layer per band, in the band colour', /abroadLayers\.push\(\[`\$\{g\}-\$\{kind\}-\$\{band\}`, g, \[[^\n]*\], col\(band\), fastOf\]\);/],
  ['other lines: own colour, else neutral', /\['coalesce', \['get', 'lc'\], col\('main'\)\], plainOf\]\);/],
  ['colour note says no company colours', /不按公司上色/],
  ['no company list, no operator colours', /^(?![\s\S]*opList)(?![\s\S]*OP_COLOR)(?![\s\S]*_operators)/],
  // 6c. every country is on the map all the time; the country of the card only decides whose
  // switches the card shows (2026-10-09, replacing "the other countries are hidden")
  ['layers abroad answer to their own switch only', /for \(const id of Object\.keys\(abroadVisible\)\) \{\s+set\(id, abroadVisible\[id\]\);/],
  ['China layers answer to China switches only', /for \(const id of \[\.\.\.FAST, 'main', 'branch'\]\) set\(id, visible\[id\]\);/],
  ['no layer is hidden for being in another country', /^(?![\s\S]*cn && visible)(?![\s\S]*startsWith\(country \+ '-'\) && abroadVisible)(?![\s\S]*countryFilter)/],
  ['shared layers show the countries whose switch is on', /const where = \['any', \.\.\.here\.map\(g => \(g === 'cn' \? NOT_ABROAD : \['==', \['get', 'g'\], g\]\)\)\];/],
  ['stations: one switch per country', /among\('stations', withStations, /],
  ['lines being built: one switch per country', /among\('build', everyCountry\.filter\(g => rowOn\('build', g\)/],
  ['a shared row changes the switch of the country of the card', /if \(SHARED_ROWS\.includes\(c\.id\) && country !== 'cn'\) sharedOff\[country \+ '-' \+ c\.id\] = !e\.target\.checked;/],
  ['a shared row shows the switch of the country of the card', /box\.checked = rowOn\(id, country\);/],
  // the names of the cities are such a row too (2026-10-09, "城市也加个图层，可以取消显示"): one row, on at
  // the start, shown for every country, each country with its own switch behind it
  ['city names: a row of the layers tab, shared by the countries', page => /\{ id: 'cities', label: 'row\.cities', sub: '', spd: '', src: 'cities' \},/.test(page) && /const SHARED_ROWS = \['build', 'stations', 'cities'\];/.test(page)
    && !/hideAbroad = \{[^}]*cities/.test(page) && !/for \(const id of \[[^\]]*'cities'[^\]]*\]\) if \(rowEls\[id\]\) rowEls\[id\]\.hidden/.test(page)],
  ['city names: one switch per country, over the dots and the names of every rank', page =>
    /const withCities = everyCountry\.filter\(g => rowOn\('cities', g\)\);\s+for \(const id of \['city-dots', 'city-labels'\]\) set\(id, withCities\.includes\('cn'\)\);\s+set\('place-labels', withCities\.length > 0\);\s+if \(withCities\.length\) map\.setFilter\('place-labels', \['all', \['in', \['get', 'g'\], \['literal', withCities\]\], PLACE_RANKS\]\);/.test(page)
    && /\(c, i\) => \(\{ k: c\.r \* 1000 \+ i, g: c\.g \|\| 'cn', \.\.\.\(c\.side \? \{ side: c\.side \} : \{\}\) \}\)/.test(page)],
  // the names on the map come from the same rule as the card's, and are set again in another language
  ['the map\'s labels are named by the rule of the card', page => /const NAMED_LAYERS = \[\['station-labels', 'other', true\], \['metro-station-labels', 'other', true\], \['depot-labels', 'other', true\], \['place-labels', 'city', false\], \['city-labels', 'city', false\]\];/.test(page)
    && /map\.setLayoutProperty\(id, 'text-field', namedField\(kind, under, g\)\)/.test(page) && /listStations\(\);\s+nameTheMap\(\);/.test(page)
    && /if \(g\) return as\(howNamed\(g, kind, NAMES\.map\)\);/.test(page)],
  ['the card names lines, cities and stations by the same rule', page => /const cityName = c => named\(c, abroad\(c\.g\), 'city'\);/.test(page)
    && /addJump\(cityName\(c\), /.test(page) && /, cityName\(c\), \(\) => openCity\(c, true\), false, 'city:' \+ c\.n\);/.test(page) && /named\(l, abroad\(c\.g\)\), \(\) => selectMetro\(c, l, true\)/.test(page)
    && /named\(l, abroad\(l\.g\)\), \(\) => select\(l\.n, true\), selected === l\.n, 'line:' \+ l\.n\)/.test(page) && /hubName = new Map\(routable\.map\(f => \[f\.properties\.g, named\(f\.properties\)\]\)\);/.test(page)
    && /say: t, name: named,/.test(page) && /nameMetroCities\(metroCities, cities, abroad\);/.test(page)],
  // 6n. the mini-shinkansen (2026-10-10): lines of the fast class in no speed band are listed with it after the others,
  // with their top speed, drawn in their own colours by a layer and switch of their own, said for what they are
  ['a fast class\'s lines in no band: their own layer, in their own colours, with a row and a switch of their own (2026-10-10, "新加个130km新干线图层吧")', page =>
    /abroadLayers\.push\(\[`\$\{g\}-\$\{kind\}-mini`, g, \['all', \.\.\.of\(kind\), \['!', \['in', \['get', 'c'\], \['literal', FAST\]\]\]\], \['coalesce', \['get', 'lc'\], col\('main'\)\], plainOf\]\);/.test(page)
    && /\.\.\.\(\(minis\[kind\] \|\| \[\]\)\.length \? \[\{ id: `\$\{g\}-\$\{kind\}-mini`, g, rail: kind, mini: minis\[kind\] \}\] : \[\]\)/.test(page)
    && /itsLines\.filter\(l => l\.mini && jkOf\(g, kind\)\.includes\(l\.jk\)\)/.test(page) && !/for \(const \[id, g, kind\] of abroadMini\)/.test(page)
    && /'main', 'branch', \.\.\.abroadMini\.map\(m => m\[0\]\),/.test(page) && /abroadPlain\.push\(`\$\{g\}-\$\{kind\}-mini`\);/.test(page)],
  ['...listed after the lines built for the speed, their top speed shown, said as mini-shinkansen; the class\'s whole length in the figures', page =>
    /\.sort\(\(a, b\) => !!a\.mini - !!b\.mini\)\]\)\)\]\)\);/.test(page) && /\(l\.d \? l\.d \+ '\\u00a0km\/h' : l\.mini \? '—' :/.test(page) && /\(\(l\.mini && FOREIGN\[l\.g\]\.miniName\) \|\|/.test(page)
    && /\(lineOf\(p\)\.mini && there\.miniName\)/.test(page) && /miniName: 'jp\.mini',/.test(page) && /of\[FOREIGN\[g\]\.fast\[0\] \+ '_km'\]\) \|\| of\.fast_km/.test(page)],
  ['the rows are still those of the country of the card', /rowEls\[id\]\.hidden = !id\.startsWith\(country \+ '-'\);/],
  ['a selection dims the lines abroad too', /for \(const id of abroadBand\) map\.setPaintProperty\(id, 'line-opacity', sel \? 0\.4 : 1\);/],
  ['a tap on a line moves the card to its country\'s page', /enter\(abroad\(f\.properties\.g\)\);\s+select\(f\.properties\.n, false, f\.properties\.c\);/],
  ['dragging the map does not change the country', /^(?![\s\S]*map\.on\('(?:move|moveend|drag|dragend|zoomend)'[^\n]*setCountry)/],
  // 6d. yards and depots: one switch for every country, each country fetched when first seen
  ['yards and depots: one switch, no country filter', /for \(const id of \['yards', 'depots', 'depot-labels'\]\) for \(const \[layer\] of each\(id\)\) set\(layer, visible\.yards\);\s+loadYards\(\);/],
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
  ['the results take the place of the tab, or of the list of countries', /t\.hidden = t\.id !== 'tab-' \+ \(finding \? 'find' : world \? 'world' : shownTab\)/],
  ['the header steps aside while something is typed', /#panel\.finding :is\(\.title-row, \.facts, #tabs\) \{ display: none; \}/],
  ['showing a tab ends a search', /if \(finding\) endSearch\(\); else paintTabs\(\);/],
  ['what the lists hold is what is found, each line once', /lines: \[\.\.\.\[\.\.\.LISTS\.fast, \.\.\.LISTS\.conv\]\.filter\(l => !FOREIGN\[l\.g\]\), \.\.\.Object\.values\(ABROAD_RAIL\)/],
  // 6m. a country picked keeps the reader's view (2026-10-10, "人们刚开始去看某个地方的铁路，会放大到那个地方，但是如果切换国家之后，视角就变了"):
  // the map stays where it shows that country, goes back to where the reader left it, or to its overview; picked again, its overview
  ['what the map shows is the country under the middle of the free part of the map', /const lookingAt = \(\) => \{ const pad = padding\(\), room = roomNow\(\), p = map\.unproject\(\[pad\.left \+ room\[0\] \/ 2, pad\.top \+ room\[1\] \/ 2\]\); return countryAt\(p\.lng, p\.lat\); \};/],
  ['a country picked: its page picked again is its overview; shown already, the map stays; left before, back there; else its overview',
    /const go = fly === 'auto' \? \(!world && g === country \? 'overview' : lookingAt\(\) === g \? null : leftAt\[g\] \? 'back' : 'overview'\) : fly \? 'overview' : null;/],
  ['the view is kept when a country is left while the map shows it, and not at its overview', page =>
    /const keepView = \(\) => \{\s+if \(!country \|\| lookingAt\(\) !== country\) return;[^\n]*\s+if \(framed && framed\.country === country\) \{ delete leftAt\[country\]; return; \}\s+const c = map\.getCenter\(\);\s+leftAt\[country\] = \{ center: \[c\.lng, c\.lat\], zoom: map\.getZoom\(\), bearing: map\.getBearing\(\), pitch: map\.getPitch\(\) \};/.test(page)
    && /function setWorld\(\) \{\s+keepView\(\);/.test(page) && /\} else if \(go === 'back'\) frame\(\{ camera: leftAt\[g\] \}, 1800\);/.test(page) && /if \(what\.camera\) \{ map\.flyTo\(\{ \.\.\.what\.camera, duration \}\); return; \}/.test(page)],
  ['the reader\'s picks of a country go by the rule; a search result and a page that follows the map do not', page =>
    /nameOf\(g\), \(\) => \{ setCountry\(g, 'auto'\);/.test(page) && /function openResult\(r, fly = true\)/.test(page) && /setCountry\(e\.country, fly\);/.test(page) && /const enter = g => \{ if \(world \|\| g !== country\) setCountry\(g, false\); \};/.test(page)
    && !/setCountry\([^)]*\)[^\n]*frame\(\{ country/.test(page)],
  ['the back button does not move the map', page => !/function setWorld\(\) \{[^}]*(?:frame|flyTo|jumpTo|fitBounds)/.test(page)],
  ['the selection is cleared before the country changes', /function setCountry\(g, fly\) \{\n\s+const go = [^\n]*\n\s+if \(g !== country \|\| world\) keepView\(\);\n(?:\s+\/\/[^\n]*\n)*\s+if \(selMetro\) selectMetro\(null, null\);\s+if \(selected\) select\(null\);\s+const changed = g !== country \|\| !kindButtons\.length;\s+country = g;/],
  ['the card searches every country, the open one first', /const found = searchIndex\(searchData, q, \{ \.\.\.\(world \? \{ limit: 6 \} : \{ country \}\), near: \[c\.lng, c\.lat\], \.\.\.options \}\);/],
  ['the route fields use the same search, China only', /searchAll\(q, \{ country: 'cn', kinds: \['station'\], countries: \['cn'\], routable: true, limit: 40, merge: false \}\)/],
  ['no second station search', /^(?![\s\S]*routable\.filter\(f => label)/],
  ['search and open are reachable without the card', /window\.__rail = \{ search: searchAll, open: openResult, /],
  ['a result is acted on by its kind', /function openResult\(r, fly = true\) \{[\s\S]*?select\(e\.ref\.n, fly\);[\s\S]*?selectMetro\(e\.ref\[0\], e\.ref\[1\], fly\);[\s\S]*?setCountry\(e\.country, fly\);[\s\S]*?openCity\(e\.ref, fly\);[\s\S]*?offerStation\(e\.ref\);/],
  ['a station or a city opens its country\'s page', /enter\(e\.country\);[\s\S]*enter\(e\.country\);/],
  ['a metro line opens the list of its own class, in every country', /const its = \(\) => \(classes => classes\.find\(\(\[k\]\) => k === l\.jk\) \|\| classes\[0\]\)\(land\(country\)\.metro\);[^\n]*\n\s+if \(kind !== its\(\)\[0\]\) setKind\(its\(\)\[0\]\);/],
  ['search waits for an input method that is still typing letters', /if \(!\(e\.isComposing && \/\[a-z\]\/i\.test\(e\.data \|\| ''\)\)\) renderFound\(\);[\s\S]{0,120}addEventListener\('compositionend', renderFound\)/],
  // 6f. the field on a phone: the sheet rises, the list ends where the keyboard begins
  ['the sheet rises for the search field', /queryEl\.addEventListener\('focus', \(\) => \{\s+if \(isPhone\(\)\) \{ if \(!typing\) rest = sheet\.detent\(\); sheet\.to\('large'\); \}/],
  ['and goes back when the field is left empty', /if \(isPhone\(\) && !finding && rest && sheet\.detent\(\) === 'large'\) sheet\.to\(rest\);/],
  ['the list ends where the keyboard begins', /\.scroll \{[^}]*- var\(--kb, 0px\)\);/],
  ['the sheet keeps its place if the page is panned', /translateY\(calc\(var\(--sheet-y, 70%\) \+ var\(--vv-top, 0px\)\)\)/],
  ['a focused field does not zoom the page on a phone', /\.searchbar input, \.odf input \{ font-size: 16px; \}/],
  ['a tap on the field does not toggle the sheet', /closest\('button, a, \.searchbar'\)/],
  // 6g. tile mode (2026-10-09): behind a switch, one PMTiles archive and one vector source per
  // country; with the switch off every source is the GeoJSON one it was
  ['the tile switch is set by the build', /const WITH_TILES = (?:true|false);/],
  ['the address chooses the mode for one visit', /const TILES = \(\{ 1: true, 0: false \}\)\[new URLSearchParams\(location\.search\)\.get\('tiles'\)\] \?\? WITH_TILES;/],
  ['tiles off: nothing of tile mode is asked for', /const tilesReady = !TILES \? Promise\.resolve\(null\)/],
  ['tiles on: the reader comes from the site itself, when needed', page => /Promise\.all\(\[script\('vendor\/pmtiles\.js'\), \.\.\.everyCountry\.map\(g => getJSON\(`data\/tiles\/\$\{g\}\.json`, 1\)\)\]\)/.test(page) && !/<script[^>]*pmtiles/.test(page) && !/unpkg|jsdelivr/.test(page)],
  ['tiles on: every archive is read once before the map is built on it', /const archive = new window\.pmtiles\.PMTiles\(archiveOf\(g\)\);\s+protocol\.add\(archive\);[^\n]*\n\s+return archive\.getHeader\(\);/],
  ['tiles that cannot be read: the whole files, and a word in the console', /\}\)\.catch\(err => \{\s+console\.warn\('The tiles cannot be read; the page uses the whole files instead\.', err\);\s+return null;\s+\}\);/],
  ['tiles on: no line or station file comes whole', /const whole = file => \(tiles \? Promise\.resolve\(\{ type: 'FeatureCollection', features: \[\] \}\) : getJSON\(file\)\);/],
  ['tiles on: a vector source per country, read from its archive', /if \(tiles\) for \(const g of everyCountry\) map\.addSource\('tiles-' \+ g, \{ type: 'vector', url: 'pmtiles:\/\/' \+ archiveOf\(g\) \}\);/],
  ['tiles off: the GeoJSON sources as they were', /const whole = \(name, options\) => \{ if \(!tiles\) map\.addSource\(name, \{ type: 'geojson', \.\.\.options \}\); \};/],
  ['tiles off: every source keeps its own data and tolerance', page => ["whole('conv', { data: conv, tolerance: 0.45 })", "whole('build', { data: build, tolerance: 0.45 })", "whole('hsr', { data: hsr, tolerance: 0.35 })",
    "whole('shared', { data: shared, tolerance: 0.35 })", "whole('stations', { data: stations })", "whole('metro', { data: metro, tolerance: 0.3 })", "whole('metro-stations', { data: metroStations })",
    "map.addSource('border', { type: 'geojson', data: border, tolerance: 0.3 })", "whole('yards', { data: EMPTY, tolerance: 0.2 })", "whole('depots', { data: EMPTY })"].every(line => page.includes(line))],
  ['a layer names its source for either mode', /const from = \(name, g = 'cn'\) => \(tiles \? \{ source: 'tiles-' \+ g, 'source-layer': name \} : \{ source: name \}\);/],
  ['no layer names a line source outright', /^(?![\s\S]*source: '(?:conv|hsr|shared|build|metro|metro-stations|stations|yards|depots)')/],
  ['the border is one whole file in both modes', /getJSON\('data\/border\.geojson'\), whole\('data\/metro\.geojson'\)/],
  ['a layer of a country abroad reads that country', /\.\.\.from\('conv', g\),[\s\S]*\.\.\.from\('metro', g\),/],
  ['a layer that mixed countries is one per country in tile mode', /copies\[spec\.id\] = tiles \? everyCountry\.filter\(g => has\(name, g\)\)\.map\(g => \[g === 'cn' \? spec\.id : spec\.id \+ '@' \+ g, g\]\) : \[\[spec\.id, null\]\];/],
  ['the mixed layers', page => ['yards', 'build', 'hl-conv', 'hl-conv-core', 'stations', 'station-labels', 'depots', 'depot-labels', 'metro-stations', 'metro-station-labels'].every(id => new RegExp(`addMixed\\('[a-z-]+', \\{ id: '${id}',`).test(page))],
  ['each country\'s layer answers to its own switch', /const here = own \? countries\.filter\(g => g === own\) : countries;/],
  ['tiles on: speed bands and lines being built from the note beside the tiles', /FAST\.filter\(band => tiles\[g\]\.bands\.some\(\(\[jk, c\]\) => c === band && jkOf\(g, kind\)\.includes\(jk\)\)\)[\s\S]{0,400}/],
  ['tiles on: the station lists come as columns, once the map is up or a field needs them', /Promise\.all\(everyCountry\.map\(g => getJSON\(`data\/tiles\/\$\{g\}\.stations\.json`\)\)\)[\s\S]{0,900}map\.once\('idle', stationLists\);\s+for \(const field of \[queryEl, odInput\.from, odInput\.to\]\) field\.addEventListener\('focus', stationLists\);/],
  ['what is made from the stations is made again when they arrive', /stationsIn = true;\s+listStations\(\);\s+if \(finding\) renderFound\(\);/],
  ['a search asks for the station lists and says while they are on their way', /stationLists\(\);\s+const found = searchIndex\([\s\S]{0,200}found\.pending = !stationsIn;/],
  ['the results say the stations are loading rather than that nothing was found', /note\.textContent = t\(found\.pending \? 'found\.loading' : 'found\.none'\);/],
  ['tiles off: the station lists are there from the start', /let stationsAsked = !tiles, stationsIn = !tiles, stationPromise;/],
  ['a tapped station is found in the list by name and nearness', /offerStation\(stationOf\(stations\.features, st\)\);[\s\S]*offerStation\(stationOf\(metroStations\.features, ms\)\);/],
  ['a tapped feature is told by its tile layer or its source', /const of = f && \(f\.sourceLayer \|\| f\.layer\.source\);/],
  // 6h. the route network is fetched when a route is first asked for, in both modes
  ['the route network is not fetched at start', page => (page.match(/graph\.json/g) || []).length === 2 && /const loadNetwork = \(\) => network \|\| \(network = getJSON\('data\/graph\.json'\)/.test(page)
    && /if \(f\) \{[\s\S]{0,400}loadNetwork\(\)\.catch/.test(page)],
  // 6i. on a phone (2026-10-09, "手机端页面优化一下")
  // the credits are in sight at every height of the sheet: they ride on its upper edge
  ['the credits and the scale ride on the sheet', /riders = riders && riders\.isConnected \? riders : document\.querySelector\('\.maplibregl-ctrl-bottom-right'\);\s+if \(riders\) riders\.style\.transform = `translateY\(\$\{Math\.round\(y - H\)\}px\)`;/],
  ['at the sheet\'s highest the credits fold to their button, the scale goes', page => /const credits = at === 'large' && document\.querySelector\('\.maplibregl-ctrl-bottom-right \.maplibregl-ctrl-attrib\.maplibregl-compact-show'\);/.test(page) && /body\[data-sheet="large"\] \.maplibregl-ctrl-scale \{ display: none; \}/.test(page)],
  // The credits are the map's own control at every width: on a phone the one that rides on the
  // sheet, beside the desktop card one in the map's lower left corner. Each is off only where
  // the other is on.
  ['the credits are on at every width: each control is off only where the other is on', page => {
    const styles = page.slice(page.indexOf('/* Layout: a satellite globe'), page.indexOf('<div id="map"'));
    const off = [...styles.matchAll(/([^{}\n]*maplibregl-ctrl-(?:attrib|bottom-left)[^{}]*)\{[^}]*(?:display: none|visibility: hidden|opacity: 0;)[^}]*\}/g)].map(m => m[1].trim());
    return JSON.stringify(off) === JSON.stringify(['.maplibregl-ctrl-bottom-right .maplibregl-ctrl-attrib', '.maplibregl-ctrl-bottom-left'])
      && /@media not all and \(max-width: 720px\) \{[^@]*?\.maplibregl-ctrl-bottom-left \{[^}]*\}[^@]*?\.maplibregl-ctrl-bottom-right \.maplibregl-ctrl-attrib \{ display: none; \}\s+\}/.test(styles)
      && /@media \(max-width: 720px\) \{[\s\S]*\n  \.maplibregl-ctrl-bottom-left \{ display: none; \}/.test(styles);
  }],
  ['the words of the credits, with the link to the licence, in both controls', page =>
    page.includes(`const IMAGERY = 'Imagery © Esri, Maxar, Earthstar Geographics';`)
    && page.includes("const creditLine = () => `© <a href=\"https://www.openstreetmap.org/copyright\" target=\"_blank\" rel=\"noopener\">OpenStreetMap</a> ${t('credits.osm')} | ` + IMAGERY;")
    && /const CORNERS = \['bottom-right', 'bottom-left'\]/.test(page)
    && /creditControls = CORNERS\.map\(corner => \{ const control = new maplibregl\.AttributionControl\(\{ compact: true, customAttribution: creditLine\(\) \}\); map\.addControl\(control, corner\); return control; \}\);/.test(page)
    && /\n\s+attribution: IMAGERY,/.test(page)],
  ['the credits are made again in the language of the moment, each folded if it was', /const folded = CORNERS\.filter\(corner => creditControls\.length && !creditOf\(corner\)\.classList\.contains\('maplibregl-compact-show'\)\);\s+for \(const control of creditControls\) map\.removeControl\(control\);[\s\S]{0,400}for \(const corner of folded\) fold\(creditOf\(corner\)\);\s+\};\s+addCredits\(\);\s+relabelled\.push\(addCredits\);/],
  // 2026-10-10, "这没有完全到左下角啊": the window's own corner, 12 px in, under the card, which ends 56 px above the foot
  ['on a wide screen the credits stand in the window\'s lower left corner, under the card, and end before the scale', page =>
    /\.maplibregl-ctrl-bottom-left \{ left: env\(safe-area-inset-left, 0px\); right: calc\(120px \+ env\(safe-area-inset-right, 0px\)\); \}/.test(page)
    && /\.maplibregl-ctrl-bottom-left \.maplibregl-ctrl\.maplibregl-ctrl-attrib \{ margin: 0 0 12px 12px; \}/.test(page)
    && /@media not all and \(max-width: 720px\) \{\s+#panel \{ max-height: calc\(100% - 68px - env\(safe-area-inset-bottom, 0px\) - var\(--kb, 0px\)\); \}/.test(page)],
  ['they are open when the page opens and fold after five seconds with the map or at its first touch; the (i) opens them', page =>
    /credits = creditOf\('bottom-left'\);/.test(page)
    && /const fold = el => \{ el\.classList\.remove\('maplibregl-compact-show'\); el\.removeAttribute\('open'\); \};/.test(page)
    && /const foldCredits = \(\) => \{ clearTimeout\(creditTimer\); fold\(credits\); \};/.test(page)
    && /const creditsSeen = \(\) => \{ if \(!SHOT\) creditTimer = setTimeout\(foldCredits, 5000\); \};/.test(page)
    && /document\.getElementById\('loading'\)\.hidden = true;\s+creditsSeen\(\);/.test(page)
    && /for \(const type of \['pointerdown', 'wheel'\]\) map\.getCanvasContainer\(\)\.addEventListener\(type, foldCredits, \{ passive: true \}\);\s+map\.on\('movestart', e => \{ if \(e\.originalEvent\) foldCredits\(\); \}\);/.test(page)
    && !/maplibregl-ctrl-attrib-button[^{]*\{[^}]*display: none/.test(page)],
  // what a finger must hit is about 44px, by an unseen margin where the control is drawn smaller
  ['touch margins round the small controls', /\.segmented button::after, \.back::after, \.gh::after, \.lang::after, \.link::after, \.swap::after, \.searchbar \.clear::after, #jumps button::after,\s+\.maplibregl-ctrl-attrib-button::after \{ content: ""; position: absolute; \}/],
  ['tabs, class buttons and quick jumps are 36px with 4px of margin either side', page => ['.segmented button { min-height: 36px; }', '.segmented button::after { inset: -4px 0; }', '.segmented.chips button { min-height: 36px; padding: 0 12px; }', '#jumps button { min-height: 36px; padding: 0 14px; }', '#jumps button::after { inset: -4px -2px; }', '.linelist button, .sugg button { min-height: 44px; }'].every(rule => page.includes(rule))],
  ['the touch rules are for a phone or any finger', /@media \(max-width: 720px\), \(pointer: coarse\) \{/],
  ['no zoom buttons under a finger', /\.maplibregl-ctrl-top-right \.maplibregl-ctrl-group \{ display: none; \}/],
  ['hover styles only where a pointer hovers', page => /@media \(hover: hover\) \{/.test(page) && !/^(?!\s)[^\n@]*:hover[^\n]*\{/m.test(page.slice(page.indexOf('/* Layout: a satellite globe'), page.indexOf('@media (hover: hover)')))],
  // the page does not scroll, select or zoom under a finger
  ['no pull-to-refresh, no rubber band', /html, body \{ height: 100%; overscroll-behavior: none; \}/],
  ['a long press does not select the card, two taps do not zoom the page', /#panel, #jumps \{ -webkit-user-select: none; user-select: none; -webkit-touch-callout: none; touch-action: manipulation; \}\s+#panel input \{ -webkit-user-select: text; user-select: text; \}/],
  // the sheet: its highest leaves the status bar and the quick jumps free, by the dynamic viewport
  ['the sheet\'s height follows the dynamic viewport and the notch', /height: calc\(100% - 64px - env\(safe-area-inset-top, 0px\)\); height: calc\(100dvh - 64px - env\(safe-area-inset-top, 0px\)\);/],
  ['the safe areas are read where the script needs them', /#safe \{[^}]*padding: env\(safe-area-inset-top, 0px\) env\(safe-area-inset-right, 0px\) env\(safe-area-inset-bottom, 0px\) env\(safe-area-inset-left, 0px\); \}[\s\S]*const safe = side => parseFloat\(getComputedStyle\(safeEl\)\['padding' \+ side\]\) \|\| 0;/],
  ['beside the map the card stands clear of the notch and the home indicator of a phone on its side', /left: calc\(12px \+ env\(safe-area-inset-left, 0px\)\); width: var\(--card-w\); max-height: calc\(100% - 24px - env\(safe-area-inset-bottom, 0px\) - var\(--kb, 0px\)\);/],
  ['a tap after a drag is a tap', /head\.addEventListener\('click', e => \{ if \(e\.timeStamp - draggedAt < 400\) \{ draggedAt = -1e9; e\.preventDefault\(\); e\.stopPropagation\(\); \} \}, true\);/],
  // framing: in the part of the map that can be seen, again when the sheet settles elsewhere
  ['the room of the map on a phone: between the quick jumps and the sheet', /\? \{ top: 64 \+ safe\('Top'\), bottom: Math\.min\(sheet\.visible\(\) \+ 44, Math\.round\(innerHeight \* 0\.62\)\), left: 16, right: 16 \}/],
  ['every frame goes through one function that remembers it', page => /const frame = \(what, duration\) => \{ framed = what; show\(what, reduced \? 0 : duration\); \};/.test(page) && (page.match(/map\.fitBounds\(/g) || []).length === 1],
  ['the viewer\'s own move ends it', /map\.on\('movestart', e => \{ if \(e\.originalEvent\) \{ touched = true; framed = null; \} \}\);/],
  ['framed again when the sheet settles at another height', /if \(framed === was && \(!was\.room \|\| Math\.abs\(was\.room\[0\] - room\[0\]\) > 16 \|\| Math\.abs\(was\.room\[1\] - room\[1\]\) > 16\)\) show\(was, reduced \? 0 : 450\);/],
  ['on a phone\'s or a tablet\'s globe the frame is reckoned on the sphere', /if \(globe && byFinger\(\)\) \{[\s\S]{0,700}map\.flyTo\(\{ \.\.\.onGlobe\(points, \[room\[0\] \* 0\.94, room\[1\] \* 0\.94\], middle, box\.clientHeight, zoom\), duration \}\);/],
  // (the map takes an undefined maxZoom for a limit and then goes nowhere: a country and a quick jump have none)
  ['beside the desktop card the frame is fitBounds as before, with a limit only where there is one', page => /else try \{ map\.fitBounds\(\[\[west, south\], \[east, north\]\], \{ padding: pad, duration, \.\.\.\(zoom \? \{ maxZoom: zoom \} : null\) \}\); \}/.test(page) && !/maxZoom: zoom\b/.test(page.replace('{ maxZoom: zoom }', ''))],
  ['the sheet goes to its height before the map is framed for it', /if \(isPhone\(\) && fly\) sheet\.to\('peek'\);[^\n]*\n\s+if \(fly && l\) frame\(/],
  // head matter a phone uses
  ['a title for the whole site, the browser bars in the page\'s ground', page => /<title>Rail Globe · 铁路网卫星图<\/title>/.test(page) && /<meta name="theme-color" content="#05090c">/.test(page) && /--ground: #05090c;/.test(page)],
  ['what the home screen needs', page => ['<meta name="apple-mobile-web-app-capable" content="yes">', '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">', '<link rel="manifest" href="manifest.webmanifest">', '<link rel="apple-touch-icon" href="apple-touch-icon.png">'].every(tag => page.includes(tag))],
  ['the home-screen files are there and agree with the page', () => {
    const manifest = JSON.parse(readFileSync(join(root, 'manifest.webmanifest'), 'utf8'));
    return manifest.display === 'standalone' && manifest.theme_color === '#05090c' && manifest.background_color === '#05090c' && manifest.start_url === '.'
      && manifest.icons.every(icon => existsSync(join(root, icon.src))) && manifest.icons.some(icon => icon.sizes === '512x512') && existsSync(join(root, 'apple-touch-icon.png'));
  }],
  // 6j. the cities of data/cities.json (2026-10-09, "地级市也加上", "其他国家城市也可以加上")
  // China's hand-made cities of rank 1 and 2 are drawn as they always were: same source, same two layers
  ['the hand-made cities keep their source and their two layers', page =>
    /const byHand = c => !c\.g && c\.r < 3;/.test(page) && /map\.addSource\('cities', \{ type: 'geojson', data: cityPoints\(cities\.filter\(byHand\), \(\) => \(\{\}\)\) \}\);/.test(page)
    && page.includes(`map.addLayer({ id: 'city-dots', type: 'circle', source: 'cities', maxzoom: 9,\n      filter: ['any', ['==', ['get', 'r'], 1], ['>=', ['zoom'], 4.6]],\n      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 3, 2, 8, 4], 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.4 } });`)
    && page.includes(`map.addLayer({ id: 'city-labels', type: 'symbol', source: 'cities', maxzoom: 9,\n      filter: ['any', ['==', ['get', 'r'], 1], ['>=', ['zoom'], 4.6]],\n      layout: { 'text-field': ['get', 'n'], 'text-font': ['sans'], 'text-size': ['interpolate', ['linear'], ['zoom'], 3, ['case', ['==', ['get', 'r'], 1], 12, 11], 8, 16],`)],
  // every other city is one layer: rank 1 always, rank 2 from 4.6, rank 3 from 6, to the same upper limit
  ['the other cities: one layer, rank 1 always, rank 2 from zoom 4.6, rank 3 from zoom 6, gone at 9 like the rest',
    page => /map\.addLayer\(\{ id: 'place-labels', type: 'symbol', source: 'places', maxzoom: 9, filter: PLACE_RANKS,/.test(page)
      && /const PLACE_RANKS = \['any', \['==', \['get', 'r'\], 1\], \['all', \['==', \['get', 'r'\], 2\], \['>=', \['zoom'\], 4\.6\]\], \['>=', \['zoom'\], 6\]\];/.test(page)],
  ['rank 1 and 2 as large as China\'s own, rank 3 smaller and dimmer', page =>
    /'text-size': \['interpolate', \['linear'\], \['zoom'\], 3, \['match', \['get', 'r'\], 1, 12, 2, 11, 9\.5\], 8, \['match', \['get', 'r'\], 3, 13, 16\]\],/.test(page)
    && /paint: \{ 'text-color': \['match', \['get', 'r'\], 3, '#cbd7e0', '#ffffff'\], 'text-halo-color': 'rgba\(8,14,18,0\.92\)', 'text-halo-width': 1\.6 \} \}\);/.test(page)],
  // where labels would sit on each other the higher rank is drawn, and in a rank the larger place
  ['collisions go by rank, then by the order of the file', page =>
    /map\.addSource\('places', \{ type: 'geojson', data: cityPoints\(cities\.filter\(c => !byHand\(c\)\), \(c, i\) => \(\{ k: c\.r \* 1000 \+ i, g: c\.g \|\| 'cn', \.\.\.\(c\.side \? \{ side: c\.side \} : \{\}\) \}\)\) \}\);/.test(page)
    && /'symbol-sort-key': \['get', 'k'\]/.test(page)],
  ['the hand-made cities are placed first: their layers lie above', page => page.indexOf("id: 'place-labels'") > 0 && page.indexOf("id: 'place-labels'") < page.indexOf("id: 'city-dots'") && page.indexOf("id: 'city-dots'") < page.indexOf("id: 'city-labels'")],
  // the dot is part of the label: no overlap allowed, neither part optional
  ['a dot of the other cities shows only with its name', page => {
    const layer = (page.match(/map\.addLayer\(\{ id: 'place-labels'[\s\S]*?\}\);\n/) || [''])[0];
    return /'icon-image': \['step', \['zoom'\], ringAt\(0\)/.test(layer) && /'text-field': \['get', 'n'\]/.test(layer) && !/optional|allow-overlap|ignore-placement/.test(layer);
  }],
  // a name that finds its place taken tries the other sides of its dot before it gives way
  ['the other cities\' names try four sides of their dot, or stand on the one their entry gives', page =>
    /const sides = first => \(first \? AROUND\[first\] : \['right', 'left', 'above', 'below'\]\.flatMap\(side => AROUND\[side\]\)\);/.test(page)
    && /'text-variable-anchor-offset': \['match', \['get', 'side'\], \.\.\.Object\.keys\(AROUND\)\.flatMap\(side => \[side, \['literal', sides\(side\)\]\]\), \['literal', sides\(\)\]\],/.test(page)
    && /\.\.\.\(c\.side \? \{ side: c\.side \} : \{\}\)/.test(page) && !/id: 'city-labels'[\s\S]{0,700}text-variable-anchor/.test(page)],
  // a name in two scripts breaks before its bracket, wherever a name is shown
  ['a name in two scripts is two pieces: it breaks before the bracket, a piece between its words', page => /const NAME_PARTS = \/\^\(\.\*\\S\) \(\\\(\[\^\(\)\]\+\\\)\)\$\/;/.test(page)
    && /\.two > bdi \{ display: inline-block; max-width: 100%; vertical-align: top; \}/.test(page)],
  // a label that names something is never cut short (2026-10-10, "换英文之后ui界面要适配一下"): names wrap
  ['no name is cut short with an ellipsis', page => !/text-overflow: ellipsis/.test(page) && /\.linelist \.nm \{ flex: 1; min-width: 0; \}/.test(page)],
  ['list rows, search rows, the selected line and the popups set their names so', page =>
    /setName\(b\.querySelector\('\.nm'\), name\);/.test(page) && (page.match(/setName\(document\.getElementById\('selName'\), /g) || []).length === 2
    && /setName\(title, named\(f\.properties, abroad\(f\.properties\.g\)\)\);/.test(page) && /`<b class="two"><bdi>\$\{esc\(parts\[1\]\)\}<\/bdi> <bdi>\$\{esc\(parts\[2\]\)\}<\/bdi><\/b>`/.test(page)
    && !/getElementById\('selName'\)\.textContent = /.test(page)],
  // a labelled city that has no metro is a place to go to
  ['a city without a metro opens its country\'s page and the map shows the city and what is round it', /\} else if \(e\.kind === 'city' && !e\.ref\) \{[\s\S]{0,260}enter\(e\.country\);[\s\S]{0,200}frame\(\{ bounds: \[\[x - wide, y - reach\], \[x \+ wide, y \+ reach\]\] \}, 1400\);/],
  ['the search is given the cities the map labels', /cities: metroCities,\s+places: cities,/],
  // 6k. China's light rail (2026-10-10, "有轻轨的加个轻轨的分类"): a class of its own beside the metro,
  // said in the same kind of configuration as the classes abroad, with no case of its own in the code
  ['China\'s classes of urban rail are configuration, as abroad', page =>
    /const HOME = worded\(\{ name: 'cn', fastWord: 'cn\.fastWord',[\s\S]{0,160}metro: \[\['subway', 'cn\.subway'\], \['urban', 'cn\.urban'\], \['suburban', 'cn\.suburban'\]\],\s+caption: \{ subway: 'cn\.subway\.caption', urban: 'cn\.urban\.caption', suburban: 'cn\.suburban\.caption' \},/.test(page)
    && /const land = g => FOREIGN\[g\] \|\| HOME;/.test(page)],
  ['one layer per class and country, China\'s among them', /const metroLayers = everyCountry\.flatMap\(g => land\(g\)\.metro\.map\(\(\[kind\]\) => \[metroId\(g, kind\), g, kind, \(land\(g\)\.thin \|\| \{\}\)\[kind\] \|\| 1\]\)\);/],
  ['China\'s metro layer keeps its name, the light rail has its own', /const metroId = \(g, kind\) => \(g !== 'cn' \? `\$\{g\}-\$\{kind\}` : kind === HOME\.metro\[0\]\[0\] \? 'metro' : kind\);/],
  ['a Chinese line with no class in the data is a metro line', /\['==', \['match', \['get', 'k'\], \.\.\.Object\.entries\(HOME\.byK\)\.flat\(\), \['coalesce', \['get', 'jk'\], HOME\.metro\[0\]\[0\]\]\], kind\]/],
  // 6l. China's suburban and intercity trains (2026-10-10, "中国分类按钮感觉不全（如市郊）", "这两个可以放到市郊/城际里面",
  // "去掉列车两字"): a class of its own, a bureau's trains (k = "s") and a metro company's (k = "m"), one row, one chip
  ['the suburban and intercity trains are a class, told by k until the data says jk', page =>
    /byK: \{ m: 'suburban', s: 'suburban' \}, beside: 'suburban', linesOnly: \['suburban'\]/.test(page)
    && /for \(const c of metroCities\) if \(!c\.g\) for \(const l of c\.lines\) if \(HOME\.byK\[l\.k\]\) l\.jk = HOME\.byK\[l\.k\];/.test(page)
    && /for \(const id of \['suburb-casing', 'suburb'\]\) set\(id, visible\[metroId\('cn', HOME\.beside\)\]\);/.test(page) && !/'row\.suburb'/.test(page)],
  ['light rail is drawn thinner and over the metro, every casing under every line', page =>
    /thin: \{ urban: 0\.6 \}/.test(page) && /homeMetro\.forEach\(casing\);\s+homeMetro\.forEach\(line\);/.test(page) && /'line-width': ownCasing\(thin\), 'line-offset': beside\(\)/.test(page) && /'line-width': sideWidth\(METRO_STOPS\.map\(\(\[z, v\]\) => \[z, thin \* v\]\)\)/.test(page)],
  ['a button for each class on China\'s lines tab', page => /const kindsOf = g => \(FOREIGN\[g\] \? \[\.\.\.FOREIGN\[g\]\.rail, \.\.\.FOREIGN\[g\]\.metro\]\.map\(\(\[id, label\]\) => \[id, label\]\) : \[\['fast', t\('kind\.fast'\)\], \['conv', t\('kind\.conv'\)\], \.\.\.HOME\.metro\]\);/.test(page)
    && /<button type="button" data-kind="subway" aria-pressed="false">地铁<\/button>\s+<button type="button" data-kind="urban" aria-pressed="false">轻轨·电车<\/button>\s+<button type="button" data-kind="suburban" aria-pressed="false">市郊·城际<\/button>/.test(page)],
  ['a class lists its own lines, by city, in every country', page => /const mCities = citiesHere\(\)\.map\(c => \(\{ \.\.\.c, lines: c\.lines\.filter\(l => l\.jk === mjk\) \}\)\)\.filter\(c => c\.lines\.length\);/.test(page)
    && /cap\.textContent = land\(country\)\.caption\[mjk\];/.test(page) && !/FOREIGN\[country\] \? kind : null/.test(page)],
  ['a row of the layers tab for each class, each with its own switch', page =>
    /\.\.\.HOME\.metro\.map\(\(\[kind\]\) => \(\{ id: metroId\('cn', kind\), spd: '', src: 'metro', metro: kind \}\)\),/.test(page)
    && /const \[label, sub\] = c\.metro \? HOME\.row\[c\.metro\] : \[t\(c\.label\), c\.sub && t\(c\.sub\)\]/.test(page)
    && /for \(const \[kind\] of HOME\.metro\) for \(const id of \[metroId\('cn', kind\), metroId\('cn', kind\) \+ '-casing'\]\) set\(id, visible\[metroId\('cn', kind\)\]\);/.test(page)],
  ['China\'s metro stations go with their lines: a tram stop with the light rail', /const theirLines = \['any', \['!', NOT_ABROAD\], \['case', \['has', 't'\], tramsOn, metroOn\]\];\s+among\('metro-stations', withMetroStations, theirLines\);\s+among\('metro-station-labels', withMetroStations, theirLines\);/],
  ['selecting and dimming take every class', /for \(const \[id, z0, thin\] of \[\.\.\.metroLayers\.map\(m => \[m\[0\], 4\.5, m\[3\]\]\), \['suburb', 6, 1\]\]\) \{/],
  ['a tap takes the thin class first', /const PICK = \[\.\.\.FAST, 'shared', \.\.\.\[\.\.\.homeMetroIds\]\.reverse\(\), 'suburb',/],
  ['China\'s figures say every class, a line each, in both languages alike', page => /: HOME\.metro\.map\(\(\[kind, label\]\) => classFacts\(g, kind, label\)\)\);/.test(page)
    && /const metroFacts = g => metroGroups\(g\)\.join\('\\n'\);/.test(page) && /\.grp \{ display: block; \}/.test(page) && /metro\.replaceChildren\(\.\.\.groupsOf\(g\)\);/.test(page)
    && /rail\.replaceChildren\(\.\.\.railLine\(g\)\);/.test(page) && /\.nobr \{ white-space: nowrap; \}/.test(page)],
  ['the search names China\'s classes as the others\', and finds a country by its name in either language', /countries: \[\{ g: 'cn', name: HOME\.name, names: TEXT\.cn, metro: HOME\.metro \},/],
  // 7. the content has one width whether the list scrolls or not, so nothing moves between tabs:
  // the track leaves its right margin to the (thin) scrollbar, and the header reserves nothing
  ['thin scrollbar, no gutter', /scrollbar-width: thin/],
  ['content width does not depend on the scrollbar', /\.tab \{[^}]*width: calc\(var\(--card-w\) - 32px\)/],
  ['track leaves its right margin to the scrollbar', /\.scroll \{[^}]*padding: 4px 0 16px 16px;/],
  ['header has plain margins', /\.head \{ padding: 16px 16px 12px;/],
  ['no measured scrollbar width', /^(?![\s\S]*--sbw)/],
  // 7b. the class buttons are chips that wrap wherever there are more than three classes, in every country (2026-10-10,
  // "中国的这个分类按钮和其他几个不一样"); the segmented control is for three or fewer
  ['class chips for more than three classes', page => /const chips = kindsOf\(country\)\.length > 3;/.test(page) && /classList\.toggle\('chips', chips\)/.test(page)],
  ['chips wrap', /\.segmented\.chips \{ display: flex; flex-wrap: wrap;/],
  // 8. grid children may not stretch the tab beyond the card (overflow clipping the toggles)
  ['tab items can shrink', /\.tab > \* \{ min-width: 0; \}/],
];

let failed = 0;
const report = (name, ok) => { if (!ok) { failed++; console.error('FAIL', name); } else console.log('ok  ', name); };
for (const [name, re] of checks) report(name, typeof re === 'function' ? re(html) : re.test(html));

// ---- the two languages: the page's own table and its t(), run here ----
const words = html.match(/\n  const TEXT = \{[\s\S]*?\n  const t = [\s\S]*?\n  \};\n/);
report('the texts are one table, with the function that reads it', !!words);
// the names from the data, made by one function in the language of the page
const naming = html.match(/\n  \/\/ ---- names from the data ----\n[\s\S]*?\n  const named = [\s\S]*?\n  \};\n/);
report('the names from the data are made by one function', !!naming);
const tongue = words && naming && new Function('location', 'localStorage', 'navigator', words[0] + naming[0] + '\nreturn { TEXT, t, named, NAMES, speak: to => { lang = to; } };')({ search: '' }, { getItem: () => null }, { languages: ['zh-CN'] });
const TEXT = tongue ? tongue.TEXT : {}, say = tongue ? tongue.t : () => '';
if (tongue) {
  const han = /[㐀-鿿]/, holes = text => [...new Set(text.match(/\{\w+\}/g) || [])].sort().join();
  const keys = Object.keys(TEXT);
  report(`every text is in both languages (${keys.length} keys)`, keys.length > 150 && keys.every(k => Array.isArray(TEXT[k]) && TEXT[k].length === 2 && TEXT[k].every(v => typeof v === 'string' && v.trim())));
  // (a long length is said by another rule in each language: 16.5 万公里, 165,000 km)
  const uneven = keys.filter(k => k !== 'km.long' && holes(TEXT[k][0]) !== holes(TEXT[k][1]));
  report('both languages fill in the same things', uneven.length === 0);
  if (uneven.length) console.error('     not the same {things}:', uneven.join(' '));
  // an English text has no Chinese in it, but for the examples of what can be typed and the name of the language itself
  const mixed = keys.filter(k => han.test(TEXT[k][1]) && !['lang.label', 'app.lang.label'].includes(k));
  report('the English is English', mixed.length === 0);
  if (mixed.length) console.error('     Chinese in the English of:', mixed.join(' '));
  // the script outside the table: every key it names is in the table, every key of the table is named
  const script = html.slice(html.indexOf('<script>\n(() => {'));
  const outside = script.replace(words[0], '\n');
  const named = new Set([...outside.matchAll(/'([a-z]+(?:\.[a-zA-Z_]+)+)'/g)].map(m => m[1]).filter(k => !/\.(json|geojson|pmtiles|html|js|css)$/.test(k)));
  const markup = html.slice(0, html.indexOf('<script>\n(() => {'));
  const inMarkup = [...markup.matchAll(/data-th?="([\w.]+)"/g)].map(m => m[1]).concat([...markup.matchAll(/data-ta="([^"]+)"/g)].flatMap(m => m[1].split(' ').map(pair => pair.split(':')[1])));
  const single = [...outside.matchAll(/\b(?:t|say)\((?:[^()'"]*, )?'([a-z]+)'/g)].map(m => m[1]);          // t('metro'), say(el, 'loading')
  const config = [...outside.matchAll(/\b(?:name|fastWord): '([a-z.]+)'/g)].map(m => m[1]).concat([...outside.matchAll(/\['(?:subway|urban|hs|semi|main|branch|heritage)', '([a-z.]+)'\]/g)].map(m => m[1]),
    [...outside.matchAll(/\b(?:subway|urban): '([a-z.]+)'/g)].map(m => m[1])).filter(k => k.includes('.') || ['metro', 'cn', 'jp', 'kr', 'uk'].includes(k));
  // Native UI reads this explicitly exported part of the same table through state.copy.
  const appExport = /const appCopy = \(\) => Object\.fromEntries\(Object\.keys\(TEXT\)\.filter\(k => k\.startsWith\('app\.'\)\)\.map\(k => \[k, t\(k\)\]\)\);/.test(outside)
    ? keys.filter(k => k.startsWith('app.')) : [];
  const used = new Set([...named, ...inMarkup, ...single, ...config, ...appExport]);
  const missing = [...used].filter(k => !(k in TEXT)), idle = keys.filter(k => !used.has(k));
  report('every text the page asks for is in the table', missing.length === 0);
  if (missing.length) console.error('     no entry for:', missing.join(' '));
  report('every entry of the table is asked for', idle.length === 0);
  if (idle.length) console.error('     never used:', idle.join(' '));
  // no words are written anywhere else in the script: only the data's own words, which are looked for and not shown
  const code = outside.replace(/\/\*DATA-WORDS\*\/[\s\S]*?\/\*DATA-WORDS-END\*\//, '').replace(/\/\*FOLD\*\/[\s\S]*?\/\*FOLD-END\*\//, '').split('\n').map(line => line.replace(/^\s*\/\/.*$|\s\/\/ .*$/, '')).filter(line => !/^\s*(\/?\*|hint: ')/.test(line));
  const stray = code.filter(line => han.test(line));
  report('no Chinese is written in the script outside the table', stray.length === 0);
  if (stray.length) console.error('     ' + stray.slice(0, 8).map(line => line.trim().slice(0, 120)).join('\n     '));
  // what the markup says before the script runs is the table's Chinese
  const said = [...markup.matchAll(/data-t="([\w.]+)"[^>]*>([^<]*)</g)].filter(m => m[2] !== TEXT[m[1]][0]).map(m => m[1])
    .concat([...markup.matchAll(/<[^>]*data-ta="([^"]+)"[^>]*>/g)].flatMap(m => m[1].split(' ').map(pair => pair.split(':')).filter(([attr, key]) => !m[0].includes(`${attr}="${TEXT[key][0]}"`)).map(([, key]) => key)));
  report('the markup\'s own words are the table\'s', said.length === 0);
  if (said.length) console.error('     differ:', said.join(' '));
  report('the title in the markup is the table\'s', markup.includes(`<title>${TEXT['doc.title'][0]}</title>`));
  // numbers: plural forms, and Chinese
  report('one line, two lines: English counts', say('n.lines', { n: 3 }) === '3 条' && (tongue.speak('en'), say('n.lines', { n: 1 }) === '1 line' && say('n.lines', { n: 3 }) === '3 lines' && say('title.country', { country: say('kr') }) === 'Korea'));
  tongue.speak('zh');
}

// ---- the names from the data (2026-10-10): the local name, then the reader's in brackets where the
// reader does not read the local writing; Japan's stations and lines as they are written for a
// Chinese reader, its cities in Chinese; nothing made up where the data has no name ----
if (tongue) {
  const same2 = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const hongqiao = { n: '上海虹桥', ne: 'Shanghai Hongqiao' }, tokyo = { n: '東京', nz: '东京', ne: 'Tokyo' }, seoul = { n: '서울', nz: '首尔', ne: 'Seoul' };
  const cases = () => [tongue.named(hongqiao), tongue.named(tokyo, 'jp'), tongue.named(tokyo, 'jp', 'city'), tongue.named(seoul, 'kr', 'city'), tongue.named({ n: 'London', nz: '伦敦' }, 'uk', 'city'),
    tongue.named({ n: 'さいたま新都心', nz: '埼玉新都心' }, 'jp'), tongue.named({ n: '首尔', nl: '서울', ne: 'Seoul' }, 'kr', 'city'), tongue.named({ n: '东京', nl: '東京', ne: 'Tokyo' }, 'jp', 'city'), tongue.named({ n: '台北' })];
  const zh = cases();
  tongue.speak('en');
  const en = cases(), choices = ['local', 'reader'].map(choice => tongue.named(hongqiao, 'cn', 'other', choice));
  tongue.speak('zh');
  report('names in Chinese: China, Japan\'s stations as written, Japan\'s cities in Chinese, 서울 (首尔), London (伦敦)',
    same2(zh, ['上海虹桥', '東京', '东京', '서울 (首尔)', 'London (伦敦)', 'さいたま新都心', '서울 (首尔)', '东京', '台北']));
  report('names in English: 上海虹桥 (Shanghai Hongqiao), 東京 (Tokyo), 서울 (Seoul), London, and the local name alone where there is no English one',
    same2(en, ['上海虹桥 (Shanghai Hongqiao)', '東京 (Tokyo)', '東京 (Tokyo)', '서울 (Seoul)', 'London', 'さいたま新都心', '서울 (Seoul)', '東京 (Tokyo)', '台北']));
  // a space before the bracket (2026-10-10, "括号应该和前面的本名有个空格"), and every bracket half-width,
  // the data's own too, for the eye only: the name in the data is its key and stays
  const own = { n: '三林南（在建）', ne: 'Sanlin South' };
  const ownZh = tongue.named(own);
  tongue.speak('en');
  const ownEn = tongue.named(own);
  tongue.speak('zh');
  report('a bracket the data\'s name has itself is shown half-width, where it is; the name itself is not changed',
    ownZh === '三林南(在建)' && ownEn === '三林南(在建) (Sanlin South)' && own.n === '三林南（在建）');
  // a number and its unit are not parted at the end of a line: 350 km/h, 16.5 万公里
  tongue.speak('en');
  const units = [tongue.t('speed.line', { speed: 350 }), tongue.t('km', { n: '4,715' })];
  tongue.speak('zh');
  units.push(tongue.t('km.long', { wan: '16.5' }));
  report('a number and its unit stay on one line', JSON.stringify(units) === JSON.stringify(['Line designed for 350\u00a0km/h', '4,715\u00a0km', '16.5\u00a0万公里'])
    && !/\$\{[^}]+\} km(?:\/h)?[`<]/.test(html));
  report('the page\'s choice is one line, and the other two choices give the local or the reader\'s name alone',
    /\n  const NAMES = \{ map: 'both', card: 'both' \};\n/.test(html) && same2(choices, ['上海虹桥', 'Shanghai Hongqiao']));
}

// ---- the page's script compiles: a name declared twice in one scope stops the whole page ----
{
  const script = [...readFileSync(join(root, 'index.html'), 'utf8').matchAll(/<script>([\s\S]*?)<\/script>/g)].pop()[1];
  let error = null;
  try { new Function(script); } catch (err) { error = err; }
  report('the page\'s script compiles', !error);
  if (error) console.error('     ', error.message);
}

// ---- every bracket the page writes is half-width (2026-10-10, "括号都用半角的"): its table, its markup, its notes ----
{
  const written = html.replace(/\n\s*const halfWidth = [^\n]*\n/, '\n').replace(/\n\s*const halfWidthOf = [^\n]*\n/, '\n');
  const wide = [...written.matchAll(/[^\n]{0,20}[（）【】〈〉][^\n]{0,20}/g)].map(m => m[0]);
  report('no full-width bracket in the page, but in the two lines that turn the data\'s into half-width ones', wide.length === 0);
  if (wide.length) console.error('     full-width:', wide.slice(0, 6).join(' | '));
}

// ---- the search, run: the block of the page between the two marks holds the two functions ----
const core = html.match(/\/\*SEARCH-CORE\*\/([\s\S]*?)\/\*SEARCH-CORE-END\*\//);
report('the search functions stand apart from the page', !!core && !/(^|[^.\w])(?:document|window|FOREIGN|map\.|col\()/.test(core[1].replace(/\/\/[^\n]*/g, '')));
if (core) {
  const { buildSearchIndex, searchIndex, nameMetroCities } = new Function(core[1] + '\nreturn { buildSearchIndex, searchIndex, nameMetroCities };')();
  const named = tongue ? tongue.named : p => p.n, home = g => g || 'cn';
  const point = (n, x, y, more) => ({ type: 'Feature', properties: { n, ...more }, geometry: { type: 'Point', coordinates: [x, y] } });
  const colours = { hsr350: '#c995dd', hsr250: '#2787d5', main: '#d7ecff' };
  const small = buildSearchIndex({ say,
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
  report('search: a line says what it is and has its colour', line.kind === 'line' && line.sub === '动车(含高铁) · 350\u00a0km/h' && line.colour === '#c995dd');
  report('search: a conventional line has no speed', find('京沪线')[0].results[0].sub === '普速铁路');
  const yamanote = find('山手', { country: 'cn' })[0].results[0];
  report('search: a line abroad carries its class and its own colour', yamanote.country === 'jp' && yamanote.sub === 'JR在来线' && yamanote.colour === '#9acd32');
  report('search: a high-speed line abroad carries its band colour and speed', (r => r.sub === '新干线 · 260\u00a0km/h' && r.colour === '#2787d5')(find('新幹線')[0].results[0]));
  const ginza = find('銀座')[0].results[0];
  report('search: a metro line names its city and has its colour', ginza.kind === 'metro' && ginza.sub === '地下铁 · 东京' && ginza.colour === '#ff9500');
  report('search: a country is found by its name', (r => r.kind === 'country' && r.id === 'country:jp')(find('日本')[0].results[0]));
  report('search: exact names first, then cities before lines before stations',
    same(names(find('北京', { country: 'cn' })[0]), ['北京', '北京地铁1号线', '北京南', '北京东']));
  report('search: Latin names whatever the case', same(names(find('central', { country: 'uk' })[0]), ['Central line', 'Central Wales Line']) && names(find('CENTRAL LINE')[0])[0] === 'Central line');
  report('search: the forms of a character are one (2026-10-10): 东京 and 東京 find both the city and the station, what was typed exactly first',
    same(find('东京').flatMap(g => g.results.map(r => r.kind)), ['city', 'station']) && same(find('東京').flatMap(g => g.results.map(r => r.kind)), ['station', 'city']));
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
  const crowd = buildSearchIndex({ say, countries: [{ g: 'cn', name: '中国' }], colours, lines: [],
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
  const twice = buildSearchIndex({ say, countries: [{ g: 'cn', name: '中国' }], colours, cities: [],
    lines: [{ n: '京沪线', g: 'cn', kind: 'conv', c: 'main' }, { n: '京沪线', g: 'cn', kind: 'conv', c: 'main' }],
    stations: [point('汉阳', 114.2, 30.55, { g: 1 }), point('汉阳', 114.2, 30.55, { g: 2 })] });
  report('search: a line given twice is one line, two stations on one spot stay two',
    searchIndex(twice, '京沪')[0].total === 1 && searchIndex(twice, '汉阳', { merge: false })[0].total === 2 && new Set(searchIndex(twice, '汉阳', { merge: false })[0].results.map(r => r.id)).size === 2);
  // the cities the map labels: a place each, the one with a metro only once, the country in the key
  const placesHere = [{ n: '南京', at: [118.8, 32.06], r: 1, ne: 'Nanjing' }, { n: '保定', at: [115.49, 38.86], r: 3, ne: 'Baoding' }, { n: '丽水', at: [119.92, 28.47], r: 3, ne: 'Lishui' },
    { n: '서울', at: [126.98, 37.57], r: 1, g: 'kr', nz: '首尔', ne: 'Seoul', m: '首尔' }, { n: '여수', at: [127.66, 34.75], r: 2, g: 'kr', nz: '丽水', ne: 'Yeosu' }, { n: '춘천', at: [127.73, 37.88], r: 2, g: 'kr', nz: '春川', ne: 'Chuncheon' }];
  const citiesHere = [{ n: '南京', lines: [{ n: '南京地铁2号线', col: '#c7003f' }] }, { n: '首尔', g: 'kr', lines: [{ n: '서울 지하철 2호선', col: '#00a84d', jk: 'subway' }] }];
  nameMetroCities(citiesHere, placesHere, home);
  const labelled = buildSearchIndex({ say, name: named, countries: [{ g: 'cn', name: '中国' }, { g: 'kr', name: '韩国', metro: [['subway', '地铁']] }], colours, lines: [], stations: [],
    cities: citiesHere, places: placesHere });
  const city = (q, options) => searchIndex(labelled, q, options).flatMap(g => g.results).filter(r => r.kind === 'city');
  report('search: a labelled city without a metro is found as a city, with its place',
    same(city('保定').map(r => [r.country, r.name, r.sub]), [['cn', '保定', '城市']]) && same(labelled.byId.get(city('保定')[0].id).at, [115.49, 38.86]) && !labelled.byId.get(city('保定')[0].id).ref
    && same(city('baoding').map(r => r.name), ['保定']));
  report('search: a labelled city that has a metro is the metro city, once', same(city('南京').map(r => r.sub), ['地铁 · 1 条线路']) && same(city('首尔').map(r => [r.country, r.sub, r.id]), [['kr', '地铁 · 1 条线路', 'city:首尔']]));
  report('search: a city named in two scripts is found by either, also when the metro list has only one of them',
    same(city('首尔').map(r => r.name), ['서울 (首尔)']) && same(city('서울').map(r => r.name), ['서울 (首尔)']) && !!labelled.byId.get(city('서울')[0].id).ref
    && same(city('春川').map(r => [r.name, r.sub]), [['춘천 (春川)', '城市']]) && same(city('춘천').map(r => r.name), ['춘천 (春川)'])
    && same(searchIndex(labelled, '首尔 지하철').flatMap(g => g.results).filter(r => r.kind === 'metro').map(r => r.sub), ['地铁 · 서울 (首尔)'])
    && same(city('seoul').map(r => r.name), ['서울 (首尔)']) && same(citiesHere[1].nl, '서울') && !('nl' in citiesHere[0]) && citiesHere[0].ne === 'Nanjing');
  report('search: a name that is a city in two countries is found in both, each in its country',
    same(city('丽水', { country: 'cn' }).map(r => [r.country, r.name]), [['cn', '丽水'], ['kr', '여수 (丽水)']]) && new Set(city('丽水').map(r => r.id)).size === 2 && labelled.byId.get(city('丽水', { country: 'kr' })[0].id).at[0] === 127.66);
  // in English the same things are shown by their English names, and found by every name
  if (tongue) {
    tongue.speak('en');
    const english = buildSearchIndex({ say, name: named, countries: [{ g: 'cn', name: 'China' }, { g: 'kr', name: 'Korea', metro: [['subway', 'Metro']] }], colours, lines: [], stations: [],
      cities: citiesHere, places: placesHere });
    const cityEn = q => searchIndex(english, q).flatMap(g => g.results).filter(r => r.kind === 'city').map(r => r.name);
    report('search in English: the names in English, every name finds',
      same(cityEn('Seoul'), ['서울 (Seoul)']) && same(cityEn('首尔'), ['서울 (Seoul)']) && same(cityEn('서울'), ['서울 (Seoul)']) && same(cityEn('南京'), ['南京 (Nanjing)']) && same(cityEn('nanjing'), ['南京 (Nanjing)']));
    tongue.speak('zh');
  }
  report('search: a result is still a plain object with six fields', city('丽水').every(r => same(Object.keys(r), ['kind', 'country', 'name', 'sub', 'colour', 'id'])));
  const rails = buildSearchIndex({ say, countries: [{ g: 'cn', name: '中国', metro: [['subway', '地铁'], ['urban', '轻轨']] }], colours, lines: [], stations: [], places: [['三亚', 109.51, 18.25, 2]],
    cities: [{ n: '沈阳', lines: [{ n: '沈阳地铁9号线', col: '#f9a01b', jk: 'subway' }, { n: '沈阳有轨电车5号线', col: '#3b6ea5', jk: 'urban' }] },
      { n: '三亚', lines: [{ n: '三亚有轨电车示范线', col: '#00a0e9', jk: 'urban' }] }, { n: '北京', lines: [{ n: '北京地铁1号线', col: '#a12830' }] }] });
  const rail = q => searchIndex(rails, q).flatMap(g => g.results);
  report('search: a light-rail line says so, a metro line says metro, a line with no class is a metro line',
    same(rail('有轨电车5号线').map(r => r.sub), ['轻轨 · 沈阳']) && same(rail('沈阳地铁9').map(r => r.sub), ['地铁 · 沈阳']) && same(rail('北京地铁1').map(r => r.sub), ['地铁 · 北京']));
  report('search: a city is said to have a metro, unless light rail is all it has',
    same(rail('沈阳').filter(r => r.kind === 'city').map(r => r.sub), ['地铁 · 2 条线路']) && same(rail('三亚').filter(r => r.kind === 'city').map(r => r.sub), ['轻轨 · 1 条线路']));
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
    const places = data('cities.json');
    nameMetroCities(cities, places, home);
    const real = buildSearchIndex({ say, name: named, countries: [{ g: 'cn', name: '中国' }, ...abroad.map(g => ({ g, name: names_[g], kindName: {}, metro: [] }))], lines, cities, places, stations, colours });
    const t0 = performance.now();
    const tokyo = searchIndex(real, '東京', { country: 'cn' });
    const took = performance.now() - t0;
    report(`search on the data: ${real.entries.length} things, one query in ${took.toFixed(1)} ms`, real.entries.length > 20000 && took < 200);
    if (abroad.includes('jp')) report('search on the data: 東京 finds the station in Japan from the card of China',
      tokyo.some(g => g.country === 'jp' && g.results.some(r => r.kind === 'station' && r.name === '東京')));
    report('search on the data: 上海虹桥 is a station, 上海 a city first', searchIndex(real, '上海虹桥')[0].results[0].kind === 'station' && searchIndex(real, '上海', { country: 'cn' })[0].results[0].kind === 'city');
    // every city the map labels is found by the name it is labelled with, in its country, as a city
    const here = places.filter(p => !p.g || abroad.includes(p.g));
    const cityRows = (q, g) => searchIndex(real, q, { country: g, countries: [g], kinds: ['city'], limit: 50 }).flatMap(group => group.results);
    const shownAs = p => named(p, home(p.g), 'city');
    // (by every name it carries: its own, and in Chinese and English where it has them)
    const lost = here.filter(p => [p.n, p.nz, p.ne].filter(Boolean).some(q => !cityRows(q, home(p.g)).some(r => r.name === shownAs(p))));
    report(`search on the data: each of the ${here.length} labelled cities is found by each of its names in its country`, here.length > 400 && lost.length === 0);
    if (lost.length) console.error('     not found:', lost.slice(0, 12).map(c => c.n).join(' '));
    // a metro city and the label of the same place are one thing: no city is listed twice in a country
    const twice = here.filter(p => cityRows(p.n, home(p.g)).filter(r => r.name === shownAs(p)).length !== 1);
    report('search on the data: no city is listed twice in its country', twice.length === 0);
    if (twice.length) console.error('     twice:', twice.slice(0, 12).map(c => c.n).join(' '));
    // a label that names its metro city names one the metro list has, and that city is then the one entry
    const strays = here.filter(p => p.m && !(cities.some(c => c.n === p.m && home(c.g) === home(p.g)) && cityRows(p.m, home(p.g)).length === 1 && cityRows(p.m, home(p.g))[0].name === shownAs(p)));
    report('search on the data: a label in two scripts and its metro city are one entry, under the label', strays.length === 0);
    if (strays.length) console.error('     not one:', strays.map(c => c.n).join(' '));
    if (abroad.includes('kr')) report('search on the data: 首尔 and 서울 both find the city, with its metro lines',
      ['首尔', '서울'].every(q => (r => r.length === 1 && r[0].name === '서울 (首尔)' && r[0].sub.startsWith('地铁'))(cityRows(q, 'kr'))));
    if (abroad.includes('uk')) report('search on the data: 伦敦 and London both find the city', ['伦敦', 'London', 'london'].every(q => cityRows(q, 'uk').some(r => r.name === 'London (伦敦)')));
    // the forms of a character are one (2026-10-10, "山形新干线" typed for 山形新幹線): Japanese and traditional forms
    // are found by the simplified ones and the other way round; the name as typed stays first
    const rowsOf = (q, g) => searchIndex(real, q, { country: g, countries: [g], limit: 60 }).flatMap(group => group.results);
    if (abroad.includes('jp')) {
      report('search on the data: 山形新干线 finds 山形新幹線', rowsOf('山形新干线', 'jp').some(r => r.kind === 'line' && r.name.startsWith('山形新幹線')));
      report('search on the data: 东京 finds the city and the station 東京', (r => r[0].kind === 'city' && r[0].name === '东京' && r.some(x => x.kind === 'station' && x.name.startsWith('東京')))(rowsOf('东京', 'jp')));
      report('search on the data: 广岛 finds 広島', rowsOf('广岛', 'jp').some(r => r.kind === 'station' && r.name.startsWith('広島')));
      const osaka = cities.find(c => c.n === '大阪' && c.g === 'jp').lines.filter(l => l.jk === 'subway').map(l => l.n);
      const found = rowsOf('大阪地铁', 'jp').filter(r => r.kind === 'metro').map(r => real.byId.get(r.id).ref[1].n);
      report(`search on the data: 大阪地铁 finds Osaka's ${osaka.length} metro lines`, osaka.length > 5 && osaka.every(n => found.includes(n)));
      report('search on the data: a city name alone does not bring up its metro lines by the metro word', !rowsOf('大阪', 'jp').some(r => r.kind === 'metro' && !/大阪/.test(r.name)));
    }
    const iron = searchIndex(real, '铁');
    report(`search on the data: 铁 alone: ${iron.map(g => g.country + ' ' + g.total).join(', ')}; the rows stay within the cap`,
      iron.length > 0 && iron.every(g => g.results.length <= 12) && (r => r[0].results.length <= 12 && r.slice(1).every(g => g.results.length <= 6))(searchIndex(real, '铁', { country: 'cn' })));
    // what the field suggests typing must be findable in that country
    // (in both languages: an English reader is offered Shanghai Hongqiao, Tokyo, Seoul, London)
    const hints = [['cn', 'search.example'], ...abroad.map(g => [g, (html.match(new RegExp(`\\n    ${g}: \\{[\\s\\S]*?hint: '([^']+)'`)) || [])[1]])];
    for (const [g, key] of hints) for (const hint of TEXT[key] || [undefined]) {
      report(`search on the data: the example for ${g} (${hint}) is found there`,
        !!hint && searchIndex(real, hint, { country: g, countries: [g] }).length === 1);
    }
    // and the names the empty search offers are found too
    const offered = ((TEXT['found.none'] || [])[1] || '').replace(/^[^:]*: |^Nothing found\. Try a name such as /, '').replace(/\.$/, '').split(/, | or /);
    report(`search on the data: the names the English empty search offers are found (${offered.join(' | ')})`, offered.length === 4 && offered.every(q => searchIndex(real, q).length > 0));
  }
}
// ---- China's classes of urban rail on the data: each line is in one list, each feature on one layer ----
// The lists come from the class of each line (jk, or k through HOME.byK); the layers from the filters
// the page builds, worked out here on the features of data/metro.geojson.
{
  const byK = (html.match(/byK: (\{[^}]*\})/) || [])[1], kinds = [...((html.match(/metro: \[(\['subway'[^\n]*?)\],\n/) || [])[1] || '').matchAll(/\['(\w+)', '[\w.]+'\]/g)].map(m => m[1]);
  const classOfText = (html.match(/const classOf = (\(g, kind\) => \(g === 'cn'[\s\S]*?\]\]\)\);)\n/) || [])[1];
  const besideFilter = (html.match(/map\.addLayer\(\{ id: 'suburb', type: 'line', \.\.\.from\('metro'\), minzoom: 6, filter: (\[[^\n]*?\]), layout/) || [])[1];
  report('the classes, their filters and the layer beside are where this check looks for them', !!(byK && kinds.length === 3 && classOfText && besideFilter));
  const file = join(root, 'data', 'metro_cities.json');
  if (byK && kinds.length === 3 && classOfText && besideFilter && existsSync(file)) {
    const BYK = new Function('return ' + byK)(), HOME = { byK: BYK, metro: kinds.map(k => [k]) };
    const NOT_ABROAD = ['match', ['coalesce', ['get', 'g'], ''], ['jp', 'kr', 'uk', '-'], false, true];
    const classOf = new Function('NOT_ABROAD', 'HOME', 'return ' + classOfText.replace(/;$/, ''))(NOT_ABROAD, HOME);
    const ev = (e, p, zoom) => {
      if (!Array.isArray(e)) return e;
      const [op, ...a] = e;
      if (op === 'all') return a.every(x => ev(x, p, zoom));
      if (op === 'any') return a.some(x => ev(x, p, zoom));
      if (op === '!') return !ev(a[0], p, zoom);
      if (op === '==') return ev(a[0], p, zoom) === ev(a[1], p, zoom);
      if (op === '!=') return ev(a[0], p, zoom) !== ev(a[1], p, zoom);
      if (op === '>=') return ev(a[0], p, zoom) >= ev(a[1], p, zoom);
      if (op === 'get') return p[a[0]] ?? null;
      if (op === 'zoom') return zoom;
      if (op === 'coalesce') { for (const x of a) { const v = ev(x, p, zoom); if (v != null) return v; } return null; }
      if (op === 'match') { const v = ev(a[0], p, zoom); for (let i = 1; i < a.length - 1; i += 2) if ((Array.isArray(a[i]) ? a[i] : [a[i]]).includes(v)) return ev(a[i + 1], p, zoom); return ev(a[a.length - 1], p, zoom); }
      throw new Error('no ' + op);
    };
    const cities = JSON.parse(readFileSync(file, 'utf8'));
    for (const c of cities) for (const l of c.lines) if (BYK[l.k]) l.jk = BYK[l.k];          // as the page does
    const lines = cities.flatMap(c => c.lines.map(l => ({ ...l, city: c.n })));
    const lists = l => kinds.filter(k => (l.jk || kinds[0]) === k);
    const trains = lines.filter(l => BYK[l.k]).map(l => l.n).sort();
    report(`the lists: every one of China's ${lines.length} metro-list lines is in one class, the ${trains.length} suburban and intercity trains in theirs`,
      lines.every(l => lists(l).length === 1) && trains.length === 16 && lines.filter(l => lists(l)[0] === 'suburban').map(l => l.n).sort().join() === trains.join()
      && !cities.some(c => /城际$/.test(c.n) && c.lines.some(l => l.jk !== 'suburban')));
    const feats = JSON.parse(readFileSync(join(root, 'data', 'metro.geojson'), 'utf8')).features.filter(f => ev(NOT_ABROAD, f.properties, 10));
    const beside = new Function('return ' + besideFilter)();
    const drawnBy = p => [...kinds.filter(k => ev(classOf('cn', k), p, 10)), ...(ev(beside, p, 10) ? ['suburban'] : [])];
    const off = feats.filter(f => drawnBy(f.properties).includes('suburban'));
    report(`the layers: every feature of China's metro is drawn by one class's layers; the switch of the suburban and intercity trains takes ${off.length} features, of exactly the 16 lines`,
      feats.every(f => drawnBy(f.properties).length === 1) && [...new Set(off.map(f => f.properties.n))].sort().join() === trains.join());
  }
}
// ---- the map's labels: the style has no replace, so the page swaps the data's full-width brackets in its own expression;
// worked out here as the map would ----
{
  const code = (html.match(/\n\s*let swaps = 0;[^\n]*\n\s*const swap = [\s\S]*?\n\s*const halfWidthOf = [^\n]*\n/) || [''])[0];
  report('the map\'s labels turn the data\'s brackets half-width, by an expression of the style', !!code);
  if (code) {
    const halfWidthOf = new Function(code + '\nreturn halfWidthOf;')();
    const run = (e, p, scope = {}) => {
      if (!Array.isArray(e)) return e;
      const [op, ...a] = e;
      if (op === 'get') return p[a[0]] ?? null;
      if (op === 'let') { const inner = { ...scope }; for (let i = 0; i < a.length - 1; i += 2) inner[a[i]] = run(a[i + 1], p, scope); return run(a[a.length - 1], p, inner); }
      if (op === 'var') return scope[a[0]];
      if (op === 'index-of') return String(run(a[1], p, scope)).indexOf(run(a[0], p, scope));
      if (op === 'slice') { const v = String(run(a[0], p, scope)); return a.length > 2 ? v.slice(run(a[1], p, scope), run(a[2], p, scope)) : v.slice(run(a[1], p, scope)); }
      if (op === 'concat') return a.map(x => run(x, p, scope)).join('');
      if (op === '+') return a.reduce((t, x) => t + run(x, p, scope), 0);
      if (op === '>=') return run(a[0], p, scope) >= run(a[1], p, scope);
      if (op === 'case') { for (let i = 0; i < a.length - 1; i += 2) if (run(a[i], p, scope)) return run(a[i + 1], p, scope); return run(a[a.length - 1], p, scope); }
      if (op === 'coalesce') { for (const x of a) { const v = run(x, p, scope); if (v != null) return v; } return null; }
      throw new Error('no ' + op);
    };
    const cases = { '三林南（在建）': '三林南(在建)', '上環（西港城）總站': '上環(西港城)總站', 'A（1）B（2）': 'A(1)B(2)', '上海虹桥': '上海虹桥' };
    report('...and each of the data\'s names comes out half-width, up to two brackets of each kind', Object.entries(cases).every(([n, want]) => run(halfWidthOf(['get', 'n']), { n }) === want));
  }
}
// ---- a line picked on the map is named from the lists (2026-10-10: a Korean line showed no Chinese name):
// the tiles carry a line's own name only, the lists carry the others ----
{
  const code = (html.match(/\n\s*const cityByName = new Map[^\n]*\n[\s\S]*?\n\s*const lineOf = [^\n]*\n/) || [''])[0];
  report('a line on the map is named by the list that holds it', !!code && /const called = p\.n \? named\(lineOf\(p\), abroad\(p\.g\)\) : t\('tip\.unnamed'\)/.test(html)
    && /tip\.shares', \{ line: named\(lineOf\(sh\.properties\)\) \}/.test(html) && /tip\.suburban', \{ line: named\(lineOf\(sv\.properties\)\) \}/.test(html)
    && /p\.on\.split\(AND\)\.map\(n => named\(lineOf\(\{ n, g: p\.g \}\)\)\)\.join\(t\('list\.and'\)\)/.test(html)
    && /named\(railByKey\.get\('cn\/' \+ st\.name\) \|\| metroByName\.get\(st\.name\) \|\| \{ n: st\.name \}\)/.test(html) && !/named\((?:p|sh\.properties|sv\.properties)\)/.test(html));
  if (code && tongue) {
    const abroad = g => (['jp', 'kr', 'uk'].includes(g) ? g : 'cn');
    const lines = [{ n: '경부고속선', g: 'kr', nz: '京釜高速线', ne: 'Gyeongbu HSL' }, { n: '京沪高铁', g: 'cn', ne: 'Beijing–Shanghai HSR' }];
    const metroCities = [{ n: '首尔', g: 'kr', lines: [{ n: '서울 지하철 2호선', nz: '首尔地铁2号线', ne: 'Seoul Subway Line 2' }] }, { n: '上海', lines: [{ n: '上海地铁2号线', ne: 'Shanghai Metro Line 2' }] }];
    const lineOf = new Function('lines', 'metroCities', 'abroad', code + '\nreturn lineOf;')(lines, metroCities, abroad);
    const say = (p, g) => tongue.named(lineOf(p), g);
    const zh = [say({ n: '경부고속선', g: 'kr', c: 'hsr300' }, 'kr'), say({ n: '서울 지하철 2호선', g: 'kr', ct: '首尔' }, 'kr'), say({ n: '京沪高铁', c: 'hsr350' }, 'cn'), say({ n: '남부내륙선', g: 'kr', c: 'build' }, 'kr')];
    tongue.speak('en');
    const en = [say({ n: '경부고속선', g: 'kr' }, 'kr'), say({ n: '京沪高铁' }, 'cn'), say({ n: '上海地铁2号线', ct: '上海' }, 'cn')];
    tongue.speak('zh');
    report('a line feature with only its own name gets its Chinese and English names from the list; one in no list keeps its own',
      JSON.stringify(zh) === JSON.stringify(['경부고속선 (京釜高速线)', '서울 지하철 2호선 (首尔地铁2号线)', '京沪高铁', '남부내륙선'])
      && JSON.stringify(en) === JSON.stringify(['경부고속선 (Gyeongbu HSL)', '京沪高铁 (Beijing–Shanghai HSR)', '上海地铁2号线 (Shanghai Metro Line 2)']));
  }
}
// ---- lines side by side (2026-10-10, "都要follow 中国平行线的画法，如北京市郊"): China's suburban guest is the drawing
// for all. Every offset of the page is made by beside(); for each country and class, a line beside another stands
// as far from it and is as wide as the suburban guest beside its national line, at z6, 9, 12 and 15 ----
{
  const offsets = [...html.matchAll(/'line-offset': ([^,}]+?)\s*[,}]/g)].map(m => m[1].trim());
  const made = new Set([...html.matchAll(/const (\w+) = beside\(/g)].map(m => m[1]));
  const strays = offsets.filter(o => !o.startsWith('beside(') && !made.has(o));
  report(`every line offset of the page (${offsets.length}) is made by the one drawing, beside()`, offsets.length > 15 && strays.length === 0);
  if (strays.length) console.error('     not by beside():', strays.join(' | '));
  report('the suburban guest is drawn by the guest drawing, the high-speed guest too',
    /const besideHost = beside\(\{ guest: true \}\);/.test(html) && /'line-width': guestWidth, 'line-offset': besideHost/.test(html) && /'line-width': ownCasing\(1\), 'line-offset': besideHost/.test(html)
    && /const besideFast = beside\(\{ guest: true \}\);/.test(html) && /set\('shared', FAST_COLOR, guestWidth,/.test(html));
  const code = (html.match(/\n\s*const slot = \['coalesce', \['get', 'off'\], 0\][^\n]*\n[\s\S]*?\n\s*const railOff = beside\(\{ apart: true \}\);\n/) || [''])[0];
  report('the drawing is one block of the page', !!code);
  if (code) {
    const rule = new Function('FAST', code + '\nreturn { beside, sideWidth, guestWidth, ownCasing, plainOf, fastOf, METRO_STOPS, GUEST, LINE, railOff };')(['hsr400', 'hsr350', 'hsr300', 'hsr250', 'hsr200', 'hsr160', 'hsrslow']);
    const run = (e, p, z) => {
      if (!Array.isArray(e)) return e;
      const [op, ...a] = e;
      if (op === 'zoom') return z;
      if (op === 'get') return p[a[0]] ?? null;
      if (op === 'has') return a[0] in p;
      if (op === 'literal') return a[0];
      if (op === 'coalesce') { for (const x of a) { const v = run(x, p, z); if (v != null) return v; } return null; }
      if (op === '*') return a.reduce((t, x) => t * run(x, p, z), 1);
      if (op === '+') return a.reduce((t, x) => t + run(x, p, z), 0);
      if (op === '-') return run(a[0], p, z) - run(a[1], p, z);
      if (op === '==') return run(a[0], p, z) === run(a[1], p, z);
      if (op === '!=') return run(a[0], p, z) !== run(a[1], p, z);
      if (op === 'in') return run(a[1], p, z).includes(run(a[0], p, z));
      if (op === '<') return run(a[0], p, z) < run(a[1], p, z);
      if (op === '>=') return run(a[0], p, z) >= run(a[1], p, z);
      if (op === '!') return !run(a[0], p, z);
      if (op === 'all') return a.every(x => run(x, p, z));
      if (op === 'any') return a.some(x => run(x, p, z));
      if (op === 'case') {
        if (a.length < 3 || a.length % 2 !== 1) throw new Error('case requires a condition, a result, and a fallback');
        for (let i = 0; i < a.length - 1; i += 2) if (run(a[i], p, z)) return run(a[i + 1], p, z);
        return run(a[a.length - 1], p, z);
      }
      if (op === 'interpolate') {
        const [kind, , ...stops] = a, base = kind[0] === 'exponential' ? kind[1] : 1;
        const pts = []; for (let i = 0; i < stops.length; i += 2) pts.push([stops[i], stops[i + 1]]);
        if (z <= pts[0][0]) return run(pts[0][1], p, z);
        if (z >= pts[pts.length - 1][0]) return run(pts[pts.length - 1][1], p, z);
        const i = pts.findIndex(([at]) => at > z) - 1, [[z0, e0], [z1, e1]] = [pts[i], pts[i + 1]];
        const k = base === 1 ? (z - z0) / (z1 - z0) : (base ** (z - z0) - 1) / (base ** (z1 - z0) - 1);
        return run(e0, p, z) + (run(e1, p, z) - run(e0, p, z)) * k;
      }
      throw new Error('no ' + op);
    };
    const zooms = [6, 9, 12, 15];
    // the reference: the suburban guest beside its national line
    const ref = zooms.map(z => [+run(rule.beside({ guest: true }), {}, z).toFixed(2), +run(rule.guestWidth, {}, z).toFixed(2)]);
    // a pair of a bundle: one step apart (from one to the other), each the guest's width
    // (the second line of the pair is the guest: its width; the first, of the lowest slot, is the host)
    const pairOf = (offset, width, a, b, at = zooms) => at.map(z => [+Math.abs(run(offset, a, z) - run(offset, b, z)).toFixed(2), +run(width, b, z).toFixed(2)]);
    // (lines on tracks of their own are on their way back onto them from z14.5: they are compared up to there)
    const apartZooms = [6, 9, 12, 14.5], refApart = apartZooms.map(z => [+run(rule.beside({ guest: true }), {}, z).toFixed(2), +run(rule.guestWidth, {}, z).toFixed(2)]);
    const tramStops = rule.METRO_STOPS.map(([z, v]) => [z, 0.6 * v]), metroStops = rule.METRO_STOPS;
    const cases = {
      'China high-speed guest': zooms.map(z => [+run(rule.beside({ guest: true }), {}, z).toFixed(2), +run(rule.guestWidth, {}, z).toFixed(2)]),
      'Japan own-colour pair (山形 / 奥羽)': pairOf(rule.railOff, rule.sideWidth(rule.plainOf), { off: -0.5, c: 'main', lc: '#ee7b28', sh: 1 }, { off: 0.5, c: 'main', lc: '#ff9a3d', sh: 1 }),
      'UK pair in a speed band (tracks of their own)': pairOf(rule.railOff, rule.sideWidth(rule.fastOf), { off: -0.5, c: 'hsr300' }, { off: 0.5, c: 'hsr300' }, apartZooms),
      'Korea main-line pair (tracks of their own)': pairOf(rule.railOff, rule.sideWidth(rule.plainOf), { off: -0.5, c: 'main' }, { off: 0.5, c: 'main' }, apartZooms),
      'tram pair': pairOf(rule.beside(), rule.sideWidth(tramStops), { off: -0.5 }, { off: 0.5 }),
      'metro pair': pairOf(rule.beside(), rule.sideWidth(metroStops), { off: -0.5 }, { off: 0.5 }),
    };
    const off = Object.entries(cases).filter(([name, v]) => v.some(([d, w], i) => { const r = /their own/.test(name) ? refApart : ref; return Math.abs(d - r[i][0]) > 0.1 || Math.abs(w - r[i][1]) > 0.1; }));
    report(`every country and class stands and is drawn as the suburban guest at z6, 9, 12 and 15 (${JSON.stringify(ref)} px: step, width)`, off.length === 0);
    if (off.length) console.error('     not as the guest:', JSON.stringify(Object.fromEntries(off)));
    // the host of a bundle, the line of the lowest slot, keeps its own look, as the national line at 沙河 does:
    // its own width; the data's lead mark where it has one, else a negative slot (right for a pair)
    const ownAt12 = +run(rule.sideWidth(rule.plainOf), { c: 'main', lc: '#ee7b28' }, 12).toFixed(2);
    report(`the host of a bundle keeps its own look (${ownAt12} px at z12), its guests the guest's; the data's lead mark decides where it is given`,
      +run(rule.sideWidth(rule.plainOf), { off: -0.5, c: 'main', lc: '#ee7b28' }, 12).toFixed(2) === ownAt12
      && +run(rule.sideWidth(rule.plainOf), { off: 0.5, c: 'main', lc: '#ff9a3d' }, 12).toFixed(2) === 2.6
      && +run(rule.sideWidth(rule.plainOf), { off: -1, lead: 0, bn: 3, c: 'main', lc: '#ee7b28' }, 12).toFixed(2) === 2.6
      && +run(rule.sideWidth(rule.plainOf), { off: 0, lead: 0, bn: 3, c: 'main', lc: '#ee7b28' }, 12).toFixed(2) === 2.6
      && +run(rule.sideWidth(rule.plainOf), { off: 1, lead: 1, bn: 3, c: 'main', lc: '#ee7b28' }, 12).toFixed(2) === ownAt12);
    // a line alone keeps its own width (a tram stays thinner, a speed band wider)
    report('a line alone keeps its own width', +run(rule.sideWidth(tramStops), {}, 12).toFixed(2) === 1.56 && +run(rule.sideWidth(rule.fastOf), { c: 'hsr300' }, 12).toFixed(2) === 3.4);
    // nothing is added under a line for standing beside another ("我觉得不一定非要加白边吧"): no casing on rail
    // lines or China's high-speed guest; a metro, tram or suburban line keeps exactly its own casing, a neighbour or not
    report('no casing is added to a line for standing beside another; a cased line keeps exactly its own',
      !/of abroadLayers\) map\.addLayer\(\{ id: id \+ '-casing'/.test(html) && !/'shared-casing'/.test(html) && !('casing' in rule.GUEST)
      && [9, 12].every(z => run(rule.ownCasing(0.6), { off: 0.5 }, z) === run(rule.ownCasing(0.6), {}, z)));
    // on tracks of their own, back onto them by 16.5; on one track (sh), one step apart at every zoom
    const sh = [17, 19].map(z => Math.abs(run(rule.railOff, { off: -0.5, sh: 1 }, z) - run(rule.railOff, { off: 0.5, sh: 1 }, z)));
    report(`rail lines on tracks of their own are back on them by z16.5; on one track (sh) they stay a step apart (${sh.map(d => d.toFixed(1)).join(', ')} px at z17, 19)`,
      run(rule.railOff, { off: 0.5 }, 16.5) === 0 && run(rule.railOff, { off: 0.5 }, 17) === 0 && sh.every(d => Math.abs(d - 8) < 0.01));
    report('the end of a shared track fades continuously onto its neighbouring track at every zoom',
      [15, 16, 17, 19].every(z => {
        const shared = run(rule.railOff, { off: 0.5, sh: 1 }, z), separate = run(rule.railOff, { off: 0.5 }, z);
        return [0.125, 0.5, 0.875].every(sh => Math.abs(run(rule.railOff, { off: 0.5, sh }, z) - (shared * sh + separate * (1 - sh))) < 1e-9);
      }));
    report('cross-category movement fades back onto independent tracks while the within-category pair stays apart',
      run(rule.beside(), { off: 1, goff: 1.5 }, 12) === 5
      && [17, 19].every(z => run(rule.beside(), { off: 1, goff: 1.5 }, z) === -4
        && run(rule.beside(), { off: 2, goff: 1.5 }, z) === 4));
    report('actual-track metro and rail share the same continuous independent-track fade',
      [12, 14.5, 15, 16, 16.5, 19].every(z => [0, .25, 1].every(sh =>
        Math.abs(run(rule.beside(), { off: .5, sh, ap: 1 }, z) - run(rule.railOff, { off: .5, sh }, z)) < 1e-9))
      && run(rule.beside(), { off: .5, ap: 1 }, 19) === 0
      && run(rule.beside(), { off: .5, sh: 1, ap: 1 }, 19) === 4);
    report('actual-track groups retain shared internal spacing and return independent displacement to source',
      [rule.beside(), rule.railOff].every(expr =>
        run(expr, { off: 2, goff: 1.5, sh: 1, ap: 1 }, 19) === 4
        && run(expr, { off: 2, goff: 1.5, ap: 1 }, 19) === 0));
    // present from far out: a bundle is apart at z4 and z6 as the guest is
    report('a bundle is apart from far out, as the guest is (z4, z6)', [4, 6].every(z => Math.abs(Math.abs(run(rule.railOff, { off: -0.5 }, z) - run(rule.railOff, { off: 0.5 }, z)) - run(rule.beside({ guest: true }), {}, z)) < 0.01));
  }
}
process.exit(failed ? 1 : 0);
