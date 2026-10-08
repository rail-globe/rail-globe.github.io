"""Colour the finished railway geometry by source-backed section design speeds.

Design is not an operating limit and never changes the routing graph. Section
boundaries are projected onto the finished line and cut at the same coordinate
on both sides. No track is moved, smoothed again or bridged during this step.
Unresolved endpoints, restricted source notes and conflicting references stay
unclassified rather than inheriting the highest number of a long railway.
"""
import heapq
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import substring
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
GRADES = ('hsr400', 'hsr350', 'hsr300', 'hsr250', 'hsr200', 'hsr160', 'hsrslow')
LABELS = dict(zip(GRADES, ('>350', '350', '300', '250', '200', '160', '<160')))


CONVENTIONAL = -1      # stands in for the design speed of a stretch documented as a conventional line


def brief(s):
    """A section as the coverage report lists it."""
    out = {k: s[k] for k in ('name', 'endpoints', 'design', 'url')}
    if s.get('conventional'):
        out.update(design=None, conventional=True)
    return out


def grade(speed):
    """Standard design bands. Intermediate 165/205 belong to the 160/200 band."""
    if not speed or speed <= 0:
        return None
    if speed > 350:
        return 'hsr400'
    for threshold in (350, 300, 250, 200, 160):
        if speed >= threshold:
            return 'hsr' + str(threshold)
    return 'hsrslow'


def line_name(name):
    name = re.sub(r'（[^）]*）|\([^)]*\)', '', name).strip()
    name = name.translate(str.maketrans('綫線鐵廣東運專灣臺', '线线铁广东运专湾台'))
    name = re.sub(r'(线|高铁|客专)(.{1,8}段)$', r'\1', name)
    name = re.sub(r'(高速铁路|高速线|高铁线|高铁)$', '高速', name)
    name = re.sub(r'(客运专线|客专线|客专)$', '客专', name)
    name = re.sub(r'(城际铁路|城际线|城际)$', '城际', name)
    return re.sub(r'(铁路|线)$', '', name)


# The same line goes by 高速铁路, 客运专线 or 城际铁路 from one source to the next (合蚌客专线 on the
# map is 合蚌高速线 in the catalogue). Tried only when the name as written finds nothing.
FAST_WORDS = ('高速', '客专', '城际')
# Map names the catalogue files under another name. Each pair is one physical line.
LINE_ALIASES = {'成自宜高速': '成宜高速'}                 # 成都-自贡-宜宾, opened 2023 as 成宜高铁
# Map names that take in a line the catalogue files separately: 京包客专线 on the map starts at
# 北京北, over what the catalogue calls 京张高速线. 川藏铁路 on the map includes 成都-雅安, which the
# catalogue files as 成雅线.
LINE_PARTS = {'京包客专': ('京张高速',), '川藏': ('成雅',)}
# Map names that are one card of a catalogue page, by the card's own title.
CARD_ALIASES = {'海南东环高速': ('海南环岛高速铁路东段',), '海南西环高速': ('海南环岛高速铁路西段',),
                '长沙西城际': ('长株城际铁路长沙西段',)}   # 长沙站-长沙西站, the western extension of 长株潭城际
NOMINAL_FAST = ('hsr350', 'hsr250', 'hsr200')           # classes process_osm.py gives from the track's own speed tags


def own_title(section):
    """The line a catalogue card's own title names, without the stretch: 川青铁路成镇段 is 川青."""
    # after the last word for a line: 京张高铁崇礼支线下太段 is the branch, not 京张高铁
    return line_name(re.sub(r'^(.*(?:铁路|线|高铁|客专|城际))[^段~·]{1,8}段$', r'\1', section['name'].split(' · ')[0]))


def card_aliases(section):
    """The names a catalogue card's physical line can carry on the map: its track names, and the
    card's own title without the stretch ("川青铁路成镇段" is on 川青线). Many cards have no
    separate track name. The page title is not used: it can name a corridor of several lines."""
    names = [line_name(a) for a in re.split('[；;]', section['track_name']) if a] + [own_title(section)]
    return list(dict.fromkeys(n for n in names if n))


def fast_spellings(key):
    """A fast line's name under each of the words a fast line goes by; any other name as it is."""
    for word in FAST_WORDS:
        if key.endswith(word):
            return {key[:-len(word)] + other for other in FAST_WORDS}
    return {key}


def catalogue_rows(name, by_alias, by_card):
    """(the catalogue's sections for a line on the map, the name they were found under)."""
    key = line_name(name)
    if key in CARD_ALIASES:
        return ([s for card in CARD_ALIASES[key] for s in by_card.get(card, [])] + by_alias.get(key, []),
                '、'.join(CARD_ALIASES[key]))
    if by_alias.get(key):
        more = [s for part in LINE_PARTS.get(key, ()) for s in by_alias.get(part, [])]
        return by_alias[key] + more, '、'.join(LINE_PARTS[key]) if more else None
    if key in LINE_ALIASES:
        return by_alias.get(LINE_ALIASES[key], []), LINE_ALIASES[key]
    for alias in sorted(fast_spellings(key) - {key}):
        if by_alias.get(alias):
            return by_alias[alias], alias
    return [], None


SIMPLIFIED = str.maketrans({'橋': '桥', '營': '营', '東': '东', '蘭': '兰', '灣': '湾', '臺': '台', '雲': '云', '義': '义',
                            '園': '园', '鎮': '镇', '龍': '龙', '門': '门', '關': '关', '廣': '广', '豐': '丰', '崗': '岗',
                            '頭': '头', '頂': '顶', '烏': '乌', '鳥': '鸟', '車': '车', '馬': '马', '學': '学', '會': '会',
                            '區': '区', '鄉': '乡', '鐵': '铁', '線': '线', '綫': '线', '樹': '树', '壢': '坜', '濱': '滨',
                            '寧': '宁', '楊': '杨', '員': '员', '嶺': '岭', '岡': '冈', '莊': '庄', '陽': '阳', '華': '华'})


def point_name(name):
    return re.sub(r'站$', '', name.strip().translate(SIMPLIFIED))


def parts_of(feature):
    g = shape(feature['geometry'])
    return list(g.geoms) if g.geom_type == 'MultiLineString' else [g]


def contiguous_sections(rows):
    """Remove a redundant boundary only when both sides have the same design.

    A missing L1L2 junction cannot block the known 350 span from 郑州东 to
    广州北. Unknown values and source scope caveats always stop the merge.
    """
    out = []
    for row in rows:
        s = dict(row)
        ends = s['endpoints'].split('~')
        if (out and s.get('design') and not s.get('requires_review') and len(ends) == 2
                and out[-1].get('design') == s['design'] and not out[-1].get('requires_review')
                and bool(out[-1].get('design_infrastructure')) == bool(s.get('design_infrastructure'))
                and out[-1]['url'] == s['url'] and out[-1]['endpoints'].split('~')[-1] == ends[0]):
            previous = out[-1]
            previous.setdefault('cards', [dict(previous)]).append(dict(row))
            previous['endpoints'] = previous['endpoints'].split('~')[0] + '~' + ends[1]
            previous['name'] = previous['name'].split(' · ')[0] + ' · ' + previous['endpoints']
            for field in ('operating', 'design_track', 'design_infrastructure'):
                if previous.get(field) != s.get(field):
                    previous[field] = None
        else:
            out.append(s)
    return out


class SectionPaths:
    """A small graph of one drawn line, with station projections as cut nodes."""
    def __init__(self, parts, points, boundary_names, near=.015, join=.003, beyond=.3, at_end=.02,
                 same_place=.08, gap=.03):
        self.parts, self.anchors = parts, {}
        self.snapped = []            # boundaries taken as an end of the line
        self.where = {name: points.get(point_name(name), []) for name in boundary_names}
        self.adj = defaultdict(list)
        def position(i, d):
            # Rebuilding a previously split line can project an exact endpoint to
            # 1e-15 instead of zero. Such a near-zero edge must not isolate its
            # station anchor when tiny graph edges are omitted below.
            if d < 1e-9:
                return 0.0
            if parts[i].length - d < 1e-9:
                return parts[i].length
            return round(d, 10)
        tree = STRtree(parts)
        cuts = [{0.0, g.length} for g in parts]
        links = []
        # Include branches meeting the middle of another piece, not just end-to-end joins.
        for i, g in enumerate(parts):
            for d in (0.0, g.length):
                p = g.interpolate(d)
                for j in tree.query(p, predicate='dwithin', distance=join):
                    j = int(j)
                    if j == i:
                        continue
                    other = position(j, parts[j].project(p))
                    cuts[j].add(other)
                    links.append(((i, d), (j, other), p.distance(parts[j].interpolate(other))))
        tied = {a for a, _, _ in links} | {b for _, b, _ in links}
        # A drawn line can stop and carry on a little further on (the breaks check_layers.py
        # lists). A section runs through such a break: the loose end is tied to the nearest
        # other piece within reach.
        for i, g in enumerate(parts):
            for d in (0.0, g.length):
                if (i, d) in tied:
                    continue
                p = g.interpolate(d)
                near_by = [(parts[int(j)].distance(p), int(j)) for j in tree.query(p, predicate='dwithin', distance=gap) if int(j) != i]
                if near_by:
                    distance, j = min(near_by)
                    other = position(j, parts[j].project(p))
                    cuts[j].add(other)
                    links.append(((i, d), (j, other), distance))
        tied = {a for a, _, _ in links} | {b for _, b, _ in links}
        self.loose = [(i, d) for i, g in enumerate(parts) for d in (0.0, g.length) if (i, d) not in tied]
        for name in sorted(boundary_names):
            candidates = []
            for xy in points.get(point_name(name), []):
                p = Point(xy)
                i = int(tree.nearest(p))
                if parts[i].distance(p) <= near:
                    candidates.append((parts[i].distance(p), i, parts[i].project(p), xy))
            if candidates:
                candidates.sort()
                # Same-name stations thousands of km away are excluded by line proximity.
                # Two remaining candidates far apart along this line are ambiguous.
                best = candidates[0]
                if any(Point(best[3]).distance(Point(x[3])) > same_place for x in candidates[1:]):
                    continue
                _, i, d, _ = best
                d = position(i, d)
                cuts[i].add(d)
                self.anchors[name] = (i, d)
                continue
            # A section often runs to a station the line itself stops short of: the last few
            # kilometres into 包头 or 西安北 belong to another line or to the station's own tracks.
            # Where the nearest point of the whole line to that station is a loose end of the
            # line, the section runs to that end.
            ends = []
            for xy in points.get(point_name(name), []):
                p = Point(xy)
                i = int(tree.nearest(p))
                g, d = parts[i], parts[i].project(p)
                end = 0.0 if d <= at_end else g.length if g.length - d <= at_end else None
                if end is not None and g.distance(p) <= beyond and (i, end) not in tied:
                    ends.append((g.distance(p), i, end))
            if ends and len({(i, end) for _, i, end in ends}) == 1:
                _, i, end = min(ends)
                self.anchors[name] = (i, end)
                self.snapped.append(name)
        for i, ds in enumerate(cuts):
            ds = sorted(ds)
            for a, b in zip(ds, ds[1:]):
                if b - a > 1e-12:
                    self.edge((i, a), (i, b), b - a, (i, a, b))
        for a, b, distance in links:
            self.edge(a, b, max(distance, 1e-12), None)

    def edge(self, a, b, cost, span):
        self.adj[a].append((b, cost, span))
        self.adj[b].append((a, cost, span))

    def walk(self, a, stop=()):
        """Shortest ways from node a to every node it reaches without passing a node in stop."""
        distances, prev, heap = {a: 0}, {}, [(0, a)]
        while heap:
            cost, node = heapq.heappop(heap)
            if cost != distances[node] or (node in stop and node != a):
                continue
            for other, weight, span in self.adj[node]:
                new = cost + weight
                if new < distances.get(other, float('inf')):
                    distances[other], prev[other] = new, (node, span)
                    heapq.heappush(heap, (new, other))
        return distances, prev

    @staticmethod
    def spans(prev, a, node):
        out = []
        while node != a:
            node, span = prev[node]
            if span:
                out.append(span)
        return out

    def between(self, start, end):
        if start not in self.anchors or end not in self.anchors:
            return None
        a, b = self.anchors[start], self.anchors[end]
        distances, prev = self.walk(a)
        return self.spans(prev, a, b) if b in distances else None

    def around(self, name):
        """All of the line that a boundary reaches before any other boundary."""
        a = self.anchors[name]
        stop = {node for other, node in self.anchors.items() if other != name}
        distances, prev = self.walk(a, stop)
        return list(dict.fromkeys(span for node in distances for span in self.spans(prev, a, node)))

    def other_tracks(self, spans):
        """Stretches left without a section that leave a placed section and come back to it: the
        other track where the two run apart (separate tunnels, a loop through a station). They get
        the section they leave and rejoin, when it is one and the same value at both ends.
        spans: {part: [(from, to, section)]}; returns the additions in the same form."""
        def placed(i, a, b):
            return [s for x, y, s in spans.get(i, []) if min(x, y) - 1e-9 <= a and b <= max(x, y) + 1e-9]
        edges = {}                                   # (part, from, to) -> its two nodes
        for node, links in self.adj.items():
            for other, _, span in links:
                if span:
                    edges[span] = ((span[0], span[1]), (span[0], span[2]))
        added = defaultdict(list)

        def at(node, seen=None):
            """Sections placed on the edges meeting at a node, across joins between pieces."""
            seen = seen if seen is not None else {node}
            found = []
            for other, _, span in self.adj[node]:
                if span:
                    found += placed(*span) + [s for x, y, s in added.get(span[0], []) if x <= span[1] and span[2] <= y]
                elif other not in seen:
                    seen.add(other)
                    found += at(other, seen)
            return found
        changed = True
        while changed:
            changed = False
            for span, (u, v) in edges.items():
                i, a, b = span
                if placed(i, a, b) or any(x <= a and b <= y for x, y, _ in added.get(i, [])):
                    continue
                here, there = at(u), at(v)
                if here and there and len({s['design'] for s in here + there}) == 1:
                    added[i].append((a, b, here[0]))
                    changed = True
        return added

    def towards(self, start, end):
        """The way from one boundary to the end of the line in the direction of the other, for a
        section whose other boundary is not on the drawn line: a junction the map does not name, or
        a station the line has not been built through to yet. It stops at no end that lies behind
        another boundary of the line's sections, so it never runs across a neighbouring section."""
        if start not in self.anchors or (end in self.anchors and self.between(start, end)):
            return None
        a = self.anchors[start]
        stop = {node for name, node in self.anchors.items() if name != start}
        distances, prev = self.walk(a, stop)
        ends = [node for node in self.loose if node in distances and node not in stop and node != a]
        target = [Point(xy) for xy in self.where.get(end, [])]
        if end in self.anchors:
            i, d = self.anchors[end]
            target = [self.parts[i].interpolate(d)]
        if target:
            # towards the other boundary: the end nearest to it, and nearer to it than the start is
            here = self.parts[a[0]].interpolate(a[1])
            scored = [(min(self.parts[i].interpolate(d).distance(t) for t in target), (i, d)) for i, d in ends]
            scored = [x for x in scored if x[0] < min(here.distance(t) for t in target)]
            return self.spans(prev, a, min(scored)[1]) if scored else None
        return self.spans(prev, a, ends[0]) if len(ends) == 1 else None


def split_part(g, spans, original):
    """Yield unchanged subpaths with shared cut coordinates and separate provenance."""
    cuts = sorted({0.0, g.length, *(v for a, b, _ in spans for v in (a, b))})
    runs = []
    for a, b in zip(cuts, cuts[1:]):
        if b - a < 1e-10:
            continue
        refs = [s for x, y, s in spans if x <= (a + b) / 2 <= y]
        speeds = {s['design'] for s in refs}
        section = refs[0] if len(speeds) == 1 else None
        # Merge consecutive ranges with the same source section, so station cuts
        # within a 350 section do not inflate map features or create visual joins.
        token = (section['url'], section['name']) if section else None
        if runs and runs[-1][3] == token:
            runs[-1] = (runs[-1][0], b, section, token)
        else:
            runs.append((a, b, section, token))
    for a, b, section, _ in runs:
        props = dict(original)
        props['r'] = props.pop('r', props['c'])
        # Legacy OSM maxspeed is not a section operating-speed measurement.
        props.pop('s', None)
        for field in ('d', 'dt', 'v', 'dn', 'de', 'ref', 'db'):
            props.pop(field, None)
        # No documented design value: a line that the track's own speed tags put among the fast
        # lines keeps that band, marked as an estimate (e); every other line is conventional.
        # A high-speed line is never drawn as a conventional one for want of a reference.
        props.pop('e', None)
        if props['r'] in NOMINAL_FAST:
            props.update(c=props['r'], e=1)
        else:
            props['c'] = 'main' if props['r'] != 'branch' else 'branch'
        if section and section.get('conventional'):
            # A source says what this stretch is, and it is not a fast line: an old line that the
            # trains of a fast one run over into a city, a branch. It is drawn as a conventional
            # line, with the source kept, instead of in the band of the line it is named after.
            props.pop('e', None)
            props['c'] = 'main' if props['r'] != 'branch' else 'branch'
            props.update(dn=section['name'], de=section['endpoints'], ref=section['url'])
        elif section:
            props.pop('e', None)
            props.update(c=grade(section['design']), d=section['design'],
                         dn=section['name'], de=section['endpoints'], ref=section['url'],
                         db='infrastructure' if section.get('design_infrastructure') else 'track')
            if section.get('design_track'):
                props['dt'] = section['design_track']
            if section.get('operating'):
                props['v'] = section['operating']
        piece = substring(g, a, b)
        yield {'type': 'Feature', 'properties': props, 'geometry': mapping(piece)}


def pack(features):
    """Keep all pieces sharing one annotation in a single MultiLineString."""
    groups = {}
    for f in features:
        token = json.dumps(f['properties'], sort_keys=True, ensure_ascii=False)
        if token not in groups:
            groups[token] = {'type': 'Feature', 'properties': f['properties'],
                             'geometry': {'type': 'MultiLineString', 'coordinates': []}}
        groups[token]['geometry']['coordinates'].append(f['geometry']['coordinates'])
    return list(groups.values())


BASE_FILES = ('rail_hsr.geojson', 'rail_conv.geojson', 'rail_shared.geojson', 'lines.json')


def keep_base(root=ROOT):
    """Set aside the rail layers as process_osm.py wrote them, before any colouring by design
    speed. apply() starts from these every time, so it can be run again on its own after the
    references or the written ranges change, and gives what a full run would give."""
    base = root / 'data' / 'raw' / 'design_base'
    base.mkdir(parents=True, exist_ok=True)
    for name in BASE_FILES:
        shutil.copy(root / 'data' / name, base / name)


def apply(root=ROOT):
    data = root / 'data'
    base = data / 'raw' / 'design_base'
    source = base if all((base / name).exists() for name in BASE_FILES) else data
    catalog = json.loads((data / 'rail_design_catalog.json').read_text())
    raw_points = json.loads((data / 'rail_design_points.json').read_text())['points']
    points = defaultdict(list)
    for p in raw_points:
        points[point_name(p['name'])].append(p['coordinates'])
    sections, cards = defaultdict(list), defaultdict(list)
    for page in catalog['pages']:
        for s in page['sections']:
            # Match physical track aliases only. Page titles sometimes name a service
            # corridor made of unrelated physical lines, and are not safe aliases.
            for alias in card_aliases(s):
                sections[alias].append(s)
            cards[s['name']].append(s)
    manual = data / 'rail_design_overrides.json'
    if manual.exists():
        for s in json.loads(manual.read_text())['sections']:
            # a range read from a source note covers what it names and nothing more
            s = {**s, 'scoped': True}
            if s.get('conventional'):
                s['design'] = s.get('design') or CONVENTIONAL
            sections[line_name(s['track_name'])].append(s)
    all_features, originals = [], {}
    for bucket in ('hsr', 'conv', 'shared'):
        originals[bucket] = json.loads((source / f'rail_{bucket}.geojson').read_text())
        if bucket == 'shared':
            for f in originals[bucket]['features']:
                f['properties']['_shared'] = True
        all_features.extend(originals[bucket]['features'])
    named = defaultdict(list)
    unnamed = []
    for f in all_features:
        if f['properties'].get('n'):
            named[f['properties']['n']].append(f)
        else:
            unnamed.append(f)
    output, reports = [], []
    for name, fs in named.items():
        found, alias = catalogue_rows(name, sections, cards)
        rows = contiguous_sections(found)
        parts, props = [], []
        for f in fs:
            for g in parts_of(f):
                parts.append(g)
                props.append(f['properties'])
        # the cards a merged row was made of keep their own boundaries: the row falls back on them
        boundary_names = {n for s in rows for c in [s] + s.get('cards', []) for n in c['endpoints'].split('~')}
        graph = SectionPaths(parts, points, boundary_names) if rows else None
        spans = defaultdict(list)
        used, pending = [], []
        # Every card of the line gives one and the same design value, with no caveat: the whole
        # line has it, and no boundary is needed to say where.
        # Only for a line built as one fast line: a card of a conventional line can cover no more
        # than the stretch it names.
        nominal = Counter()
        for g, q in zip(parts, props):
            nominal[q.get('r') or q['c']] += g.length
        # A card without a value that has no boundary on the drawn line (a stretch still to be
        # built) does not stand in the way.
        # Nor does a card of another title filed under the line's track name: a third track or a
        # connecting line beside it (沈南客专三线 under 沈大高速线).
        key = line_name(name)
        titles = fast_spellings(key) | fast_spellings(LINE_ALIASES.get(key, key))
        here = [s for s in rows if s.get('design') or s.get('requires_review')
                or (own_title(s) in titles and any(n in graph.anchors for n in s['endpoints'].split('~')))]
        whole = (here and all(s.get('design') and not s.get('requires_review') and not s.get('scoped') for s in here)
                 and len({s['design'] for s in here}) == 1
                 and sum(v for k, v in nominal.items() if k in NOMINAL_FAST) > .5 * sum(nominal.values()))
        if whole:
            rows = here
        extended = []
        if whole:
            for i, g in enumerate(parts):
                spans[i].append((0.0, g.length, rows[0]))
            used = [brief(s) for s in rows]
        todo, unplaced = ([] if whole else list(rows)), []
        while todo:
            s = todo.pop(0)
            ends = s['endpoints'].split('~')
            if not s.get('design') or s.get('requires_review') or len(ends) != 2:
                pending.append({'section': s['name'], 'reason': 'missing or restricted design value'})
                continue
            path = graph.between(*ends)
            if not path and s.get('cards'):
                # the merged range has an end the map cannot place: its cards one by one, some of
                # which lie between boundaries it can
                todo = [dict(c) for c in s['cards']] + todo
                continue
            if not path and not s.get('scoped'):
                path = (graph.towards(ends[0], ends[1]) or []) + (graph.towards(ends[1], ends[0]) or [])
                if path:
                    extended.append(s['name'])
            if not path:
                unplaced.append(s)
                continue
            for i, a, b in path:
                spans[i].append((a, b, s))
            used.append(brief(s))
        # Cards that could not be placed, around a boundary the map does have: where every card
        # meeting at that boundary gives the same value, the line has it on both sides, up to the
        # next boundary.
        for s in unplaced:
            ends = s['endpoints'].split('~')
            path = []
            for n in ends:
                meet = [c for r in rows for c in (r.get('cards') or [r]) if n in c['endpoints'].split('~')]
                if (n in graph.anchors and not s.get('scoped') and meet
                        and all(c.get('design') == s['design'] and not c.get('requires_review') for c in meet)):
                    path += graph.around(n)
            if path:
                for i, a, b in path:
                    spans[i].append((a, b, s))
                used.append(brief(s))
                extended.append(s['name'])
                continue
            missing = [n for n in ends if n not in graph.anchors]
            pending.append({'section': s['name'], 'reason': 'unresolved boundary' if missing else 'disconnected path',
                            'boundaries': missing})
        # the other track, where the two tracks of the line run apart
        if graph and any(spans.values()):
            for i, more in graph.other_tracks(spans).items():
                spans[i] += more
        drawn = [f for i, g in enumerate(parts) for f in split_part(g, spans[i], props[i])]
        output.extend(drawn)
        if rows:
            known = sum(shape(f['geometry']).length for f in drawn if f['properties'].get('d'))
            reports.append({'line': name, 'matched_sections': used, 'pending': pending,
                            'coverage': round(known / sum(g.length for g in parts), 4),
                            **({'found_as': alias} if alias else {}), **({'whole_line': True} if whole else {}),
                            **({'ends_taken_for': graph.snapped} if graph and graph.snapped else {}),
                            **({'run_to_the_end': extended} if extended else {})})
    for f in unnamed:
        for g in parts_of(f):
            output.extend(split_part(g, [], f['properties']))
    # Unknown speed remains neutral, never placed in <160 just because a tag is absent.
    for bucket in ('hsr', 'conv'):
        features = pack([f for f in output if not f['properties'].get('_shared')
                         and (f['properties']['c'] in GRADES) == (bucket == 'hsr')])
        (data / f'rail_{bucket}.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': features},
                                                             ensure_ascii=False, separators=(',', ':')))
    shared_file = data / 'rail_shared.geojson'
    shared = {'type': 'FeatureCollection', 'features': [f for f in output if f['properties'].get('_shared')]}
    for f in shared['features']:
        f['properties'].pop('_shared')
    shared['features'] = pack(shared['features'])
    shared_file.write_text(json.dumps(shared, ensure_ascii=False, separators=(',', ':')))
    by_name = defaultdict(list)
    for f in output:
        if f['properties'].get('n'):
            by_name[f['properties']['n']].append(f)
    lines_file = data / 'lines.json'
    lines = json.loads((source / 'lines.json').read_text())
    for line in lines:
        fs = by_name[line['n']]
        if not fs:
            continue
        votes = Counter()
        for f in fs:
            votes[f['properties']['c']] += shape(f['geometry']).length
        line['kind'] = line.get('kind') or ('fast' if line['c'].startswith('hsr') else 'conv')
        line['c'] = votes.most_common(1)[0][0]
        line['grades'] = [g for g in GRADES if votes[g]]
        line['design'] = sorted({f['properties']['d'] for f in fs if f['properties'].get('d')})
        # plain: the share drawn as conventional; est: the share whose band comes from the track's
        # speed tags and not from a documented design value
        total = sum(votes.values())
        line['plain'] = round(sum(v for g, v in votes.items() if g not in GRADES) / total, 4)
        line['est'] = round(sum(shape(f['geometry']).length for f in fs if f['properties'].get('e')) / total, 4)
        for old in ('s', 'unverified', 'has_unverified'):
            line.pop(old, None)
    lines_file.write_text(json.dumps(lines, ensure_ascii=False, separators=(',', ':')))
    KM = 111.0
    estimated = defaultdict(float)
    for f in output:
        if f['properties'].get('e'):
            estimated[(f['properties'].get('n') or '', f['properties']['c'])] += shape(f['geometry']).length * KM
    known_km = sum(shape(f['geometry']).length for f in output if f['properties'].get('d')) * KM
    plain_km = sum(shape(f['geometry']).length for f in output if f['properties']['c'] not in GRADES) * KM
    print(f"design speed: {known_km:.0f} km documented, {sum(estimated.values()):.0f} km of fast line by the track's "
          f"speed tags (to verify), {plain_km:.0f} km conventional", flush=True)
    report = {'source': catalog['source'], 'retrieved': catalog['retrieved'], 'basis': catalog['basis'],
              'documented_km': round(known_km), 'estimated_km': round(sum(estimated.values())), 'conventional_km': round(plain_km),
              'to_verify': [{'line': n, 'band': LABELS[c], 'km': round(v, 1)} for (n, c), v in sorted(estimated.items(), key=lambda kv: -kv[1])],
              'catalog_pages': len(catalog['pages']), 'catalog_sections': sum(len(p['sections']) for p in catalog['pages']),
              'lines_with_references': len(reports), 'matched_sections': sum(len(r['matched_sections']) for r in reports),
              'classes': dict(Counter(f['properties']['c'] for f in output)), 'lines': reports}
    out = root / 'output/design'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'coverage.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('design speed sections:', report['matched_sections'], 'on', len(reports), 'lines;', report['classes'], flush=True)
    return report


if __name__ == '__main__':
    apply()
