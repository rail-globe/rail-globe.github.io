"""Source-backed endpoint ranks in the ordinary urban bundle pipeline.

Inspired by the statically verified conditional VectorKit endpoint-index sort.
Reference choice, graph matching and bounded curves are independent policies.
"""
from collections import Counter, defaultdict
import json
import math
from shapely.geometry import LineString
from shapely.ops import unary_union
import line_bundles as lb
from endpoint_order import EndpointOrder, canonical_features, geographic_groups, line_key, source_turns
from endpoint_profiles import offset_profiles


def raw_geometries(source, keys, projection):
    out = {}
    for key in keys:
        chunks = [chunk for route in source.get(key, {}).get('routes', []) for chunk in route.get('chunks', [])]
        paths = [LineString([projection(*p) for p in chunk]) for chunk in chunks if len(chunk) >= 2]
        if paths:
            out[key] = unary_union(paths)
    return out


def common_towards(own, reference, end, reach=80.0, step=2.0):
    """A line's course on a stretch (metres, the stretch's direction): the common reference course
    at the given end (0: start, -1: finish), easing to the line's own course within reach metres
    (at most 0.8 of the stretch), its own course unchanged beyond. Points are matched by their
    share of each course's length; both courses run along the same stretch."""
    own_line, ref_line = LineString(own), LineString(reference)
    length = own_line.length
    span = min(reach, .8 * length)
    if span <= 0 or ref_line.length <= 0:
        return list(reference)
    distances = [0.0]
    for a, b in zip(own, own[1:]):
        distances.append(distances[-1] + math.dist(a, b))
    near = (lambda s: s) if end == 0 else (lambda s: length - s)
    values = {s for s in distances if near(s) >= span}
    values.update(s for s in distances if near(s) < span)
    values.update((k * step if end == 0 else length - k * step) for k in range(math.ceil(span / step) + 1)
                  if k * step <= span)
    result = []
    for s in sorted(values):
        t = max(0.0, 1 - near(s) / span)
        w = t * t * t * (10 + t * (-15 + 6 * t))
        p = own_line.interpolate(s)
        if w <= 0:
            result.append((p.x, p.y))
            continue
        q = ref_line.interpolate(s / length * ref_line.length)
        result.append((p.x + w * (q.x - p.x), p.y + w * (q.y - p.y)))
    result[0 if end == 0 else -1] = tuple(reference[end])
    result[-1 if end == 0 else 0] = tuple(own[-1 if end == 0 else 0])
    return result


def shared_centres(edges, drawings, graph):
    """A branch family has one centre port, including degree-two members.

    Individual course smoothing otherwise moves a through line away from the
    fixed centre of its branching neighbour. Fit a bounded translation over
    80 m, keeping the rest of each source course and all true ends unchanged.
    The common course holds only towards the branching end: towards an end
    where no line branches, each line eases back to its own smoothed course
    (common_towards), so it still meets its own next stretch there, smoothed.
    Taking the common course to that end too turned every other line there in
    a corner, pulled to the graph node (2026-10-18: Basel Bankverein, Hamburg
    Hbf and Berliner Tor, Bochum; offset lines folded into small loops at z16).
    """
    at = defaultdict(list)
    counts = defaultdict(Counter)
    for (i, key), co in drawings.items():
        for end, node in ((0, edges[i]['u']), (-1, edges[i]['v'])):
            at[node].append((i, key, end, co[end]))
            counts[node][key] += 1
    path_changes = []
    common = dict(drawings)
    for i, edge in enumerate(edges):
        if len(edge['lines']) < 2 or not any(max(counts[n].values()) > 2 for n in (edge['u'],edge['v'])):
            continue
        # A continuous through course avoids the artificial end turnback
        # produced by reflecting a snapped branch endpoint. Share that centre
        # course, then fit all incompatible ports back to the graph node.
        key = min(edge['lines'],key=lambda k:(-sum(counts[n][k]==2 for n in (edge['u'],edge['v'])),k))
        reference = drawings[i,key]
        displacement = max(LineString(reference).hausdorff_distance(LineString(drawings[i,k])) for k in edge['lines'])
        if not math.isfinite(displacement):
            raise ValueError('non-finite common branch centre displacement')
        if displacement > 10:
            raise ValueError('common branch centre exceeds bounded 10 m fit')
        if displacement > 1e-6:
            path_changes.append({'edge':i,'reference_source':key,'max_centre_displacement_m':displacement})
        branching = [end for end, n in ((0, edge['u']), (-1, edge['v'])) if max(counts[n].values()) > 2]
        for k in edge['lines']:
            common[i,k] = reference if len(branching) == 2 else common_towards(drawings[i,k], reference, branching[0])
    # Rebuild ports after choosing each shared edge centre. Any moved terminal
    # or incompatible adjacent course converges to the existing graph node.
    # Only branching nodes: elsewhere every line keeps its own smoothed port.
    at = defaultdict(list)
    for (i,key),co in common.items():
        for end,node in ((0,edges[i]['u']),(-1,edges[i]['v'])):
            at[node].append((i,key,end,co[end]))
    drawings = common
    targets, changes = {}, []
    for node, ports in at.items():
        if max(counts[node].values()) <= 2:
            continue
        gap = max((math.dist(a[3], b[3]) for a in ports for b in ports), default=0)
        target = graph.node[node]
        terminal_shift = max((math.dist(p[3],target) for p in ports),default=0) if any(counts[node][p[1]]==1 for p in ports) else 0
        if max(gap,terminal_shift) <= 1e-6:
            continue
        targets[node] = target
        changes.append({'node': node, 'max_port_gap_before_m': gap,
                        'max_translation_m': max(math.dist(p[3], target) for p in ports)})
    out = {}
    for (i, key), co in drawings.items():
        edge = edges[i]
        curve = LineString(co)
        shifts = []
        for end, node in ((0, edge['u']), (-1, edge['v'])):
            if node in targets:
                shifts.append((end, (targets[node][0]-co[end][0], targets[node][1]-co[end][1])))
        if not shifts:
            out[i, key] = co
            continue
        distances = [0.0]
        for a, b in zip(co, co[1:]):
            distances.append(distances[-1] + math.dist(a, b))
        # Fine points only in the bounded translation windows.
        values = set(distances)
        for end, _ in shifts:
            span = min(80, curve.length * .4)
            values.update((min(span,k*2) if end==0 else curve.length-min(span,k*2))
                          for k in range(math.ceil(span/2)+1))
        result = []
        for s in sorted(values):
            p = curve.interpolate(s)
            x, y = p.x, p.y
            for end, (dx, dy) in shifts:
                span = min(80, curve.length * .4)
                t = max(0, 1-(s if end==0 else curve.length-s)/max(span,1e-9))
                w = t*t*t*(10+t*(-15+6*t))
                x += w*dx; y += w*dy
            result.append((x,y))
        out[i,key] = result
    return out, {'ports':changes, 'shared_paths':path_changes}


def curve_nodes(code, graph, projection, properties):
    # Two visually verified, source-bound bend cases. Match geographic ports,
    # never graph numbering, which changes when the source graph is rebuilt.
    if code != 'de':
        return {}
    cases = [(9.181899526,48.782783915,None), (9.186464399,48.782207741,'U11:')]
    result = {}
    for lon, lat, prefix in cases:
        point = projection(lon,lat)
        near = min(graph.node, key=lambda n: math.dist(graph.node[n], point))
        if math.dist(graph.node[near], point) > 15:
            continue
        selected = None if prefix is None else {key for key in properties if key.split('|')[1].startswith(prefix)}
        if selected is None or len(selected)==1:
            result[near] = selected
    return result


def apply_endpoint(features, code, source, audit=None, context_sink=None):
    source = dict(source)
    canonical, identity_audit = canonical_features(features, source)
    output = []
    for index, mine in enumerate(geographic_groups(canonical)):
        pts = [p for f in mine for co in lb.parts_of(f) for p in co]
        proj = lb.Projection(sum(p[0] for p in pts)/len(pts), sum(p[1] for p in pts)/len(pts))
        paths, properties = [], {}
        for f in mine:
            key = line_key(f['properties'])
            properties[key] = {k:v for k,v in f['properties'].items() if k not in lb.DROP and k not in ('jc','cl')}
            paths.extend(([proj(*p) for p in co],frozenset([key])) for co in lb.parts_of(f))
        stubs = all(f['properties'].get('ct') in lb.BRANCH_STUB_CITIES for f in mine)
        graph = lb.build(paths, source_bound=True, branch_stubs=stubs)
        edges = lb.contract(graph)
        if not edges:
            raise ValueError('empty endpoint bundle graph')
        baseline = lb.Order(graph, edges)
        rounds = min(60000,max(4000,400*sum(len(row)>1 for row in baseline.order)))
        legacy_cost = baseline.anneal(rounds=rounds)
        votes, mapping = source_turns(edges, source, proj)
        order = EndpointOrder(graph, edges, votes, raw_geometries(source, properties, proj), initial=baseline.order)
        before = order.inversions(order.locks)
        source_cost = order.total()
        cost = order.anneal(rounds=rounds)
        stretch = []
        for edge in edges:
            inner = list(LineString(edge['co']).simplify(lb.SIMPLIFY).coords)
            stretch.append([graph.node[edge['u']]]+inner[1:-1]+[graph.node[edge['v']]])
        selected = curve_nodes(code,graph,proj,properties)
        if selected:
            from bend_curves import smooth_lines
            drawings = smooth_lines(edges,stretch,order,selected)
        else:
            drawings = lb.smooth_lines(edges,stretch,order)
        drawings, centre_changes = shared_centres(edges,drawings,graph)
        rendered = {key:[[round(v,9) for v in proj.back(*p)] for p in co] for key,co in drawings.items()}
        profiles = offset_profiles(edges,order,rendered,keep=frozenset(selected))
        for i,edge in enumerate(edges):
            for k,key in enumerate(order.order[i]):
                co = rendered[i,key]
                shape = LineString(co)
                props = dict(properties[key])
                props.update(jc=1,cl=int(shape.is_simple and not shape.is_ring),off=k-(len(order.order[i])-1)/2,
                             bn=len(order.order[i]),op=json.dumps(profiles[i,key],separators=(',',':')))
                output.append({'type':'Feature','properties':props,'geometry':{'type':'LineString','coordinates':co}})
        report = {'index':index,'line_count':len(properties),'edges':len(edges),'legacy_cost':legacy_cost,
                  'source_cost_before':source_cost,'source_cost_after':cost,'endpoint_inversions_before':before,
                  'endpoint_inversions_after':order.inversions(),'locks':len(order.active_locks),
                  'locked_pairs':sum(len(row[3]) for row in order.active_locks),
                  'protected_source_crossings':order.protected,'unknown_source_pairs':order.unknown_source_pairs,
                  'parity_conflicts':order.parity_conflicts,'mapping':mapping,'connections':order.connection_audit,
                  'shared_centre_changes':centre_changes['ports'],'shared_path_changes':centre_changes['shared_paths'],'curve_nodes':sorted(selected),'identity_audit':identity_audit,
                  'graph_source_audit':graph.source_audit,'orders_before':baseline.order,'orders_after':order.order,
                  'node_positions':{str(v):list(proj.back(*graph.node[v])) for v in order.at},
                  'edges_geometry':[[list(proj.back(*p)) for p in edge['co']] for edge in edges]}
        if audit is not None:
            audit.append(report)
        if context_sink is not None:
            context_sink(index,{'graph':graph,'edges':edges,'order':order,'drawings':drawings,
                                'properties':properties,'projection':proj})
        print(f"{code} endpoint bundle: {len(properties)} lines, {len(edges)} stretches, "
              f"{report['locked_pairs']} pair constraints, {before} -> {order.inversions()} inversions",flush=True)
    return output
