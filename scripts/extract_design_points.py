"""Cache named OSM railway points used as catalogue section boundaries.

Stations come from extract.pkl. This additional pass includes named junctions and
signals (线路所), without replacing them with a similarly named nearby station.
"""
import json
import pickle
import re
import sys
from pathlib import Path

import osmium

ROOT = Path(__file__).resolve().parents[1]


sys.path.insert(0, str(Path(__file__).resolve().parent))
from design_speeds import point_name          # one spelling for station names on the map and in the catalogue


def main():
    catalog = json.loads((ROOT / 'data/rail_design_catalog.json').read_text())
    wanted = {point_name(n) for p in catalog['pages'] for s in p['sections']
              for n in s['endpoints'].split('~')}
    manual = ROOT / 'data/rail_design_overrides.json'
    if manual.exists():
        wanted.update(point_name(n) for s in json.loads(manual.read_text())['sections']
                      for n in s['endpoints'].split('~'))
    points = []
    ex = pickle.load(open(ROOT / 'data/raw/extract.pkl', 'rb'))
    for tags, x, y in ex['stations']:
        for key in ('name:zh', 'name', 'alt_name', 'old_name'):
            if tags.get(key) and point_name(tags[key]) in wanted:
                points.append({'name': point_name(tags[key]), 'coordinates': [x, y], 'kind': 'station'})
    for filename in ('china-latest.osm.pbf', 'taiwan-latest.osm.pbf'):
        path = ROOT / 'data/raw' / filename
        if not path.exists():
            path = ROOT / 'data/raw' / filename.replace('-latest', '')
        fp = osmium.FileProcessor(str(path), entities=osmium.osm.NODE).with_filter(osmium.filter.KeyFilter('railway'))
        count = 0
        for o in fp:
            for key in ('name:zh', 'name', 'alt_name', 'old_name'):
                n = o.tags.get(key)
                if n and point_name(n) in wanted:
                    points.append({'name': point_name(n), 'coordinates': [o.location.lon, o.location.lat],
                                   'kind': o.tags.get('railway'), 'node': o.id})
                    count += 1
        print(filename, count, 'boundary points', flush=True)
    seen, result = set(), []
    for p in points:
        key = (p['name'], *(round(v, 5) for v in p['coordinates']))
        if key not in seen:
            seen.add(key)
            result.append(p)
    out = {'sources': ex.get('sources'), 'points': result}
    (ROOT / 'data/rail_design_points.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print('saved', len(result), 'unique points')


if __name__ == '__main__':
    main()
