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
  // 3. switching to Japan off the route tab moves to lines (no dead tab), but 路线 still opens empty
  ['auto-switch route->lines on JP', /g === 'jp' && onRoute\) showTab\('lines'\)/],
  // 4. country-specific layer rows hidden for Japan (build / suburb / yards), kept otherwise
  ['JP hides build/suburb/yards rows', /hideForJp/],
  // 5. Japan station popup does not offer 设为出发/到达
  ['JP station popup blocked', /f\.properties\.g === 'jp'\)/],
  // 6. Japan has one colour rule (the line's own colour, else neutral; never the company's):
  // no design-speed layers/toggles, no list of companies
  ['JP rail drawn by line colour', /jpVisible/],
  ['JP colour note says no company colours', /不按公司上色/],
  ['JP shows no company list', /getElementById\('opList'\)\.hidden = jp \|\| !ukOp/],
  ['page does not load company colours for Japan', /^(?![\s\S]*jp_operators)/],
  ['JP layer row: 新干线', /jp-shinkansen/],
  ['JP layer row: JR在来', /jp-jr/],
  ['JP layer row: 大手私铁', /jp-private_big/],
  ['JP layer row: 地方私铁·第三セク', /jp-private_local/],
  ['JP layer row: 其他', /jp-unknown/],
  ['JP layer row: 地下铁', /jp-subway/],
  ['JP layer row: 城市轨道', /jp-urban/],
  ['JP layers hidden when not selected', /el\.hidden = country !== 'jp'/],
  ['China layers hidden when Japan is selected', /cn && visible\[id\]/],
  ['stations filtered to selected country', /map\.setFilter\('stations', \['all', countryFilter/],
  ['generic metro row hidden for Japan', /hideForJp = \{ metro: true/],
  ['JP hides by-operator/by-class segmented', /closest\('\.segmented'\)\.hidden = !WITH_UK \|\| jp;/],
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
  ['operator list items can shrink', /\.oplist li \{ min-width: 0; \}/],
  ['operator buttons can shrink in two columns', /\.oplist button \{ width: 100%; min-width: 0;/],
];

let failed = 0;
for (const [name, re] of checks) {
  const ok = re.test(html);
  if (!ok) { failed++; console.error('FAIL', name); }
  else console.log('ok  ', name);
}
process.exit(failed ? 1 : 0);
