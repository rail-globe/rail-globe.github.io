"""Compare drawn services with their own retained native relation members."""
import math
from collections import defaultdict
from shapely.geometry import LineString
from shapely.ops import unary_union

RUNNING = {'rail', 'narrow_gauge', 'preserved', 'subway', 'light_rail', 'monorail', 'tram'}


def audit(features, extract, tolerance_m=35, approved_service_way=None):
    ways = {i: (tags, co) for i, tags, co in extract['ways']}
    relation_context = {i: (tags,members) for i,tags,members in extract['relations']}
    relations = {i: members for i, (_,members) in relation_context.items()}
    groups = defaultdict(list)
    for feature in features:
        p = feature['properties']
        groups[tuple(p.get(k, '') for k in ('g', 'network', 'n', 'rid', 'ct', 'jk'))].append(feature)
    rows = []
    for identity, fs in sorted(groups.items()):
        row = dict(identity=dict(zip(('g','network','n','rid','ct','jk'),identity)))
        ids = [int(r) for r in identity[3].split(',') if r]
        if not ids or any(r not in relations for r in ids):
            rows.append(dict(**row, status='insufficient_relation_source'))
            continue
        members = {w for r in ids for kind,w in relations[r] if kind == 'w'}
        eligible = sorted(w for w in members if w in ways and ways[w][0].get('railway') in RUNNING
                          and (not ways[w][0].get('service') or approved_service_way
                               and any(approved_service_way(identity[0],r,w,ways,relation_context) for r in ids)))
        source = [ways[w][1] for w in eligible]
        display = [co for f in fs for co in ([f['geometry']['coordinates']]
                   if f['geometry']['type'] == 'LineString' else f['geometry']['coordinates'])]
        points = [p for co in source for p in co]
        if not points:
            rows.append(dict(**row,status='insufficient_running_way_source'))
            continue
        lon = sum(p[0] for p in points)/len(points)
        lat = sum(p[1] for p in points)/len(points)
        sx = 111320*math.cos(math.radians(lat))
        def geometry(paths):
            return unary_union([LineString([((x-lon)*sx,(y-lat)*111320) for x,y in co])
                                for co in paths if len(co)>1])
        a,b = geometry(source),geometry(display)
        def measure(first,second):
            outside=first.difference(second.buffer(tolerance_m,resolution=32)).length
            return dict(length_m=round(first.length,3),outside_m=round(outside,3),
                        coverage=round(1-outside/first.length,9) if first.length else 0)
        forward,reverse = measure(a,b),measure(b,a)
        candidate=any(r['outside_m']>10 and r['coverage']<.999 for r in (forward,reverse))
        rows.append(dict(**row,status='review_candidate' if candidate else 'within_retained_source_tolerance',
                         source_way_count=len(eligible),omitted_member_way_ids=sorted(members-ways.keys()),
                         source_to_display=forward,display_to_source=reverse))
    return dict(tolerance_m=tolerance_m,scope='own retained running relation members; omitted member types remain unresolved',
                metric='continuous directional arclength within metric buffer; centre geometry before screen offsets',rows=rows)
