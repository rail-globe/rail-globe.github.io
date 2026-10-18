"""Source-scoped European HSR identity, independent of speed and adopted names.

``install(cfg)`` composes with Country's existing callbacks. Its preflight annotates
only the in-memory extract loaded by country.run. Original pickles, names and
coordinates are never changed. Explicit exclusions become conventional railway.
Unresolved identities retain the old rendering class with hsr_state=unresolved:
this migration policy is deliberately incomplete, not a verified HSR inventory.
No line-level official speed is copied onto every way or an adopted neighbour.
"""
import argparse
import hashlib
import json
import pickle
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'data/europe_hsr_sources.json'
TAG_KEYS = ('_hsr_state', '_hsr_ids', '_hsr_refs', '_hsr_match')


def normal_name(value):
    """Typography only: no partial, structure-name or foreign-name matching."""
    value = unicodedata.normalize('NFC', value or '').casefold()
    value = re.sub(r'\s*[–—−-]\s*', '-', value)
    return re.sub(r'\s+', ' ', value).strip()


def shown_name(value):
    """A name as the map shows it: without a note in round brackets ("(LGV)"), the first of several
    separated by semicolons. Square brackets mark a dataset's annotation, never part of a name, and
    such a name is not re-read ("HSL 4 [nl_lines.json]" stays unmatched)."""
    if "[" in (value or ""):
        return value
    value = re.sub(r"\s*[(（].*?[)）]", "", value or "")
    return re.sub(r"\s+", " ", re.split(r"\s*;\s*", value)[0]).strip()


class Registry:
    def __init__(self, data=None):
        self.data = data if data is not None else json.loads(CATALOG.read_text())
        self.by_name = defaultdict(list)
        for row in self.data['records'] + self.data['exclusions']:
            if row['identity'] == 'unresolved':
                if row.get('exact_names'):
                    raise ValueError('Unverified research must not have active name bindings')
                continue
            if not row.get('verified_sources'):
                raise ValueError('Active identity has no verified source')
            for source in row['verified_sources']:
                # whether a line is new-build may rest on a reference work (an encyclopaedia citing the
                # builder); a design speed still needs official evidence (design_binding, below)
                if self.data['sources'][source].get('publisher_kind') not in ('official', 'reference'):
                    raise ValueError('Active identity needs official or reference evidence')
            if row.get('design_binding') is not None:
                raise ValueError('Official design bindings need an explicit native-way adapter')
            for name in row.get('exact_names', ()):
                if '[' in name or ']' in name:
                    raise ValueError('Dataset annotations are not infrastructure names')
                self.by_name[row['country'], normal_name(name)].append((row, None))
            # a name one part of which is this line and another part another (Schnellfahrstrecke
            # Nürnberg-Erfurt: new north of Ebensfeld, the four-tracked old line south of it): the
            # name binds only where a way's midpoint lies within the given box [west, south, east, north]
            for scoped in row.get('scoped_names', ()):
                self.by_name[row['country'], normal_name(scoped['name'])].append((row, tuple(scoped['box'])))

    def match(self, code, names, co=None):
        found = {}
        mid = co[len(co) // 2] if co else None
        # a raw name no record knows is tried as the map shows it, without its bracketed note and
        # after the first of several (SNCF's "Ligne de Paris-Montparnasse à Monts (LGV)" is listed by
        # its shown name, as research found it); a raw name some record knows is never re-read
        names = [n for name in names for n in ([name] if (code, normal_name(name)) in self.by_name
                                                 else [name, shown_name(name)])]
        for name in names:
            for row, box in self.by_name.get((code, normal_name(name)), ()):
                if box is not None and not (mid and box[0] <= mid[0] <= box[2] and box[1] <= mid[1] <= box[3]):
                    continue
                found[row['id']] = row
        if len(found) != 1:
            return None                     # conflicting aliases are unresolved
        return next(iter(found.values()))

    def annotate(self, extract, code):
        """Original ways or a unique route=railway name bind identity, never services.

        Explicit raw names remain authoritative. No match through an adopted name,
        nearest geometry, bridge title, train service, or neighbouring-country alias.
        Construction remains construction even if a current line name is shared.
        """
        infrastructure = defaultdict(set)
        for _, tags, members in extract.get('relations', ()):
            if tags.get('type') == 'route' and tags.get('route') == 'railway' and tags.get('name'):
                for kind, wid in members:
                    if kind == 'w':
                        infrastructure[wid].add(tags['name'])
        counts = Counter()
        for wid, tags, co in extract['ways']:
            for key in TAG_KEYS:
                tags.pop(key, None)          # repeated preflight is deterministic
            if tags.get('railway') not in ('rail', 'narrow_gauge', 'preserved', 'construction'):
                continue
            raw_name = tags.get('name')
            names = [raw_name] if raw_name else list(infrastructure[wid])
            match = self.match(code, names, co) if raw_name or len(names) == 1 else None
            if tags.get('railway') == 'construction':
                state, match = 'construction_unresolved', None
            else:
                state = match['identity'] if match else 'unresolved'
            tags['_hsr_state'] = state
            tags['_hsr_match'] = 'raw_way_name' if match and raw_name else 'infrastructure_relation' if match else 'none'
            if match:
                tags['_hsr_ids'] = match['id']
                tags['_hsr_refs'] = ' '.join(sorted({self.data['sources'][sid]['url'] for sid in match['verified_sources']}))
            counts[state] += 1
        counts.update(self.between_new_build(extract))
        return dict(sorted(counts.items()))

    def between_new_build(self, extract, longest_km=30.0):
        """Unnamed and structure-named running track inside a new-build line takes its identity.

        A new line's bridges and tunnels carry their own names (Talbrücke Leinach), and some of
        its track none, so they match no catalogue name; with unresolved track drawn as
        conventional (only listed new-build lines are high-speed: "不算", 2026-10-17) the line
        would come apart at each of them. A connected run of such ways, with no service tag, of at
        most longest_km, whose ends touch ways of one and the same new-build identity at two places
        or more, is that line. One that touches it once (a connecting curve, a spur) stays unresolved.
        """
        ways = {wid: (tags, co) for wid, tags, co in extract['ways']}
        key = lambda c: (round(c[0], 7), round(c[1], 7))
        def free(tags):
            name = tags.get('name') or ''
            return (tags.get('railway') == 'rail' and not tags.get('service') and tags.get('_hsr_state') == 'unresolved'
                    and (not name or STRUCTURE.search(name)))
        at = defaultdict(set)
        for wid, (tags, co) in ways.items():
            if tags.get('railway') == 'rail' and len(co) > 1:
                at[key(co[0])].add(wid); at[key(co[-1])].add(wid)
        parent = {w: w for w, (tags, _) in ways.items() if free(tags)}
        def root(w):
            while parent[w] != w:
                parent[w] = parent[parent[w]]; w = parent[w]
            return w
        for wids in at.values():
            mine = [w for w in wids if w in parent]
            for a, b in zip(mine, mine[1:]):
                parent[root(a)] = root(b)
        runs = defaultdict(list)
        for w in parent:
            runs[root(w)].append(w)
        counts = Counter()
        for run in runs.values():
            km = sum(_length_km(ways[w][1]) for w in run)
            touch = defaultdict(set)                 # identity -> the places it touches the run
            for w in run:
                co = ways[w][1]
                for end in (key(co[0]), key(co[-1])):
                    for other in at[end]:
                        tags = ways[other][0]
                        if other not in parent and tags.get('_hsr_state') == 'new_build':
                            touch[tags['_hsr_ids']].add(end)
            if km > longest_km or len(touch) != 1:
                continue
            (identity, places), = touch.items()
            if len(places) < 2:
                continue
            for w in run:
                tags = ways[w][0]
                donor = next(ways[o][0] for e in places for o in at[e] if o not in parent and ways[o][0].get('_hsr_ids') == identity)
                tags.update({'_hsr_state': 'new_build', '_hsr_match': 'between_new_build', '_hsr_ids': identity,
                             '_hsr_refs': donor.get('_hsr_refs', '')})
            counts['unresolved'] -= len(run)
            counts['new_build'] += len(run)
            counts['between_new_build_ways'] += len(run)
        return counts


# names of a bridge, tunnel or other structure on a line, not of the line
STRUCTURE = re.compile(r'(tunnel|brücke|bruecke|talbrücke|viadu[ck]t|viaduc|viadotto|galleria|t[uú]nel|viaducto|pont |ponte|brug|tunel|überführung|unterführung|einschnitt|kurve)', re.I)


def _length_km(co):
    import math
    return sum(math.hypot((b[0] - a[0]) * math.cos(math.radians((a[1] + b[1]) / 2)), b[1] - a[1]) for a, b in zip(co, co[1:])) * 111.32


def uniform_tags(tags_km):
    rows = {row for row, length in tags_km.items() if length > 0}
    if len(rows) > 1:
        raise ValueError('HSR identity and speed require per-track evidence stretches')
    return dict(next(iter(rows))) if rows else {}


def identity_kind(tags, fallback):
    """Three-state identity. Neither maxspeed nor highspeed proves new construction."""
    if tags.get('railway') == 'preserved' or tags.get('railway:preserved') == 'yes' or tags.get('usage') == 'tourism':
        return 'heritage'
    if tags.get('_hsr_state') == 'new_build':
        return 'hs'
    if tags.get('_hsr_state') == 'upgraded_existing':
        return 'main' if tags.get('usage') == 'main' else 'branch'
    # Only listed new-build lines are high-speed (the user, 2026-10-17: an upgraded line "不算"); an
    # unresolved way with a running limit of 200 or more is drawn as conventional, not by its limit
    # (Berlin-Hamburger Bahn, Hannover-Hamburg, Berlin-Halle, Bologna-Ancona were high-speed so).
    if fallback == 'hs':
        return 'main' if tags.get('usage') == 'main' else 'branch'
    return fallback


def install(cfg, registry=None):
    """Compose Country callbacks once. Requires existing track_stretches=True.

    Unresolved ways preserve the previous rendering with an explicit audit state.
    A way's own design/operating evidence is still evaluated by cfg.speed_of.
    The source catalogue's research values never enter production speed fields.
    """
    if getattr(cfg, '_europe_hsr_installed', False):
        return cfg
    if not cfg.track_stretches:
        raise ValueError('European HSR identity needs per-track stretches')
    registry = registry or Registry()
    old_kind, old_speed = cfg.kind_of, cfg.speed_of
    old_stretch, old_props, old_preflight = cfg.stretch_of, cfg.rail_properties, cfg.urban_preflight
    cfg.tag_keys = tuple(dict.fromkeys(cfg.tag_keys + TAG_KEYS))

    def preflight(extract):
        if old_preflight:
            old_preflight(extract)
        registry.annotate(extract, cfg.code)

    def stretch(name, tags, coordinates):
        return json.dumps({'track': old_stretch(name, tags, coordinates),
                           'hsr': {key: tags[key] for key in TAG_KEYS if key in tags}},
                          ensure_ascii=True, sort_keys=True, separators=(',', ':'))

    def kind(name, tags_km):
        tags = uniform_tags(tags_km)
        return identity_kind(tags, old_kind(name, tags_km))

    def speed(name, railway_kind, tags_km):
        if railway_kind != 'hs':
            return None
        return old_speed(name, railway_kind, tags_km)

    def properties(tags_by_way):
        result = dict(old_props(tags_by_way) or {}) if old_props else {}
        signatures = {tuple(tags.get(key, '') for key in TAG_KEYS) for tags in tags_by_way.values()}
        if len(signatures) > 1:
            raise ValueError('A rail feature combines different HSR evidence scopes')
        if not signatures:
            result['hsr_state'] = 'unresolved'
            return result
        state, ids, refs, match = next(iter(signatures))
        result.update(hsr_state=state or 'unresolved', hsr_match=match or 'none')
        if ids:
            result['hsr_identity'] = ids
        if refs:
            result['hsr_identity_ref'] = refs
        if state in ('unresolved', 'construction_unresolved'):
            result['hsr_identity_unresolved'] = 1
        return result

    cfg.urban_preflight, cfg.stretch_of = preflight, stretch
    cfg.kind_of, cfg.speed_of, cfg.rail_properties = kind, speed, properties
    cfg._europe_hsr_installed = True
    return cfg


def audit_extract(extract, code, cfg, registry=None):
    """Read-only native input audit. No selected-geometry or whole-country rebuild."""
    registry = registry or Registry()
    from process_jp import km
    before = {wid: dict(tags) for wid, tags, _ in extract['ways']}
    registry.annotate(extract, code)
    decisions, unresolved_hs = [], []
    totals = Counter()
    by_name = defaultdict(lambda: {'ways': [], 'track_km': 0.0, 'previous_hs_km': 0.0})
    for wid, tags, coordinates in extract['ways']:
        old = before[wid]
        if old.get('railway') not in cfg.rail or old.get('service') or old.get('usage') in cfg.skip_usage:
            continue
        length = km(coordinates)
        old_row = tuple(sorted((key, old[key]) for key in cfg.tag_keys if old.get(key)))
        old_kind = cfg.kind_of(old.get('name', ''), Counter({old_row: length}))
        new_kind = identity_kind(tags, old_kind)
        state = tags['_hsr_state']
        totals[state + '_ways'] += 1
        totals[state + '_track_km'] += length
        if state != 'unresolved':
            group = by_name[(old.get('name', ''), tags.get('_hsr_ids'), state)]
            group['ways'].append(wid)
            group['track_km'] += length
            group['previous_hs_km'] += length if old_kind == 'hs' else 0
        row = dict(way_id=wid, raw_name=old.get('name',''), previous_kind=old_kind, candidate_kind=new_kind,
                   state=state, identity=tags.get('_hsr_ids'), identity_match=tags['_hsr_match'],
                   track_km=round(length, 6), tags={k:old[k] for k in ('railway','usage','highspeed','maxspeed','maxspeed:design','design_speed') if k in old})
        if old_kind != new_kind:
            decisions.append(row)
        elif old_kind == 'hs' and state == 'unresolved':
            unresolved_hs.append(row)
    research=[]
    names=Counter(normal_name(tags.get('name','')) for _,tags,_ in extract['ways'])
    for row in registry.data['records']:
        if row['country'] != code:
            continue
        candidates=row['research'].get('osm_names',[])
        research.append(dict(id=row['id'],name=row['name'],identity=row['identity'],blockers=row['blockers'],
            candidate_name_counts={name:names[normal_name(name)] for name in candidates},
            active_names=row['exact_names'],verified_sources=row['verified_sources']))
    groups=[]
    for (name, identity, state), row in sorted(by_name.items()):
        groups.append(dict(raw_name=name,identity=identity,state=state,source_way_ids=sorted(row['ways']),
                           track_km=round(row['track_km'],6),previous_hs_km=round(row['previous_hs_km'],6)))
    return dict(country=code,scope='native eligible running way evidence; no selected geometry regenerated',
                totals={key:round(value,6) for key,value in sorted(totals.items())},
                changed_ways=decisions,verified_native_groups=groups,
                unresolved_previous_hs=unresolved_hs,research_records=research)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('codes', nargs='*', default=['de','fr','ch','es','nl','be','it'])
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    from process_europe import COUNTRIES
    args.report_dir.mkdir(parents=True, exist_ok=True)
    manifest=[]
    for code in args.codes:
        input_file=ROOT / 'data/raw' / ('extract_'+code+'.pkl')
        payload=input_file.read_bytes()
        extract=pickle.loads(payload)             # trusted local pipeline pickle
        report=audit_extract(extract,code,COUNTRIES[code])
        report['extract_sha256']=hashlib.sha256(payload).hexdigest()
        report['catalog_sha256']=hashlib.sha256(CATALOG.read_bytes()).hexdigest()
        output=args.report_dir / (code+'-native-audit.json')
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        manifest.append(dict(country=code,extract_sha256=report['extract_sha256'],
                             changed_ways=len(report['changed_ways']),unresolved_hs_ways=len(report['unresolved_previous_hs']),totals=report['totals']))
        print(code, 'changed ways',len(report['changed_ways']),'unresolved previous hs',len(report['unresolved_previous_hs']),flush=True)
        del extract,payload
    (args.report_dir/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    main()
