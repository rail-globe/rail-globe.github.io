"""Source-backed junction connections and monotone endpoint ordering for a local pilot.

This is an independent implementation of an endpoint-order invariant. It does
not call VectorKit. Physical crossings and unresolved branch ports are audited.
"""
import itertools
import math
import random
from collections import Counter, defaultdict

from shapely import STRtree
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

import line_bundles as lb


def line_key(props):
    return f"{props.get('network', '')}|{props['n']}|{props.get('rid', '')}"


def geographic_groups(features):
    """Only actual near geometries connect groups; city names do not cut them."""
    if not features:
        return []
    geometries = [unary_union([LineString(co) for co in lb.parts_of(f)]) for f in features]
    parent = list(range(len(features)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    tree = STRtree(geometries)
    ii, jj = tree.query(geometries, predicate='dwithin', distance=0.0003)
    for i, j in zip(ii, jj):
        if i != j:
            parent[root(int(i))] = root(int(j))
    groups = defaultdict(list)
    for i, f in enumerate(features):
        groups[root(i)].append(f)
    return list(groups.values())


def source_turns(edges, traversals, projection):
    """Vote only from consecutive source-path samples near an actual graph node.

    Disconnected OSM member chunks remain disconnected. A graph match is local,
    line-specific, and within 80 m to allow the existing snapped/cropped nodes.
    Mapping breaks never create a continuation across a nonadjacent graph edge.
    """
    by_line = defaultdict(list)
    for i, e in enumerate(edges):
        for line in e['lines']:
            by_line[line].append(i)
    votes = defaultdict(Counter)
    report = {'matched_source_transitions': 0, 'nonadjacent_mapping_breaks': 0,
              'unmatched_samples': 0, 'ambiguous_samples': 0, 'source_chunks': 0, 'max_match_distance_m': 80}
    for line, ids in by_line.items():
        geoms = [LineString(edges[i]['co']) for i in ids]
        tree = STRtree(geoms)
        for route in traversals.get(line, {}).get('routes', []):
            for chunk in route['chunks']:
                report['source_chunks'] += 1
                co = [projection(*point) for point in chunk]
                if len(co) < 2:
                    continue
                previous = None
                ambiguous_run = 0
                seen = set()
                for point in lb.samples(co, step=10):
                    p = Point(point)
                    candidates = tree.query(p, predicate='dwithin', distance=80)
                    if not len(candidates):
                        previous = None
                        report['unmatched_samples'] += 1
                        continue
                    ranked = sorted((geoms[int(j)].distance(p), ids[int(j)]) for j in candidates)
                    if len(ranked) > 1 and ranked[1][0] - ranked[0][0] <= .25:
                        report['ambiguous_samples'] += 1
                        ambiguous_run += 10
                        if ambiguous_run > 30:
                            previous = None
                        continue
                    ambiguous_run = 0
                    distance, current = ranked[0]
                    if previous is not None and previous != current:
                        shared = {edges[previous]['u'], edges[previous]['v']} & {edges[current]['u'], edges[current]['v']}
                        if len(shared) == 1:
                            node = next(iter(shared))
                            before = edges[previous]['co'][0 if edges[previous]['u'] == node else -1]
                            after = edges[current]['co'][0 if edges[current]['u'] == node else -1]
                            event = node, min(previous, current), max(previous, current)
                            if max(math.dist(point, before), math.dist(point, after)) <= 110 and event not in seen:
                                votes[node, previous, line][current] += 1
                                votes[node, current, line][previous] += 1
                                report['matched_source_transitions'] += 1
                                seen.add(event)
                        else:
                            report['nonadjacent_mapping_breaks'] += 1
                    previous = current
    return votes, report


class EndpointOrder(lb.Order):
    def __init__(self, graph, edges, votes, source_geometries=None, initial=None):
        super().__init__(graph, edges)
        old = self.next.copy()
        self.connections = {}
        self.connection_audit = {'changed_straightest_guesses': [], 'ambiguous_source_ports': [],
                                 'unresolved_ports': [], 'unique_topology_ports': 0, 'source_ports': 0}
        for node, incident in self.at.items():
            for i in incident:
                for line in edges[i]['lines']:
                    candidates = [j for j in incident if j != i and line in edges[j]['lines']]
                    if not candidates:
                        continue
                    proved = Counter({j: count for j, count in votes.get((node, i, line), {}).items()
                                      if j in candidates})
                    if proved:
                        self.connections[node, i, line] = proved
                        self.connection_audit['source_ports'] += 1
                        if len(proved) > 1:
                            self.connection_audit['ambiguous_source_ports'].append([node, i, line, sorted(proved)])
                        if old.get((node, i, line)) not in proved:
                            self.connection_audit['changed_straightest_guesses'].append(
                                [node, i, line, old.get((node, i, line)), sorted(proved)])
                    else:
                        self.connection_audit['unresolved_ports'].append([node, i, line, candidates])
        self.next = {key: next(iter(options)) for key, options in self.connections.items() if len(options) == 1}
        if initial is not None:
            self.order = [list(row) for row in initial]
        self.locks = []
        self.protected = []
        self.unknown_source_pairs = []
        self.source_geometries = source_geometries or {}
        for node, incident in self.at.items():
            for i, j in itertools.combinations(incident, 2):
                common = sorted(set(edges[i]['lines']) & set(edges[j]['lines']))
                unique = [line for line in common if self.next.get((node, i, line)) == j
                          and self.next.get((node, j, line)) == i]
                pairs = []
                for a, b in itertools.combinations(unique, 2):
                    status = self.physical_crossing(node, i, j, a, b)
                    if status is True:
                        self.protected.append([node, i, j, a, b])
                    elif status is False:
                        pairs.append((a, b))
                    else:
                        self.unknown_source_pairs.append([node, i, j, a, b])
                if pairs:
                    self.locks.append((node, i, j, pairs))
        self.active_locks = []
        self.components = {}
        self.parity_conflicts = []

    def physical_crossing(self, node, i, j, a, b):
        """True: source side swap, False: stable source family, None: unknown.

        Nearby display lines alone do not prove a shared physical track. Exact
        raw source overlap or a measurable stable side relationship is required.
        """
        if a not in self.source_geometries or b not in self.source_geometries:
            return None
        values, overlaps = [], []
        ga, gb = self.source_geometries[a], self.source_geometries[b]
        for edge_index in (i, j):
            edge = self.edges[edge_index]
            coords = edge['co'] if edge['u'] == node else edge['co'][::-1]
            path = LineString(coords)
            t = min(60, path.length * .65)
            p = path.interpolate(t)
            q = path.interpolate(min(path.length, t + 5))
            ux, uy = q.x - p.x, q.y - p.y
            norm = math.hypot(ux, uy)
            if norm < 1e-9 or max(ga.distance(p), gb.distance(p)) > 80:
                return None
            points = []
            for geom in (ga, gb):
                pieces = [geom] if geom.geom_type == 'LineString' else list(geom.geoms)
                local = min(pieces, key=lambda g: g.distance(p))
                points.append(local.interpolate(local.project(p)))
            values.append(-(ux * (points[1].y - points[0].y) - uy * (points[1].x - points[0].x)) / norm)
            # This proves identical represented source geometry locally, not
            # ownership or track semantics absent from the supplied extract.
            overlaps.append(ga.intersection(gb).intersection(p.buffer(25)).length >= 10)
        if min(map(abs, values)) >= 2.0:
            return values[0] * values[1] > 0
        if all(overlaps):
            return False
        return None

    def node_cost(self, node):
        cost = 0.0
        positions = {i: self.out_pos(i, node) for i in self.at[node]}
        for i in self.at[node]:
            for a, b in itertools.combinations(self.order[i], 2):
                aa = self.connections.get((node, i, a), {})
                bb = self.connections.get((node, i, b), {})
                if not aa or not bb:
                    continue
                left = positions[i][a] < positions[i][b]
                total = sum(aa.values()) * sum(bb.values())
                for fa, ca in aa.items():
                    for fb, cb in bb.items():
                        local = 0.0
                        if fa == fb:
                            if left == (positions[fa][a] < positions[fa][b]):
                                local = lb.CROSS
                            elif abs(positions[i][a] - positions[i][b]) == 1 and abs(positions[fa][a] - positions[fa][b]) != 1:
                                local = lb.SPLIT
                        else:
                            base = self.angle[node, i]
                            ccw = lambda k: (self.angle[node, k] - base) % (2 * math.pi)
                            if (ccw(fa) > ccw(fb)) == left:
                                local = lb.CROSS
                        cost += local * ca * cb / total
        return cost / 2

    def inversions(self, locks=None):
        count = 0
        for node, i, j, pairs in self.active_locks if locks is None else locks:
            a, b = self.out_pos(i, node), self.out_pos(j, node)
            count += sum((a[x] < a[y]) == (b[x] < b[y]) for x, y in pairs)
        return count

    def seed_endpoints(self):
        """Map each shared pair monotonically, with direction-aware port ranks.

        A direction frame belongs to a line pair, not a whole edge. Disjoint
        families meeting at three ports can form an odd edge cycle while every
        pair constraint is feasible. Solve pair frames, then their precedence
        orders jointly, preserving the reference order wherever possible.
        """
        self.active_locks, self.components, self.parity_conflicts = [], {}, []
        self.pair_components = {}
        self.locked_pairs_by_edge = defaultdict(set)
        pair_graph = defaultdict(lambda: defaultdict(list))
        for node, i, j, pairs in self.locks:
            si = 1 if self.edges[i]['u'] == node else -1
            sj = 1 if self.edges[j]['u'] == node else -1
            for pair in pairs:
                pair_graph[pair][i].append((j, -si * sj))
                pair_graph[pair][j].append((i, -si * sj))
        # A coherent whole-family frame is a reference preference only.
        # It must never discard the pair constraints of a feasible odd cycle.
        frame = defaultdict(list)
        for node, i, j, _ in self.locks:
            sign = -(1 if self.edges[i]['u']==node else -1)*(1 if self.edges[j]['u']==node else -1)
            frame[i].append((j,sign)); frame[j].append((i,sign))
        reference_rows = [list(row) for row in self.order]
        visited = set()
        for root in sorted(frame,key=lambda i:(-LineString(self.edges[i]['co']).length,i)):
            if root in visited: continue
            direction = 1 if tuple(self.edges[root]['co'][0]) < tuple(self.edges[root]['co'][-1]) else -1
            signs, stack, conflict = {root:direction},[root],False
            while stack:
                i=stack.pop()
                for j,sign in frame[i]:
                    expected=signs[i]*sign
                    if j in signs and signs[j]!=expected: conflict=True
                    elif j not in signs: signs[j]=expected;stack.append(j)
            visited.update(signs)
            if conflict: continue
            row=self.order[root] if direction>0 else self.order[root][::-1]
            names=set().union(*(set(self.order[i]) for i in signs))
            ranks={name:k for k,name in enumerate(row+sorted(names-set(row)))}
            for i,sign in signs.items():
                reference_rows[i]=sorted(self.order[i],key=ranks.__getitem__,reverse=sign<0)
        variables, excluded = [], set()
        for pair, adjacency in sorted(pair_graph.items()):
            visited = set()
            for root in sorted(adjacency, key=lambda i: (-LineString(self.edges[i]['co']).length, i)):
                if root in visited:
                    continue
                parity, stack, conflict = {root: 1}, [root], False
                while stack:
                    i = stack.pop()
                    for j, sign in adjacency[i]:
                        expected = parity[i] * sign
                        if j in parity and parity[j] != expected:
                            conflict = True
                        elif j not in parity:
                            parity[j] = expected
                            stack.append(j)
                visited.update(parity)
                if conflict:
                    self.parity_conflicts.append({'pair': list(pair), 'edges': sorted(parity)})
                    excluded.update((i, pair) for i in parity)
                else:
                    preferred = reference_rows[root].index(pair[0]) < reference_rows[root].index(pair[1])
                    variables.append((pair, parity, preferred))
                    for i in parity:
                        self.pair_components[i, pair] = tuple(sorted(parity))
        variables.sort(key=lambda item: (-len(item[1]), item[0], min(item[1])))
        precedence = [defaultdict(set) for _ in self.edges]
        def sorted_row(i):
            row = self.order[i]
            degrees = dict.fromkeys(row, 0)
            for targets in precedence[i].values():
                for target in targets:
                    degrees[target] += 1
            result = []
            ready = [name for name in row if degrees[name] == 0]
            while ready:
                name = min(ready, key=row.index)
                ready.remove(name)
                result.append(name)
                for target in precedence[i][name]:
                    degrees[target] -= 1
                    if degrees[target] == 0:
                        ready.append(target)
            return result if len(result) == len(row) else None
        attempts = 0
        def solve(k):
            nonlocal attempts
            if k == len(variables):
                return True
            if attempts >= 20000:
                return False
            pair, parity, preferred = variables[k]
            for choice in (preferred, not preferred):
                attempts += 1
                added = []
                for i, sign in parity.items():
                    left, right = pair if choice == (sign > 0) else pair[::-1]
                    precedence[i][left].add(right)
                    added.append((i, left, right))
                if all(sorted_row(i) is not None for i in parity) and solve(k + 1):
                    return True
                for i, left, right in added:
                    precedence[i][left].remove(right)
            return False
        if not solve(0):
            raise ValueError('Endpoint precedence constraints unresolved within bounded search; no candidate written')
        self.seed_search_attempts = attempts
        for i in range(len(self.edges)):
            self.order[i] = sorted_row(i)
        for node, i, j, pairs in self.locks:
            feasible = [pair for pair in pairs if (i, pair) not in excluded and (j, pair) not in excluded]
            if feasible:
                self.active_locks.append((node, i, j, feasible))
                self.locked_pairs_by_edge[i].update(feasible)
                self.locked_pairs_by_edge[j].update(feasible)
        adjacency = defaultdict(set)
        for _, i, j, _ in self.active_locks:
            adjacency[i].add(j); adjacency[j].add(i)
        for root in adjacency:
            if root in self.components:
                continue
            component, stack = {root}, [root]
            while stack:
                for j in adjacency[stack.pop()]:
                    if j not in component:
                        component.add(j); stack.append(j)
            for i in component:
                self.components[i] = tuple(sorted(component))
        assert self.inversions() == 0

    def anneal(self, rounds=20000, seed=1):
        self.seed_endpoints()
        rng = random.Random(seed)
        movable = [i for i, row in enumerate(self.order) if len(row) > 1]
        if not movable:
            return self.total()
        cost = best_cost = self.total()
        best = [list(row) for row in self.order]
        for iteration in range(1, rounds + 1):
            i = rng.choice(movable)
            k = rng.randrange(len(self.order[i]) - 1)
            a, b = self.order[i][k:k + 2]
            pair = tuple(sorted((a,b)))
            candidates = self.pair_components.get((i,pair),(i,)) if rng.random() < .65 else (i,)
            changed = [j for j in candidates if a in self.order[j] and b in self.order[j]]
            nodes = {v for j in changed for v in (self.edges[j]['u'], self.edges[j]['v'])}
            before = sum(self.node_cost(v) for v in nodes)
            saved = {j: list(self.order[j]) for j in changed}
            feasible = True
            for j in changed:
                row = self.order[j]
                if pair not in self.locked_pairs_by_edge[j]:
                    x,y=row.index(a),row.index(b)
                    row[x],row[y]=b,a
                    continue
                # Reverse only this source pair's connected frame. Other hard
                # comparisons remain fixed; stable topological projection can
                # move free neighbours without a non-adjacent swap violating
                # their independent constraints.
                targets=defaultdict(set);degree=dict.fromkeys(row,0)
                for left,right in self.locked_pairs_by_edge[j]:
                    if row.index(left)>row.index(right):left,right=right,left
                    if {left,right}=={a,b}:left,right=right,left
                    targets[left].add(right);degree[right]+=1
                result=[];ready=[name for name in row if degree[name]==0]
                while ready:
                    name=min(ready,key=row.index);ready.remove(name);result.append(name)
                    for other in targets[name]:
                        degree[other]-=1
                        if degree[other]==0:ready.append(other)
                if len(result)!=len(row):
                    feasible=False;break
                self.order[j]=result
            feasible = feasible and self.inversions() == 0
            delta = sum(self.node_cost(v) for v in nodes) - before if feasible else math.inf
            temperature = 1000 / iteration
            if feasible and (delta <= 0 or rng.random() < math.exp(-delta / temperature)):
                cost += delta
                if cost < best_cost - 1e-9:
                    best_cost, best = cost, [list(row) for row in self.order]
            else:
                for j, row in saved.items():
                    self.order[j] = row
        self.order = best
        assert self.inversions() == 0
        return best_cost


def canonical_features(features, source):
    """Merge relation variants only with a shared source master or relation ID.

    Names and colours alone are insufficient evidence. Geometry duplicates are
    removed before graph insertion while independent branches are retained.
    """
    names = defaultdict(list)
    for f in features:
        p = f['properties']
        names[p.get('network'), p['n'], p.get('col')].append(f)
    result, audit = [], []
    for identity, rows in names.items():
        keys = sorted({line_key(f['properties']) for f in rows})
        parent = {key: key for key in keys}

        def root(key):
            while parent[key] != key:
                parent[key] = parent[parent[key]]
                key = parent[key]
            return key

        for a, b in itertools.combinations(keys, 2):
            aa, bb = source.get(a, {}), source.get(b, {})
            if set(aa.get('masters', [])) & set(bb.get('masters', [])) or set(aa.get('rids', [])) & set(bb.get('rids', [])):
                parent[root(b)] = root(a)
        members = defaultdict(list)
        for key in keys:
            members[root(key)].append(key)
        for group in members.values():
            selected = [f for f in rows if line_key(f['properties']) in group]
            ids = sorted({rid for key in group for rid in source.get(key, {}).get('rids', [])})
            props = dict(selected[0]['properties'])
            props['rid'] = ','.join(map(str, ids)) if ids else props.get('rid', '')
            combined = line_key(props)
            if combined not in source:
                source[combined] = {'rids': ids, 'masters': [],
                                    'routes': [route for key in group for route in source.get(key, {}).get('routes', [])]}
            paths, seen = [], set()
            for f in selected:
                for co in lb.parts_of(f):
                    frozen = tuple(tuple(point) for point in co)
                    signature = min(frozen, frozen[::-1])
                    if signature not in seen:
                        seen.add(signature)
                        paths.append(co)
            result.append({'type': 'Feature', 'properties': props,
                           'geometry': {'type': 'MultiLineString', 'coordinates': paths}})
            audit.append({'identity': identity, 'source_keys': group, 'output_key': combined,
                          'input_parts': sum(len(lb.parts_of(f)) for f in selected), 'distinct_parts': len(paths)})
    return result, audit
