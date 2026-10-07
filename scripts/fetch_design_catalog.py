"""Read factual section/speed fields from the user-selected China-EMU catalogue.

No map artwork, prose, photos or station diagrams are copied. The OSM geometry stays separate.
Run explicitly to refresh data/rail_design_catalog.json, not on every offline map build.
"""
import concurrent.futures
import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://www.china-emu.cn"


def page(url):
    for attempt in range(3):
        response = requests.get(url, timeout=25)
        response.raise_for_status()
        response.encoding = "utf-8"
        if "database is locked" not in response.text and "title-label" in response.text:
            return BeautifulSoup(response.text, "html.parser")
        time.sleep(.5 * (attempt + 1))
    raise ValueError("catalogue page has no section data: " + url)


def facts(url):
    s = page(url)
    stations = list(dict.fromkeys(a.get_text(" ", strip=True) for a in s.select('.lines-box a[href*="Station="]')))
    sections = []
    for card in s.select('.border-radius-xs.shadow-xs.position-r'):
        title, span = card.select_one('.title-label'), card.select_one('.text-blue')
        if not title or not span:
            continue
        alias = card.select_one('.font-small')
        # Open/closed notices use different text colours. Read the notice container,
        # not just .text-info, or a red "no service" notice can hide a scope caveat.
        note = ' '.join(p.get_text(' ', strip=True) for p in card.select('.bg-faded'))
        # Some headline numbers apply only to part of the advertised section, or to a
        # future upgrade. Preserve a review flag instead of colouring the entire span.
        sentences = [x.strip() for x in re.split('[。；;\n\r]', note)]
        track_caveats = [x for x in sentences if re.search(r'^线上设计速度[^，,]*(?:暂无|暂缺)', x)]
        review = any(re.search(r'设计.*?(?:速度|时速)|(?:速度|时速).*?设计', x)
                     for x in sentences if x not in track_caveats)
        fields = {}
        technical = {}
        for p in card.select('.para'):
            label, value = p.select_one('.para-M'), p.select_one('.para-N')
            if label and value and label.get_text(strip=True) in ('线下设计速度', '线上设计速度', '最高运行速度'):
                text = value.get_text(' ', strip=True)
                nums = re.findall(r'\d+(?:\.\d+)?', text)
                # Multiple values/ranges need manual interpretation, never pick their maximum silently.
                fields[label.get_text(strip=True)] = float(nums[0]) if len(nums) == 1 else None
            elif label and value and label.get_text(strip=True) in ('线路数', '供电制式', '轨距', '列控系统'):
                technical[label.get_text(strip=True)] = value.get_text(' ', strip=True)
        events = []
        kinds = {'开通': 'opened', '开工': 'construction_started', '联调联试': 'testing', '试运营': 'trial_service', '竣工': 'completed'}
        for m in re.finditer(r'(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?\s*(开通|开工|联调联试|试运营|竣工)', note):
            try:
                day = date(*map(int, m.groups()[:3])).isoformat()
            except ValueError:
                continue
            context = note[max(0, m.start() - 16):m.end()]
            events.append({'date': day, 'event': kinds[m[4]],
                           'planned': bool(re.search('预计|计划|拟|目标|力争', context))})
        # A caveat solely about track design does not invalidate the separately
        # documented infrastructure design, but that unverified track number is omitted.
        if track_caveats:
            fields['线上设计速度'] = None
        sections.append({'name': title.get_text(' ', strip=True), 'track_name': alias.get_text(' ', strip=True) if alias else '',
                         'endpoints': span.get_text(' ', strip=True), 'design': fields.get('线下设计速度') or fields.get('线上设计速度'),
                         'design_infrastructure': fields.get('线下设计速度'), 'design_track': fields.get('线上设计速度'),
                         'operating': fields.get('最高运行速度'), 'requires_review': review,
                         'events': events, 'technical': technical, 'url': url})
    return {'page': parse_qs(urlparse(url).query).get('LineName', [''])[0], 'url': url, 'stations': stations, 'sections': sections}


def main():
    urls = set()
    # Every index of the directory: trunk lines, regional lines, intercity and suburban lines, and
    # the connecting lines and lines inside hubs (联络线及枢纽内线路), more pages than the other three together.
    indexes = ['/RailRoads/Mainlines/', '/RailRoads/Area/', '/RailRoads/Intercity/', '/RailRoads/Hub/']
    for path in indexes:
        response = requests.get(BASE + path, timeout=25)
        response.raise_for_status()
        response.encoding = 'utf-8'
        s = BeautifulSoup(response.text, 'html.parser')
        links = s.select('a[href*="/RailRoads/Line/?LineName="]')
        if not links:
            raise ValueError('empty catalogue index, previous snapshot retained: ' + path)
        urls.update(urljoin(BASE, a['href']) for a in links)
    rows, failures = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        future_urls = {pool.submit(facts, url): url for url in sorted(urls)}
        for future in concurrent.futures.as_completed(future_urls):
            url = future_urls[future]
            try:
                rows.append(future.result())
            except Exception as err:
                failures.append({'url': url, 'error': str(err)})
            if (len(rows) + len(failures)) % 25 == 0:
                print('pages read:', len(rows), 'failed:', len(failures), flush=True)
    rows.sort(key=lambda row: row['page'])
    if failures:
        report = ROOT / 'output/design/catalog-failures.json'
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(failures, ensure_ascii=False, indent=2) + '\n')
        raise SystemExit('incomplete refresh: previous catalogue retained; see ' + str(report))
    out = {'retrieved': datetime.now(timezone.utc).isoformat(), 'source': BASE + '/RailRoads/',
           'basis': 'infrastructure design speed; track design and operating speeds kept separately',
           'pages': rows, 'failures': failures}
    p = ROOT / 'data/rail_design_catalog.json'
    p.with_suffix('.json.tmp').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    p.with_suffix('.json.tmp').replace(p)
    print('saved', len(rows), 'pages,', sum(len(r['sections']) for r in rows), 'sections; failures:', len(failures), flush=True)


if __name__ == '__main__':
    main()
