"""Read-only station provenance and conservative duplicate display plans.

Names and distances find pairs to inspect, never establish a duplicate. A plan
can collapse repeated instances of one native object, or a non-platform station
outline plus its station node within an explicit common stop_area. Every kept
Point is an existing authoritative Point. Opposite platforms are never merged.
"""
import copy
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

from shapely.geometry import Point, Polygon


def metres(a, b):
    return math.hypot((a[0]-b[0])*math.cos(math.radians((a[1]+b[1])/2)), a[1]-b[1])*111320


def name(tags):
    return re.sub(r'\s+', ' ', tags.get('name') or '').strip()


def same_name_pairs(features, minimum=10, maximum=120, urban_only=False):
    groups=defaultdict(list)
    for index,f in enumerate(features):
        if not urban_only or f['properties'].get('m'):
            groups[f['properties']['n']].append(index)
    pairs=[]
    for label,indices in groups.items():
        for offset,a in enumerate(indices):
            for b in indices[offset+1:]:
                distance=metres(features[a]['geometry']['coordinates'],features[b]['geometry']['coordinates'])
                if minimum<=distance<=maximum:
                    pairs.append({'name':label,'a':a,'b':b,'distance_m':round(distance,3)})
    return pairs


def match_extract(feature, rows):
    """Recover original extraction rows by the generator's exact rounded Point."""
    at=feature['geometry']['coordinates'];label=feature['properties']['n']
    return [index for index,(tags,x,y) in enumerate(rows)
            if name(tags)==label and [round(x,5),round(y,5)]==at]


def is_platform(obj):
    tags=obj.get('tags',{})
    return (tags.get('public_transport') in {'platform','stop_position'}
            or tags.get('railway') in {'platform','tram_stop','stop'}
            or tags.get('highway')=='bus_stop')


def classify(a, b, areas):
    """Classify two recovered native objects. Evidence IDs, never names, decide."""
    if not a or not b:
        return {'class':'insufficient_evidence','safe_merge':False,'reason':'native_object_not_uniquely_recovered'}
    aid=(a['type'],a['id']);bid=(b['type'],b['id'])
    common=[area['id'] for area in areas if aid in {tuple(member[:2]) for member in area['members']}
            and bid in {tuple(member[:2]) for member in area['members']}]
    if aid==bid:
        return {'class':'duplicate_object','safe_merge':True,'reason':'same_native_object','common_stop_areas':common}
    platform_roles={tuple(member[:2]) for area in areas for member in area['members'] if str(member[2]).startswith('platform')}
    a_platform=is_platform(a) or aid in platform_roles
    b_platform=is_platform(b) or bid in platform_roles
    if a_platform or b_platform:
        opposite=[]
        for left in a.get('route_memberships',()):
            for right in b.get('route_memberships',()):
                x,y=left['tags'],right['tags']
                if (x.get('from') and x.get('to') and x.get('from')!=x.get('to')
                        and x.get('from')==y.get('to') and x.get('to')==y.get('from')
                        and x.get('ref') and x.get('ref')==y.get('ref')
                        and x.get('network')==y.get('network') and x.get('route')==y.get('route')):
                    opposite.append([left['rid'],right['rid']])
        return {'class':'bidirectional_platforms' if opposite else 'distinct_platforms' if a_platform and b_platform else 'station_and_platform','safe_merge':False,
                'reason':'opposite_native_route_endpoints' if opposite else 'different_native_stopping_objects_preserved',
                'common_stop_areas':common,'opposite_route_pairs':opposite}
    def mode(obj):
        tags=obj.get('tags',{})
        return tags.get('station') or ('subway' if tags.get('subway')=='yes' else
               'light_rail' if tags.get('light_rail')=='yes' else 'rail' if tags.get('uic_ref') else None)
    ma,mb=mode(a),mode(b)
    if ma and mb and ma!=mb:
        wa,wb=a['tags'].get('wikidata'),b['tags'].get('wikidata')
        return {'class':'different_stations' if wa and wb and wa!=wb else
                'same_complex_distinct_modes' if wa and wa==wb else 'different_station_modes',
                'safe_merge':False,'reason':'explicit_native_station_modes_differ',
                'common_stop_areas':common,'station_modes':[ma,mb],
                'station_wikidata':[wa,wb]}
    if common:
        node,outline=(a,b) if a['type']=='n' else (b,a)
        if node['type']=='n' and outline['type']=='w' and node.get('at') and outline.get('coords'):
            co=outline['coords']
            if len(co)>=4 and co[0]==co[-1] and Polygon(co).is_valid and Polygon(co).covers(Point(node['at'])):
                return {'class':'duplicate_representation','safe_merge':True,
                        'reason':'station_node_inside_station_outline_in_same_explicit_stop_area',
                        'common_stop_areas':common,'prefer':list((node['type'],node['id']))}
        return {'class':'same_station_distinct_objects','safe_merge':False,
                'reason':'shared_stop_area_does_not_prove_redundant_points','common_stop_areas':common}
    return {'class':'insufficient_evidence','safe_merge':False,
            'reason':'different_native_objects_without_common_stop_area','common_stop_areas':[]}


def display_plan(features, origins, areas):
    """A reviewable suppress-only plan. Ambiguous and platform objects stay intact.

    origins maps feature index to one uniquely recovered native object. Returned
    suppressed indices are recommendations, not a data mutation. Callers must
    bind their evidence to input hashes before applying a plan in production.
    """
    suppressed={};evidence=[]
    for pair in same_name_pairs(features,minimum=0):
        a,b=pair['a'],pair['b'];decision=classify(origins.get(a),origins.get(b),areas)
        if (not decision['safe_merge'] or a in suppressed or b in suppressed
                or bool(features[a]['properties'].get('m')) != bool(features[b]['properties'].get('m'))):
            continue
        preferred=decision.get('prefer')
        keep=a if not preferred or list((origins[a]['type'],origins[a]['id']))==preferred else b
        drop=b if keep==a else a
        suppressed[drop]=keep
        evidence.append({**pair,**decision,'keep':keep,'suppress':drop})
    return {'suppressed':suppressed,'evidence':evidence}


def apply_display_plan(features, plan):
    """Return copies of existing Points only. No averaging, snapping or renaming."""
    return [copy.deepcopy(f) for index,f in enumerate(features) if index not in plan['suppressed']]


def filter_station_sources(code, extract, extract_path, *, ledger_path=None, audit=None):
    """Filter only hash-bound, source-proven duplicate station outlines.

    The build input is data/europe_station_sources/<code>.json, not a report.
    Unknown hashes, changed origins, absent retained nodes and incomplete
    manifests fail closed by retaining every station. Future native-ID tuples
    still need a revalidated manifest for their exact extract SHA.
    """
    rows=extract['stations']
    path=Path(ledger_path) if ledger_path is not None else Path(__file__).resolve().parents[1]/'data'/'europe_station_sources'/f'{code}.json'
    def note(reason, **more):
        if audit is not None:audit.append({'country':code,'reason':reason,**more})
    if not path.exists():
        note('no_source_ledger',suppressed=0)
        return rows
    try:
        manifest=json.loads(path.read_text())
    except (ValueError, OSError):
        note('unreadable_source_ledger',suppressed=0)
        return rows
    if (not isinstance(manifest,dict) or manifest.get('v')!=1 or manifest.get('country')!=code
            or not isinstance(manifest.get('extract_sha256'),str)
            or not isinstance(manifest.get('pbf_source'),dict)
            or not all(key in manifest['pbf_source'] for key in ('file','sha256'))
            or not isinstance(manifest.get('duplicates'),list)):
        note('unsupported_source_ledger',suppressed=0)
        return rows
    digest=hashlib.sha256()
    with Path(extract_path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):digest.update(chunk)
    if digest.hexdigest()!=manifest['extract_sha256']:
        note('extract_hash_mismatch',suppressed=0)
        return rows
    source=manifest['pbf_source']
    if not any(row.get('file')==source['file'] and row.get('sha256')==source['sha256'] for row in extract.get('sources',())):
        note('pbf_vintage_mismatch',suppressed=0)
        return rows
    suppressed=set()
    for duplicate in manifest['duplicates']:
        if not isinstance(duplicate,dict):
            note('incomplete_native_proof')
            continue
        area=duplicate.get('stop_area')
        native_keep=duplicate.get('keep',{}).get('native')
        native_drop=duplicate.get('suppress',{}).get('native')
        if not area or not native_keep or not native_drop:
            note('incomplete_native_proof',name=duplicate.get('name'))
            continue
        try:
            proof=classify(native_keep,native_drop,[area])
            complete=all(all(key in duplicate[kind] for key in ('type','id','extract_index','station_tuple'))
                         for kind in ('keep','suppress'))
        except (KeyError,TypeError,ValueError):
            note('incomplete_native_proof',name=duplicate.get('name'))
            continue
        if not complete:
            note('incomplete_native_proof',name=duplicate.get('name'))
            continue
        if (not proof['safe_merge'] or proof['class']!='duplicate_representation'
                or any((duplicate[kind]['type'],duplicate[kind]['id']) !=
                       (duplicate[kind]['native']['type'],duplicate[kind]['native']['id'])
                       for kind in ('keep','suppress'))):
            note('invalid_native_proof',name=duplicate.get('name'))
            continue
        matches={}
        for kind in ('keep','suppress'):
            source=duplicate[kind];index=source['extract_index']
            if not 0<=index<len(rows):continue
            tags,x,y=rows[index]
            expected=source['station_tuple']
            stripped={key:value for key,value in tags.items() if not key.startswith('_osm_')}
            if stripped!=expected[0] or [x,y]!=expected[1:]:continue
            # Explicit IDs always override the old index/tuple correspondence.
            # A changed ID cannot silently fall back to its nearby old name.
            if '_osm_id' in tags or '_osm_type' in tags:
                if tags.get('_osm_id')!=source['id'] or tags.get('_osm_type')!=source['type']:continue
            matches[kind]=index
        if set(matches)!= {'keep','suppress'}:
            note('unknown_or_changed_native_object',name=duplicate['name'])
            continue
        if duplicate['keep']['type']!='n' or duplicate['suppress']['type']!='w':
            note('unsupported_duplicate_kind',name=duplicate['name'])
            continue
        suppressed.add(matches['suppress'])
        note('proven_node_outline_duplicate',name=duplicate['name'],keep=list(rows[matches['keep']][1:]),
             suppressed_native=['w',duplicate['suppress']['id']],stop_area=area['id'])
    note('source_filter_complete',suppressed=len(suppressed),retained=len(rows)-len(suppressed))
    return [row for index,row in enumerate(rows) if index not in suppressed]
