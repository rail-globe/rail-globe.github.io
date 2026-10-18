"""Source-supported station display capsules. Authoritative Point coordinates never move.

``annotate(stations, metro, stopping=extract['stops'])`` is the build API. A capsule
requires two distinct parallel services and route stop or
platform evidence for this station on both services. Proximity is only a candidate
search, never evidence that a line calls here. Missing evidence keeps the dot.

cp is compact JSON: v=1, a=display anchor, t=nearby point along canonical path,
m=offset properties of its stopping members. Runtime computes the real screen
extent with ContinuousOffset.pixels, not bn times a guessed constant. cpe is an
audit-only provenance record, intentionally excluded from vector tiles.
"""
import argparse
import copy
import json
import math
import pickle
import re
import statistics
from collections import defaultdict
from pathlib import Path

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

from continuous_offset import value_at
from metro_stops import canon, metres

ROOT = Path(__file__).resolve().parents[1]
SEARCH_M = 25
SAME_STOP_M = 150


def project_line(coords, point):
    """Bounded segment projection, including repeated vertices without GEOS FP flags."""
    walked, best = 0.0, None
    for a, b in zip(coords, coords[1:]):
        dx, dy = b[0]-a[0], b[1]-a[1]
        size = math.hypot(dx, dy)
        if not size:
            continue
        t = max(0.0, min(1.0, ((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(size*size)))
        near = [a[0]+t*dx, a[1]+t*dy]
        distance = math.hypot(point[0]-near[0], point[1]-near[1])
        if best is None or distance < best[0]:
            best = distance, walked+t*size, near
        walked += size
    return (best[1], best[2]) if best else (None, None)


def identity(p):
    return '|'.join(str(p.get(k, '')) for k in ('network', 'n', 'rid'))


# A route relation named after the line and then its direction or ends ("上海地铁2号线：浦东国际机场
# → 徐泾东", "香港電車筲箕灣至堅尼地城 Hong Kong Tramways ..."): the line's name, then a separator.
ROUTE_SUFFIX = re.compile(r'^\s*[：:（(\s\-–—]')


def route_ids(p, relations=()):
    """Prefer explicit relation identities. Never match a line by colour/proximity."""
    if p.get('rid'):
        return {int(v) for v in str(p['rid']).split(',') if v.isdigit()}
    # Older Chinese, Japanese, Korean and British metro output has no rid. Only source names
    # resolve it: the relation's name is the line's, or the line's followed by a separator and
    # its direction (an exact name alone matched 92 of China's 360 stations on side-by-side lines;
    # with the direction 262, 2026-10-18). "1号线" never matches "11号线": a separator must follow.
    # A line drawn under its route master's name ("Metrolink: Altrincham to/from Piccadilly", whose
    # routes are "Metrolink: Piccadilly => Altrincham") is the master's routes: Manchester's
    # Metrolink stops had no capsule (2026-10-18). A relation name may also put its network in front
    # ("London Trams: Wimbledon - Elmers End" for the line "Wimbledon - Elmers End").
    names = {p.get(k) for k in ('n', 'ne') if p.get(k)}
    urban = {'subway', 'light_rail', 'tram', 'monorail'}
    found = set()
    for rid, tags, members in relations:
        if tags.get('type') == 'route' and tags.get('route') in urban:
            master = False
        elif tags.get('type') == 'route_master' and tags.get('route_master') in urban:
            master = True
        else:
            continue
        values = [tags.get(k) for k in ('name', 'name:zh', 'name:en') if tags.get(k)]
        # without the network, only the whole name: "Altrincham" is not "Altrincham => Piccadilly"
        bare = [v.split(': ', 1)[1] for v in values if ': ' in v]
        if any(value in names or any(value.startswith(n) and ROUTE_SUFFIX.match(value[len(n):]) for n in names)
               for value in values) or any(value in names for value in bare):
            if master:
                found.update(ref for kind, ref in members or () if kind == 'r')
            else:
                found.add(rid)
    return found


def _stop_name(name):
    # Lettered platform names remain tied to the same named station, within 150m. A German station
    # named with its modes in front ("S Anhalter Bahnhof", "S+U Friedrichstraße") is the stop its
    # routes call at without them ("Anhalter Bahnhof"): Berlin's S-Bahn stations had no capsule (2026-10-18).
    name = re.sub(r'^(?:S\+U|U\+S|S|U)\s+', '', name or '')
    return canon(re.sub(r'\s*\([A-Za-z0-9]{1,3}\)$', '', name))


def _calls(station, ids, line_stops):
    at = station['geometry']['coordinates']
    names = {_stop_name(station['properties'].get(k, '')) for k in ('n', 'nz', 'ne')}
    names.discard('')
    evidence = []
    for rid in sorted(ids):
        for stop in line_stops.get(rid, ()):
            name, x, y = stop['name'], *stop['at']
            distance = metres(at, (x, y))
            if _stop_name(name) in names and distance <= SAME_STOP_M:
                evidence.append({**stop, 'rid': rid, 'stop': name, 'distance_m': round(distance, 3)})
    return evidence


def annotate(stations, metro, *, stopping=None, relations=(), audit=None):
    """Return station copies with display metadata; preserve count, order and geometry.

    All metadata is rebuilt, making repeated builds idempotent. Ambiguous nearby
    bundle corridors retain their dots. Separate tracks retain their own anchors.
    ``audit`` optionally receives a decision for each metro station, including
    conservative failures. China callers may pass metro-only stations without m.
    """
    stopping = stopping or {'routes': {}, 'nodes': {}, 'platforms': {}, 'areas': {}}
    ids = {identity(f['properties']): route_ids(f['properties'], relations) for f in metro}
    line_stops = defaultdict(list)
    for rid in set().union(*ids.values()) if ids else set():
        for kind, ref, role in stopping['routes'].get(rid, ()):
            row = stopping['nodes' if kind == 'n' else 'platforms'].get(ref) if kind in {'n', 'w'} else None
            if not row:
                continue
            tags, x, y = row
            if not (role.startswith(('stop', 'platform')) or tags.get('public_transport') in {'stop_position', 'platform'}
                    or tags.get('railway') in {'stop', 'tram_stop', 'platform'}):
                continue
            name = tags.get('name:zh') or tags.get('name') or stopping['areas'].get(ref, '')
            line_stops[rid].append({'name': name, 'at': [x,y], 'type': kind, 'ref': ref, 'role': role})
    records = []
    for f in metro:
        p = f['properties']
        if p.get('zf') or p.get('zn'):
            continue  # paired geometry needs an explicit source/display switch
        parts = f['geometry']['coordinates'] if f['geometry']['type'] == 'MultiLineString' else [f['geometry']['coordinates']]
        for co in parts:
            if len(co) >= 2:
                geom = LineString(co)
                if geom.length > 0:
                    records.append((f, geom))
    geometries = [geom for _, geom in records]
    tree = STRtree(geometries)
    result = []
    for original in stations:
        station = copy.deepcopy(original)
        p = station['properties']
        for key in ('cp', 'cpe', 'cap', 'cc', 'rot', 'ck'):
            p.pop(key, None)
        at = station['geometry']['coordinates']
        entry = {'station': p.get('n'), 'at': at[:], 'status': 'dot', 'reason': 'no_proven_bundle'}
        candidates = {}
        coslat = max(.1, math.cos(math.radians(at[1])))
        # This is a geometry lookup only. _calls below supplies the stopping proof.
        radius = 75
        dx = radius / (111320 * max(.1, math.cos(math.radians(at[1]))))
        dy = radius / 111320
        for index in tree.query(box(at[0] - dx, at[1] - dy, at[0] + dx, at[1] + dy)):
            index = int(index)
            f, geom = records[index]; props = f['properties']; key = identity(props)
            calls = _calls(station, ids[key], line_stops)
            if not calls:
                continue
            metric = LineString([(x*coslat,y) for x,y in geom.coords])
            def project(point):
                distance, nearest=project_line(list(metric.coords), [point[0]*coslat,point[1]])
                return distance, [nearest[0]/coslat,nearest[1]]
            md, anchor = project(at)
            d, _ = project_line(list(geom.coords), anchor)
            distance = metres(at, anchor)
            if distance > radius:
                continue
            # The corresponding source stop must also lie on this local part.
            local_calls = [row for row in calls if metres(row['at'], project(row['at'])[1]) <= 35
                           and metres(anchor, project(row['at'])[1]) <= SAME_STOP_M]
            if not local_calls:
                continue
            room = min(metric.length, 10 / 111320)
            lo, hi = max(0, md - room), min(metric.length, md + room)
            a, b = metric.interpolate(lo), metric.interpolate(hi)
            if a.distance(b) < 1e-12:
                continue
            tangent = [anchor[0] + (b.x - a.x)/coslat, anchor[1] + b.y - a.y]
            off = props.get('off', 0)
            if props.get('op'):
                profile = props['op']
                if isinstance(profile, str):
                    profile = json.loads(profile)
                off = value_at(profile, d)
            member = {k: props[k] for k in ('jk', 'sh', 'ap', 'goff', 'g', 'r', 'k') if k in props}
            display_id = json.dumps([props.get(k) for k in ('g','r','ct','network','rid','n','col','zf','zn')], ensure_ascii=False, separators=(',', ':'))
            member.update(a=anchor, t=tangent, off=off, id=display_id, ends=[list(geom.coords[0]),list(geom.coords[-1])], d=d)
            row = (distance, member, {'line': key, 'calls': local_calls})
            if key not in candidates or distance < candidates[key][0]:
                candidates[key] = row
        rows = sorted(candidates.values(), key=lambda row: (row[0], row[2]['line']))
        if len(rows) >= 2:
            reference = rows[0][1]
            def vector(a, b):
                return ((b[0]-a[0])*coslat*111320, (b[1]-a[1])*111320)
            vx, vy = vector(reference['a'], reference['t']); norm = math.hypot(vx, vy)
            ux, uy = vx/norm, vy/norm
            accepted = []
            for row in rows:
                member = row[1]
                x, y = vector(member['a'], member['t']); length = math.hypot(x, y)
                parallel = abs((x*ux+y*uy)/length)
                dx, dy = vector(reference['a'], member['a'])
                longitudinal, transverse = abs(dx*ux+dy*uy), abs(-dx*uy+dy*ux)
                if parallel >= .97 and longitudinal <= 20 and transverse <= 60:
                    accepted.append(row)
            if len(accepted) >= 2:
                # A coincident unseated service is a single screen track, not a capsule.
                spread = max(metres(a[1]['a'], b[1]['a']) for a in accepted for b in accepted)
                seats = [row[1]['off'] * (1 if sum(a*b for a,b in zip(vector(row[1]['a'], row[1]['t']), (ux,uy))) >= 0 else -1) for row in accepted]
                if spread >= .3 or max(seats)-min(seats) >= .1:
                    payload = {'v': 1, 'a': reference['a'], 't': reference['t'], 'm': [row[1] for row in accepted]}
                    p['cp'] = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
                    p['cpe'] = [row[2] for row in accepted]
                    entry.update(status='capsule', reason='parallel_local_paths_and_route_stops',
                                 anchor=payload['a'], members=p['cpe'], distance_m=round(rows[0][0], 3))
            else:
                entry['reason'] = 'nonparallel_or_longitudinally_separate'
        if audit is not None:
            audit.append(entry)
        result.append(station)
    return result


def station_display(stations, metro, extract):
    """A country's stations with capsule display metadata on its metro stations (m), from the route
    stop evidence of its extract. For the countries whose pipelines had none (Japan, Korea, the UK:
    "所有的都改一下哈，胶囊，圆点（所有国家/城市）", 2026-10-18); Europe's own hook adds Italy's names."""
    selected = [f for f in stations if f['properties'].get('m')]
    annotated = iter(annotate(selected, metro, stopping=extract.get('stops'), relations=extract.get('relations', ())))
    return [next(annotated) if f['properties'].get('m') else f for f in stations]



# ---- railway stations (2026-10-18: "铁路站也要胶囊") ----
# A railway station where several drawn railway lines that stop there run side by side (Tokyo's
# Yamanote and Keihin-Tohoku lines, Stratford's Elizabeth line and Great Eastern trains) gets a
# capsule across them. Evidence is per service: a route=train relation that calls here (a stop or
# platform of the station's name, within RAIL_STOP_M) and whose member tracks near the station are
# the drawn line's tracks. A train service is not a drawn line (the line is the infrastructure), so
# the service is put on the line its tracks are (by the track's own name, else its route=railway
# relation's: the names the drawn lines are built from; a track without either by lying along the
# drawn line, runs_on), never on the line that is merely nearest to the station.
RAIL_ROUTES = {'train'}
RAIL_STOP_M = 400        # a railway station's node to a calling service's stop or platform (long platforms)
RAIL_SEARCH_M = 120      # drawn lines within this of the station are candidates (a geometry lookup only)
TRACK_M = 200            # the stretch of a service's member tracks, about the station, compared with the lines
MATCH_M = 6.0            # a service runs on a drawn line when its tracks lie this close to it (median)
TIE_M = 1.5              # lines this close to each other about the service's tracks are one track
DECISIVE = .6            # otherwise the nearest line must be this much nearer than the next one
RAIL_LONGITUDINAL_M = 40
RAIL_TRANSVERSE_M = 90
FAST = ('hsr400', 'hsr350', 'hsr300', 'hsr250', 'hsr200', 'hsr160', 'hsrslow')


def _rail_stop_name(name):
    """A stop's name as its station's: 田端駅 is 田端, 서울역 is 서울 (canon already strips 站)."""
    plain = _stop_name(name)
    return re.sub(r'(駅|역)$', '', plain) if len(plain) > 1 else plain


def _named(service, line):
    """The service's relation is named after this drawn line (its name, then a separator)."""
    return bool(service and line) and (service == line or (service.startswith(line) and bool(ROUTE_SUFFIX.match(service[len(line):]))))


def runs_on(samples, candidates, *, service_name=None, names=None):
    """The drawn lines a service runs on near a station.

    samples: points in metres (the station at the origin) along the service's member tracks;
    candidates: {key: geometry in the same metres}. The line nearest the tracks by median distance,
    within MATCH_M and DECISIVE-ly nearer than the next; the lines within TIE_M of it are one track
    (a guest drawn beside its host) and all count, unless some of them are named after the
    service, which then are its lines. Nothing when it is unclear."""
    if not samples or not candidates:
        return set()
    points = [Point(s) for s in samples]
    scores = sorted(((statistics.median(geom.distance(q) for q in points), key) for key, geom in candidates.items()),
                    key=lambda row: row[0])
    best = scores[0][0]
    if best > MATCH_M:
        return set()
    tied = [key for d, key in scores if d <= best + TIE_M]
    rest = [d for d, key in scores if d > best + TIE_M]
    if rest and best > DECISIVE * rest[0]:
        return set()
    if len(tied) > 1 and best > MATCH_M / 2:
        return set()                      # between two tracks, on neither
    named = [key for key in tied if names and _named(service_name, names.get(key))]
    return set(named or tied)


def _spelling(name):
    return re.sub(r'\s+', '', (name or '')).casefold()


COMPANY = re.compile(r'^(jr|ｊｒ)$')     # process_jp.py writes JR's lines as JR + the track's name


def track_is(track, line):
    """A track named `track` is one of the drawn line's tracks (both spelled by _spelling)."""
    return track == line or (line.endswith(track) and bool(COMPANY.match(line[:len(line) - len(track)])))


def service_lines(pieces, lines, spelled, *, guests=(), service_name=None, names=None):
    """The drawn lines a calling service runs on near a station, with its length of track on each.

    pieces: [((a member track's own names, its route=railway relations' names), its length in
    metres, points along it)] within TRACK_M of the station; lines: {key: drawn geometry in the same
    metres}; spelled: {key: its names}. A member track is a line's when its own name is the line's
    (else its route=railway relation's, the legal line it belongs to); a
    track without such a name is the line it lies along (runs_on). A guest drawn beside its host
    (China's suburban trains) on its host's track is the service's line when the service is named
    after it. A line counts with at least 30 m and a quarter of the service's identified track."""
    if not pieces or not lines:
        return {}
    samples = [q for _, _, points in pieces for q in points]
    named_guests = [key for key in guests if key in lines and names and _named(service_name, names.get(key))]
    if named_guests:
        on = runs_on(samples, {key: lines[key] for key in named_guests})
        if on:
            return {key: sum(length for _, length, _ in pieces) for key in on}
    length = defaultdict(float)
    def named(track):
        return {key for key in lines if key not in guests and any(track_is(t, l) for t in track for l in spelled.get(key, ()))}
    for (own, legal), size, points in pieces:
        by_name = named(own) or named(legal)
        for key in by_name or runs_on(points, {k: g for k, g in lines.items() if k not in guests}):
            length[key] += size
    total = sum(length.values())
    return {key: size for key, size in length.items() if size >= 30 and size >= .25 * total}


def _width_class(props):
    c = props.get('c')
    return 'fast' if c in FAST else 'own' if props.get('lc') and isinstance(props.get('g'), str) else 'main' if c == 'main' else 'branch'


def _member(f, geom, at, mode):
    """A drawn line's capsule member at a station: where the station projects onto this part (a),
    a point along it (t), its seat (off, or its op profile there) and the identity the page uses to
    look up its continuous offset (id, ends, d). Railway members carry their drawing (mode, wc, gl)."""
    props = f['properties']
    coslat = max(.1, math.cos(math.radians(at[1])))
    metric = LineString([(x * coslat, y) for x, y in geom.coords])
    md, near = project_line(list(metric.coords), [at[0] * coslat, at[1]])
    anchor = [near[0] / coslat, near[1]]
    d, _ = project_line(list(geom.coords), anchor)
    room = min(metric.length, 10 / 111320)
    lo, hi = max(0, md - room), min(metric.length, md + room)
    a, b = metric.interpolate(lo), metric.interpolate(hi)
    if a.distance(b) < 1e-12:
        return None
    tangent = [anchor[0] + (b.x - a.x) / coslat, anchor[1] + b.y - a.y]
    off = props.get('off')
    if props.get('op'):
        profile = props['op']
        if isinstance(profile, str):
            profile = json.loads(profile)
        off = value_at(profile, d)
    member = {k: props[k] for k in ('jk', 'sh', 'ap', 'goff', 'g', 'r', 'k', 'c', 'lead', 'bn', 'zf', 'zn') if k in props}
    if off is not None or mode != 'guest':
        member['off'] = off or 0          # a guest with no seat stands one step beside its host (page: off ?? 1)
    if mode != 'metro':
        member['mode'] = mode
    if mode == 'rail':
        member['wc'] = _width_class(props)
        seat, host = props.get('off', 0) or 0, (props.get('lead') == 1 if 'lead' in props else (props.get('off', 0) or 0) < 0)
        if isinstance(props.get('g'), str) and (seat != 0 or (props.get('bn') or 0) >= 2) and not host:
            member['gl'] = 1              # drawn at a guest's width beside its host (page: guestLook)
    display_id = json.dumps([props.get(k) for k in ('g', 'r', 'ct', 'network', 'rid', 'n', 'col', 'zf', 'zn')],
                            ensure_ascii=False, separators=(',', ':'))
    member.update(a=anchor, t=tangent, id=display_id, ends=[list(geom.coords[0]), list(geom.coords[-1])], d=d)
    return metres(at, anchor), member


def _line_key(mode, props):
    return json.dumps([mode, *(props.get(k) for k in ('g', 'r', 'ct', 'network', 'rid', 'n', 'col'))], ensure_ascii=False)


def annotate_rail(stations, lines, extract, *, metro=(), skip=None, audit=None):
    """Railway station copies with capsule metadata; count, order and geometry are kept.

    lines: [(feature, mode)], mode 'rail' (a railway line, drawn in the page's rail mode) or 'guest'
    (China's suburban trains and high-speed guests, drawn one step beside their host); metro: the
    metro features, a member where a metro line stops at a railway station that has no metro
    station of its own beside it (Seoul's line 1 at 영등포). skip(properties): stations left as
    they are (a metro station with a metro capsule). Rebuilds cp/cpe, so it is idempotent."""
    relations = extract.get('relations', ())
    stopping = extract.get('stops') or {'routes': {}, 'nodes': {}, 'platforms': {}, 'areas': {}}
    services = {rid: (tags, [ref for kind, ref in members if kind == 'w'])
                for rid, tags, members in relations if tags.get('type') == 'route' and tags.get('route') in RAIL_ROUTES}
    calls_at = defaultdict(list)          # a stop's name -> [(service, place)]
    for rid in services:
        for kind, ref, role in stopping['routes'].get(rid, ()):
            row = stopping['nodes' if kind == 'n' else 'platforms'].get(ref) if kind in {'n', 'w'} else None
            if not row:
                continue
            tags, x, y = row
            if not (role.startswith(('stop', 'platform')) or tags.get('public_transport') in {'stop_position', 'platform'}
                    or tags.get('railway') in {'stop', 'halt', 'station', 'platform'}):
                continue
            for name in {tags.get('name:zh'), tags.get('name'), tags.get('name:en'), stopping['areas'].get(ref)} - {None, ''}:
                calls_at[_rail_stop_name(name)].append((rid, (x, y)))
    wanted = {ref for _, refs in services.values() for ref in refs}
    tracks = {wid: co for wid, _, co in extract.get('ways', ()) if wid in wanted}
    # which line a track is: its own name, else the route=railway relations it is in (the names the
    # pipelines build the drawn lines from). The track's own name comes first: Tokyo's Yamanote and
    # Keihin-Tohoku tracks are named so and are also in the legal 東海道本線 relation.
    own_names, legal_names = defaultdict(set), defaultdict(set)
    for wid, tags, _ in extract.get('ways', ()):
        if wid in wanted and tags.get('name'):
            own_names[wid].add(_spelling(tags['name']))
    for rid, tags, members in relations:
        if tags.get('type') == 'route' and tags.get('route') == 'railway' and tags.get('name'):
            for kind, ref in members:
                if kind == 'w' and ref in wanted:
                    legal_names[ref].add(_spelling(tags['name']))
    track_names = {wid: (own_names.get(wid, set()), legal_names.get(wid, set())) for wid in wanted}
    # metro members: the metro method's own evidence (route_ids and their stops), unchanged
    ids = {identity(f['properties']): route_ids(f['properties'], relations) for f in metro}
    metro_stops = defaultdict(list)
    for rid in set().union(*ids.values()) if ids else set():
        for kind, ref, role in stopping['routes'].get(rid, ()):
            row = stopping['nodes' if kind == 'n' else 'platforms'].get(ref) if kind in {'n', 'w'} else None
            if not row:
                continue
            tags, x, y = row
            if not (role.startswith(('stop', 'platform')) or tags.get('public_transport') in {'stop_position', 'platform'}
                    or tags.get('railway') in {'stop', 'tram_stop', 'platform'}):
                continue
            metro_stops[rid].append({'name': tags.get('name:zh') or tags.get('name') or stopping['areas'].get(ref, ''),
                                     'at': [x, y], 'type': kind, 'ref': ref, 'role': role})
    records = []
    for f, mode in [*lines, *((f, 'metro') for f in metro)]:
        if mode == 'metro' and (f['properties'].get('zf') or f['properties'].get('zn') or f['properties'].get('k') == 's'):
            continue
        parts = f['geometry']['coordinates'] if f['geometry']['type'] == 'MultiLineString' else [f['geometry']['coordinates']]
        for co in parts:
            if len(co) >= 2 and LineString(co).length > 0:
                records.append((f, mode, LineString(co)))
    tree = STRtree([geom for _, _, geom in records]) if records else None
    urban = defaultdict(list)             # metro stations by name: a railway station beside one leaves its metro to it
    railway = defaultdict(list)           # and railway stations by name: a metro station beside one leaves the railway to it
    for f in stations:
        for k in ('n', 'nz', 'ne'):
            if f['properties'].get(k):
                (urban if f['properties'].get('m') else railway)[_stop_name(f['properties'][k])].append(f['geometry']['coordinates'])
    result = []
    for original in stations:
        station = copy.deepcopy(original)
        p = station['properties']
        if skip and skip(p):
            result.append(station)
            continue
        for key in ('cp', 'cpe'):
            p.pop(key, None)
        at = station['geometry']['coordinates']
        entry = {'station': p.get('n'), 'at': at[:], 'status': 'dot', 'reason': 'no_parallel_stopping_lines'}
        result.append(station)
        if tree is None:
            continue
        if p.get('m') and any(metres(at, q) <= RAIL_STOP_M for k in ('n', 'nz', 'ne') if p.get(k)
                              for q in railway.get(_stop_name(p[k]), ())):
            # Tokyo Metro's 上野 beside JR's 上野: the railway capsule is the railway station's. A metro
            # station is the railway station only where there is no other (Stratford).
            entry['reason'] = 'railway_station_beside'
            if audit is not None:
                audit.append(entry)
            continue
        coslat = max(.1, math.cos(math.radians(at[1])))
        to_m = lambda q: ((q[0] - at[0]) * coslat * 111320, (q[1] - at[1]) * 111320)
        dx, dy = 300 / (111320 * coslat), 300 / 111320
        near = defaultdict(list)          # line key -> [(distance, feature, mode, part)]
        for index in tree.query(box(at[0] - dx, at[1] - dy, at[0] + dx, at[1] + dy)):
            f, mode, geom = records[int(index)]
            local = LineString([to_m(q) for q in geom.coords])
            near[_line_key(mode, f['properties'])].append((local.distance(Point(0, 0)), f, mode, geom, local))
        close = {key for key, rows in near.items() if min(r[0] for r in rows) <= RAIL_SEARCH_M}
        if len(close) < 2:
            if audit is not None:
                audit.append(entry)
            continue
        names = {_rail_stop_name(p.get(k, '')) for k in ('n', 'nz', 'ne')} - {''}
        calling = {}
        for name in names:
            for rid, place in calls_at.get(name, ()):
                distance = metres(at, place)
                if distance <= RAIL_STOP_M and distance < calling.get(rid, 1e9):
                    calling[rid] = distance
        own_track = {key: unary_union([r[4] for r in near[key] if not r[1]['properties'].get('zf')])
                     for key in close if near[key][0][2] != 'metro'}
        own_track = {key: geom for key, geom in own_track.items() if not geom.is_empty}
        line_names = {key: near[key][0][1]['properties'].get('n') for key in own_track}
        spelled = {key: {_spelling(near[key][0][1]['properties'].get(k)) for k in ('n', 'ne')} - {''} for key in own_track}
        guests = {key for key in own_track if near[key][0][2] == 'guest'}
        evidence = defaultdict(list)
        circle = Point(0, 0).buffer(TRACK_M)
        for rid, distance in sorted(calling.items()):
            pieces = []
            for wid in services[rid][1]:
                co = tracks.get(wid)
                if not co or len(co) < 2:
                    continue
                piece = LineString([to_m(q) for q in co])
                if piece.distance(Point(0, 0)) > TRACK_M:
                    continue
                clipped = piece.intersection(circle)
                for g in getattr(clipped, 'geoms', [clipped]):
                    if g.geom_type == 'LineString' and g.length > 0:
                        n = max(2, int(g.length // 5) + 1)
                        pieces.append((track_names.get(wid, (set(), set())), g.length,
                                       [tuple(g.interpolate(i / (n - 1), normalized=True).coords[0]) for i in range(n)]))
            name = services[rid][0].get('name') or services[rid][0].get('name:zh') or ''
            lines_of_service = service_lines(pieces, own_track, spelled, guests=guests, service_name=name, names=line_names)
            for key, length in sorted(lines_of_service.items()):
                evidence[key].append({'rid': rid, 'service': name, 'stop_m': round(distance, 1), 'track_m': round(length, 1)})
        # a metro line stopping here by the metro method's evidence, where no metro station stands beside this one
        if not any(metres(at, q) <= SAME_STOP_M for name in names for q in urban.get(name, ())):
            for key in close:
                rows = near[key]
                if rows[0][2] != 'metro':
                    continue
                f = rows[0][1]
                calls = _calls(station, ids[identity(f['properties'])], metro_stops)
                if calls:
                    evidence[key].append({'rid': calls[0]['rid'], 'service': 'metro', 'stop_m': calls[0]['distance_m']})
        candidates = []
        for key in sorted(evidence):
            rows = sorted((r for r in near[key] if r[0] <= RAIL_SEARCH_M and not r[1]['properties'].get('zf')), key=lambda r: r[0])
            if not rows:
                continue
            made = _member(rows[0][1], rows[0][3], at, rows[0][2])
            if not made:
                continue
            spine = sorted((r for r in near[key] if r[1]['properties'].get('zf')), key=lambda r: r[0])
            twin = _member(spine[0][1], spine[0][3], at, spine[0][2]) if spine and spine[0][0] <= RAIL_SEARCH_M else None
            candidates.append((made[0], made[1], twin[1] if twin else None, {'line': key, 'services': evidence[key]}))
        candidates.sort(key=lambda row: (row[0], row[3]['line']))
        if len(candidates) >= 2:
            def vector(a, b):
                return ((b[0] - a[0]) * coslat * 111320, (b[1] - a[1]) * 111320)
            def group(reference):
                vx, vy = vector(reference['a'], reference['t']); norm = math.hypot(vx, vy)
                ux, uy = vx / norm, vy / norm
                accepted = []
                for row in candidates:
                    member = row[1]
                    x, y = vector(member['a'], member['t']); length = math.hypot(x, y)
                    parallel = abs((x * ux + y * uy) / length)
                    ddx, ddy = vector(reference['a'], member['a'])
                    if parallel >= .97 and abs(ddx * ux + ddy * uy) <= RAIL_LONGITUDINAL_M and abs(-ddx * uy + ddy * ux) <= RAIL_TRANSVERSE_M:
                        accepted.append(row)
                return accepted, (ux, uy)
            # the largest group of parallel stopping lines, nearest first: a line crossing the
            # station (秋葉原's 総武線 over the Yamanote and Keihin-Tohoku lines) is not the reference
            reference, accepted, (ux, uy) = max(((row[1], *group(row[1])) for row in candidates), key=lambda r: len(r[1]))
            if len(accepted) >= 2:
                spread = max(metres(a[1]['a'], b[1]['a']) for a in accepted for b in accepted)
                seats = [(row[1].get('off') or 0) * (1 if sum(a * b for a, b in zip(vector(row[1]['a'], row[1]['t']), (ux, uy))) >= 0 else -1)
                         for row in accepted]
                if spread >= .3 or max(seats) - min(seats) >= .1:
                    members = [m for row in accepted for m in (row[1], row[2]) if m]
                    payload = {'v': 1, 'a': reference['a'], 't': reference['t'], 'm': members}
                    p['cp'] = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
                    p['cpe'] = [row[3] for row in accepted]
                    entry.update(status='capsule', reason='parallel_lines_with_calling_services', members=p['cpe'])
            else:
                entry['reason'] = 'nonparallel_or_longitudinally_separate'
        elif candidates:
            entry['reason'] = 'one_line_stops_here'
        if audit is not None:
            audit.append(entry)
    return result


def rail_lines(code, root=ROOT):
    """The drawn lines a country's railway stations may get capsules across: [(feature, mode)]."""
    data = root / 'data'
    read = lambda name: json.loads((data / name).read_text())['features'] if (data / name).exists() else []
    if code == 'cn':
        lines = [(f, 'rail') for name in ('rail_conv.geojson', 'rail_hsr.geojson') for f in read(name)]
        lines += [(f, 'guest') for f in read('rail_shared.geojson')]
        lines += [(f, 'guest') for f in read('metro.geojson') if f['properties'].get('k') == 's']
        return lines
    return [(f, 'rail') for f in read(f'{code}_rail.geojson')]


def rail_display(code, root=ROOT, audit=None):
    """Write the railway capsules into a country's stations file, from its final line files and the
    train stops of its extract. Run after every script that rewrites those files (for China after
    process_osm.py's seat_overrides.reseat and build_graph.py; abroad at the end of process_<g>.py);
    the pipelines call this, and running it on its own on the same files gives the same result."""
    path = root / 'data' / ('stations.geojson' if code == 'cn' else f'{code}_stations.geojson')
    from owned_output import require_owned
    require_owned(path.parent, [path.name])
    stations = json.loads(path.read_text())
    metro = [] if code == 'cn' else json.loads((root / 'data' / f'{code}_metro.geojson').read_text())['features']
    with (root / 'data' / 'raw' / ('extract.pkl' if code == 'cn' else f'extract_{code}.pkl')).open('rb') as stream:
        ex = pickle.load(stream)
    # a metro station keeps its metro capsule; one without may get a railway capsule (Stratford)
    stations['features'] = annotate_rail(stations['features'], rail_lines(code, root), ex, metro=metro,
                                         skip=lambda p: bool(p.get('m') and p.get('cp') and '"mode":' not in p['cp']),
                                         audit=audit)
    path.write_text(json.dumps(stations, ensure_ascii=False, separators=(',', ':')) + '\n')
    return stations

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('country')
    parser.add_argument('what', nargs='?', choices=('metro', 'rail'), default='metro',
                        help='rail: the capsules of the railway stations (annotate_rail)')
    args = parser.parse_args()
    code = args.country
    if args.what == 'rail':
        audit = []
        rail_display(code, audit=audit)
        print(f"{code}: {sum(1 for row in audit if row['status'] == 'capsule')} railway capsules")
        return
    path = ROOT / 'data' / ('metro_stations.geojson' if code == 'cn' else f'{code}_stations.geojson')
    from owned_output import require_owned
    require_owned(path.parent, [path.name])
    stations = json.loads(path.read_text())
    metro = json.loads((ROOT / 'data' / ('metro.geojson' if code == 'cn' else f'{code}_metro.geojson')).read_text())['features']
    extract = ROOT / 'data' / 'raw' / ('extract.pkl' if code == 'cn' else f'extract_{code}.pkl')
    with extract.open('rb') as stream:
        ex = pickle.load(stream)
    selected = [f for f in stations['features'] if code == 'cn' or f['properties'].get('m')]
    annotated = iter(annotate(selected, metro, stopping=ex.get('stops'), relations=ex.get('relations', ())))
    stations['features'] = [next(annotated) if code == 'cn' or f['properties'].get('m') else f for f in stations['features']]
    path.write_text(json.dumps(stations, ensure_ascii=False, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    main()
