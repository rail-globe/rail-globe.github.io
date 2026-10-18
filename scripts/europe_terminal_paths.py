"""Strict, opt-in original terminal paths for individually source-audited services.

Both APIs are pure. Profiles live in normal data, never in reports. Only pipeline
added `_hsr_` tags are omitted from fingerprints. Original route-policy tags,
member order, complete available parent ancestry, absent members and original
way coordinates remain bound. Changed or partial input returns the caller's
exact default object / False. Paths retain each native direction independently,
without one_track or stitch, before the existing source-bound city graph.
"""
import hashlib
import json
from pathlib import Path
from shapely.geometry import LineString
from shapely.ops import unary_union
from process_jp import runs_of

DATA = Path(__file__).resolve().parents[1] / 'data/europe_terminal_sources.json'

def _load():
    try:
        data = json.loads(DATA.read_text())
        if data.get('schema') != 1:
            return {}
        return {(p['country'], p['network'], p['name'], tuple(p['rids'])): p
                for p in data['profiles'] if p.get('enabled') is True}
    except (OSError, ValueError, KeyError, TypeError):
        return {}

PROFILES = _load()

def _tags(tags):
    return {k: v for k, v in tags.items() if not k.startswith('_hsr_')}

def source_fingerprint(rids, ways, relations, extra_relations=()):
    """Complete reviewed route/ancestor/member-way inputs, with exact source tags."""
    ids = tuple(sorted(rids))
    if not ids or len(ids) != len(set(ids)) or any(r not in relations for r in ids):
        return None
    ancestors, frontier = set(), set(ids)
    while frontier:
        found = {rid for rid, (tags, members) in relations.items()
                 if rid not in ancestors and rid not in ids
                 and any(kind == 'r' and ref in frontier for kind, ref in members)}
        ancestors.update(found)
        frontier = found
    records = []
    for rid in sorted(set(ids) | ancestors | set(extra_relations)):
        value = relations.get(rid)
        records.append([rid, None if value is None else [_tags(value[0]), value[1]]])
    wids = sorted({ref for rid in ids for kind, ref in relations[rid][1] if kind == 'w'})
    way_records = []
    for wid in wids:
        value = ways.get(wid)
        way_records.append([wid, None if value is None else [_tags(value[0]), value[1]]])
    payload = {'routes': ids, 'ancestors': sorted(ancestors),
               'relations': records, 'ways': way_records}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()

def _matches(profile, ways, relations):
    try:
        required = profile['required_way_ids']
        if not required or any(w not in ways or len(ways[w][1]) < 2 for w in required):
            return False
        if (profile['country'] == 'es'
                and tuple(profile['rids']) == (6679948, 6679966)
                and not all(_service_proof(profile, rid, 454555501)
                            for rid in profile['rids'])):
            return False
        return source_fingerprint(profile['rids'], ways, relations,
                                  profile.get('extra_relations', ())) == profile['fingerprint']
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return False

def _service_proof(profile, rid, wid):
    """Sidecar native roles/node IDs restore evidence omitted by old tuple extracts."""
    proof = profile.get('service_way_proofs', {}).get(str(wid))
    if not proof or rid not in proof.get('rids', ()):
        return False
    try:
        stop = proof['stop_node']
        area = proof['stop_area']
        return (wid == 454555501 and profile['country'] == 'es'
                and tuple(profile['rids']) == (6679948, 6679966)
                and proof['native_way']['id'] == wid
                and proof['native_way']['tags'].get('service') == 'siding'
                and stop in proof['native_way']['nodes']
                and area['id'] == 10711667
                and any(k == 'n' and ref == stop and role == 'stop'
                        for k, ref, role in area['members'])
                and all(any(k == 'n' and ref == stop and role == 'stop'
                            for k, ref, role in profile['native_relations'][str(r)]['members'])
                        and any(k == 'w' and ref == wid for k, ref, role in profile['native_relations'][str(r)]['members'])
                        for r in proof['rids'])
                and bool(profile['provenance']['extract_sha256'])
                and bool(profile['provenance']['pbf_sha256']))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False

def approved_service_way(code, rid, wid, ways, relations):
    """Allow only the proven Vitoria passenger stopping leg, never generic sidings."""
    if type(rid) is not int or type(wid) is not int:
        return False
    for (country, network, name, ids), profile in PROFILES.items():
        if country != code or rid not in ids or not _service_proof(profile, rid, wid):
            continue
        if rid not in relations or not any(kind == 'w' and ref == wid for kind, ref in relations[rid][1]):
            return False
        return _matches(profile, ways, relations)
    return False

def terminal_paths(code, network, name, rids, ways, relations, drawn):
    """Return full original running runs per rid for an exact reviewed identity.

    Call after default `drawn`, before rounding. The city must use existing
    source_bound bundling. Construction gaps remain separate native runs.
    This function changes no Point, relation identity, name, colour or seat.
    """
    try:
        values = []
        for r in rids:
            if type(r) is int:
                values.append(r)
            elif isinstance(r, str) and r.isdecimal() and str(int(r)) == r:
                values.append(int(r))
            else:
                return drawn
        identity = tuple(sorted(values))
    except (TypeError, ValueError):
        return drawn
    if not identity or len(identity) != len(set(identity)):
        return drawn
    profile = PROFILES.get((code, network, name, identity))
    if profile is None or not _matches(profile, ways, relations):
        return drawn
    candidates = []
    try:
        for rid in identity:
            coordinates = []
            for kind, wid in relations[rid][1]:
                if kind != 'w' or wid not in ways:
                    continue
                tags, co = ways[wid]
                if tags.get('railway') not in profile['railway']:
                    continue
                if tags.get('service') and not (_service_proof(profile, rid, wid)
                                                and any(k == 'w' and ref == wid for k, ref in relations[rid][1])):
                    continue
                if len(co) < 2:
                    return drawn
                coordinates.append(co)
            if not coordinates:
                return drawn
            paths = runs_of(coordinates)
            if not paths or any(g.is_empty or not g.is_valid for g in paths):
                return drawn
            # Exact native union check: no hidden chords, cuts or gap bridges.
            native = unary_union([LineString(co) for co in coordinates])
            output = unary_union(paths)
            if not native.equals(output):
                return drawn
            candidates.extend(paths)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return drawn
    return candidates
