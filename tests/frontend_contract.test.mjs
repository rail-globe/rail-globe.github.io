// Deterministic contract regression for the country-switch frontend (reads the built index.html).
// Not a runtime DOM test (no jsdom/maplibre here); it asserts the wiring each required behavior
// depends on, so a future edit that drops a hook fails the build check.
import { readFileSync } from 'node:fs';
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
  ['layers abroad hidden unless their country is chosen', /const on = id\.startsWith\(country \+ '-'\) && abroadVisible\[id\];/],
  ['China layers hidden when another country is chosen', /cn && visible\[id\]/],
  ['stations filtered to selected country', /map\.setFilter\('stations', \['all', countryFilter/],
  ['lines being built filtered to selected country', /map\.setFilter\('build', countryFilter\)/],
  ['yards and depots of every country are loaded', /\['', \.\.\.Object\.keys\(FOREIGN\)\.map\(g => g \+ '_'\)\]\.map\(pre => getJSON\(`data\/\$\{pre\}\$\{kind\}\.geojson`\)/],
  ['yards and depots filtered to selected country', /set\(id, visible\.yards\);\s+map\.setFilter\(id, cn \? NOT_ABROAD : \['==', \['get', 'g'\], country\]\);/],
  ['the yards row stays abroad', /^(?![\s\S]*yards: true)/],
  ['setCountry updates the colour section', /colourSection\(g\);/],
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
for (const [name, re] of checks) {
  const ok = re.test(html);
  if (!ok) { failed++; console.error('FAIL', name); }
  else console.log('ok  ', name);
}
process.exit(failed ? 1 : 0);
