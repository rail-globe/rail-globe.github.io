"""Source-bound European urban-layer policy. Railway coverage is never removed here.

The thresholds were approved after a full seven-country source audit. They read
unique member ways, not route label votes, names, tunnels, or route_master modes.
"""
import hashlib
import json
import math
import pickle
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URBAN_TRACK = frozenset({'tram', 'light_rail', 'subway', 'monorail', 'maglev'})
POLICY_TAGS = ('usage', 'service', 'tourism', 'heritage', 'railway:preserved',
               'description', 'opening_hours', 'website', 'wikipedia', 'disused', 'end_date')
# Identity-scoped exceptions approved in classify.json. Names are not predicates.
SPECIAL_EXCLUSIONS = {
    'de': {1108885: 'heritage-service', 1108886: 'heritage-service',
           14570422: 'historical-event', 14570423: 'historical-event',
           13649966: 'museum-opening-service', 13649967: 'museum-opening-service',
           397326: 'event-service', 947732: 'event-service', 5421483: 'event-service',
           10547653: 'event-service', 10547654: 'event-service'},
    'nl': {20460935: 'heritage-service'},
    'it': {1523425: 'heritage-service'},
}
M1 = frozenset({1664324, 7781525})
S6 = frozenset({192247, 192248})


def sha256(file_path):
    digest = hashlib.sha256()
    with Path(file_path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def nearest_city(cities, point, elsewhere):
    """Nearest eligible city, with a stable identity tie break, independent of list order."""
    choices = []
    for name, lon, lat, reach in cities:
        distance = math.hypot((lon - point.x) * math.cos(math.radians(point.y)), lat - point.y)
        if distance < reach:
            choices.append((distance, name))
    return min(choices)[1] if choices else elsewhere


def tourist(tags):
    if tags.get('usage') == 'tourism' or tags.get('service') in {'tourism', 'tourist'}:
        return True
    if tags.get('railway:preserved') == 'yes':
        return True
    return any(tags.get(key, '').lower() not in {'', 'no', 'false', '0'}
               for key in ('tourism', 'heritage'))


RET12_ROUTES = frozenset({3009640, 4016992, 5976236, 5976237})
RET12_MASTER = 3009639
# Actual normal preflight + bound relation-policy input, not a name/ref heuristic.
# Official and full native-role receipts: reports/classification/ret12/README.md.
RET12_CONTEXT_SHA256 = 'b884e4114040c17b869d6c89676ae94365b3d7f1100480249cf9148edcc6ed89'


def ret12_context_digest(ways, relations):
    """Bind every current parent, full route member and available source way.

    Only pipeline-added HSR annotations are omitted. Original source labels,
    members, coordinates and missing-way state remain part of the digest.
    """
    selected = {i: relations[i] for i in RET12_ROUTES if i in relations}
    selected.update({i: (t, m) for i, (t, m) in relations.items()
                     if any(k == 'r' and n in RET12_ROUTES for k, n in m)})
    wanted = {n for _, members in selected.values() for k, n in members if k == 'w'}
    scope = {'relations': selected,
             'ways': {i: ({k: v for k, v in ways[i][0].items() if not k.startswith('_hsr_')},
                          ways[i][1]) for i in wanted if i in ways},
             'missing_ways': sorted(wanted - set(ways))}
    return hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def ret12_exclusion(code, rid, tags, master, ways, relations):
    if code != 'nl' or rid not in RET12_ROUTES or ways is None or relations is None:
        return None
    if rid not in relations or RET12_MASTER not in relations:
        return None
    actual, _ = relations[rid]
    parent, members = relations[RET12_MASTER]
    if tags != actual or master != parent:
        return None
    if (tags.get('network'), tags.get('operator'), tags.get('route')) != ('Rail Rotterdam', 'RET', 'tram'):
        return None
    if (master.get('network'), master.get('name'), master.get('route_master')) != ('Rail Rotterdam', 'Tram 12', 'tram'):
        return None
    try:
        verified = ret12_context_digest(ways, relations) == RET12_CONTEXT_SHA256
    except (KeyError, TypeError, ValueError):
        verified = False
    if not verified:
        return None
    return 'verified-feyenoord-event-service'


def route_exclusion(code, rid, tags, master, *, ways=None, relations=None):
    """Return an identity-scoped exclusion reason; Country chooses its layout stage."""
    event = ret12_exclusion(code, rid, tags, master, ways, relations)
    if event:
        return event
    if rid in SPECIAL_EXCLUSIONS.get(code, {}):
        return SPECIAL_EXCLUSIONS[code][rid]
    if tourist(tags) or tourist(master):
        return 'relation-tourism-heritage'
    return None


def policy(code, wids, ways, lengths, relation_ids, relations, current):
    """Return {keep, jk, reasons, railway_km}; called before drawing or bundle allocation."""
    track = Counter()
    for wid in set(wids):
        track[ways[wid][0].get('railway', '')] += lengths[wid]
    total = sum(track.values())
    urban = sum(track[k] for k in URBAN_TRACK)
    reasons = []
    keep, kind = True, current
    # An explicit, verified mixed tram-train identity protects the threshold boundary.
    protected = code == 'de' and bool(S6 & set(relation_ids))
    if current == 'urban' and urban < 0.5 and not protected:
        keep = False
        reasons.append('urban-track-below-0.5km')
    if wids and all(tourist(ways[w][0]) or ways[w][0].get('railway') == 'preserved' for w in set(wids)):
        keep = False
        reasons.append('all-member-track-tourism-heritage')
    if current == 'subway' and total and track['subway'] / total < 0.1:
        kind = 'urban'
        reasons.append('subway-track-below-10percent')
    if code == 'es' and M1 & set(relation_ids):
        kind = 'subway'
        reasons.append('sfm-official-m1-metro')
    return {'keep': keep, 'jk': kind, 'reasons': reasons,
            'railway_km': dict(sorted(track.items())), 'urban_track_km': urban,
            'protected_tram_train': protected}


def load_relations(code, extract_path, relations, schema=()):
    """Old extracts lack policy tags. Require a source-bound supplementary scan.

    Missing supplementary tags are unknown, never interpreted as absence of tourism.
    New extracts declare their retained tag schema and do not need a supplement.
    """
    extract_path = Path(extract_path)
    if set(POLICY_TAGS) <= set(schema):
        return relations
    supplement = ROOT / 'data' / 'europe_relation_tags' / f'{code}.json'
    if not supplement.exists():
        raise ValueError(f'{code}: old extract needs a bound relation-policy tag supplement')
    data = json.loads(supplement.read_text())
    if data['extract_sha256'] != sha256(extract_path):
        raise ValueError(f'{code}: relation-policy supplement belongs to another extract')
    missing = set(map(str, relations)) - set(data['relations'])
    if missing:
        raise ValueError(f'{code}: relation-policy source scan is incomplete ({len(missing)} relations)')
    return {rid: ({**tags, **data['relations'][str(rid)]}, members)
            for rid, (tags, members) in relations.items()}


def build_supplement(code):
    """Read native PBF relations only, leaving the original extract and PBF untouched."""
    import osmium
    raw = ROOT / 'data' / 'raw'
    extract_path = raw / f'extract_{code}.pkl'
    with extract_path.open('rb') as stream:
        ex = pickle.load(stream)
    wanted = {rid for rid, _, _ in ex['relations']}
    found, sources = {}, []
    for source in ex['sources']:
        pbf = raw / source['file']
        actual = sha256(pbf)
        if source.get('sha256') and source['sha256'] != actual:
            raise ValueError(f'{code}: PBF differs from extract provenance: {pbf.name}')
        sources.append({'file': pbf.name, 'sha256': actual, 'bytes': pbf.stat().st_size})
        for obj in osmium.FileProcessor(str(pbf), osmium.osm.RELATION):
            if obj.id in wanted:
                found[str(obj.id)] = {key: obj.tags[key] for key in POLICY_TAGS if key in obj.tags}
    if wanted - set(map(int, found)):
        raise ValueError(f'{code}: source scan did not find every extracted relation')
    out = ROOT / 'data' / 'europe_relation_tags' / f'{code}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'schema': 1, 'extract_sha256': sha256(extract_path),
                               'policy_tags': POLICY_TAGS, 'sources': sources,
                               'relations': found}, ensure_ascii=False, sort_keys=True) + '\n')
    return out


if __name__ == '__main__':
    import sys
    for country in sys.argv[1:]:
        print(build_supplement(country), flush=True)
