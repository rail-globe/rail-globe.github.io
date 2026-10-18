"""Direction-aware junction endpoint profiles shared by every build entry."""
import math
from shapely.geometry import LineString

def offset_profiles(edges, order, drawings):
    """Shared junction port ranks become explicit per-edge offset profiles.

    All members of an edge use the same fractional ramp extent. The browser
    consumes op rather than independently choosing a ramp for each line.
    """
    ports = {}
    for node, i, j, pairs in order.active_locks:
        ref, other = (i, j) if (len(order.order[i]), LineString(edges[i]['co']).length) >= (len(order.order[j]), LineString(edges[j]['co']).length) else (j, i)
        ranks = order.out_pos(ref, node)
        centre = (len(ranks) - 1) / 2
        lines = {line for pair in pairs for line in pair}
        for line in lines:
            value = ranks[line] - centre
            for index, outward in [(ref, value), (other, -value)]:
                sign = 1 if edges[index]['u'] == node else -1
                ports[node, index, line] = outward * sign
    protected_ports = {(row[0], line) for row in order.protected for line in row[3:]}
    # At a unique continuation that cannot be ordered as a complete shared
    # family, use the source-supported centre port. Holding a nonzero seat up
    # to a tight junction can create an offset loop even with correct ranks.
    # Proven physical side changes keep their free port geometry.
    for (node, i, line), j in order.next.items():
        def local_direction(index):
            edge = edges[index]
            coords = edge['co'] if edge['u'] == node else edge['co'][::-1]
            path = LineString(coords)
            point = path.interpolate(min(8, path.length * .25))
            dx, dy = point.x - coords[0][0], point.y - coords[0][1]
            length = math.hypot(dx, dy)
            return (dx / length, dy / length) if length else (0, 0)
        a, b = local_direction(i), local_direction(j)
        tight_turn = a[0] * b[0] + a[1] * b[1] > math.cos(math.radians(60))
        if ((node, i, line) not in ports and (node, line) not in protected_ports
                and order.next.get((node, j, line)) == i and tight_turn):
            ports[node, i, line] = ports[node, j, line] = 0.0
    # A source line with several incident continuations cannot supply one
    # invertible endpoint rank. Every member at that graph port converges to
    # its common centre; do not let one line's frontend branch anchor cross
    # a neighbour held at a nonzero seat.
    incident = {}
    for i, edge in enumerate(edges):
        for node in (edge['u'], edge['v']):
            counts = incident.setdefault(node, {})
            for line in edge['lines']:
                counts[line] = counts.get(line, 0) + 1
    branch_nodes = {node for node, counts in incident.items() if max(counts.values()) > 2}
    for i, edge in enumerate(edges):
        for node in (edge['u'], edge['v']):
            if node in branch_nodes:
                for line in edge['lines']:
                    if (node,line) not in protected_ports:
                        ports[node,i,line] = 0.0
    result = {}
    for i, edge in enumerate(edges):
        fraction = min(.3, 150 / max(LineString(edge['co']).length, 1))
        for k, line in enumerate(order.order[i]):
            centre = k - (len(order.order[i]) - 1) / 2
            co = drawings[i, line]
            length = LineString(co).length
            start = ports.get((edge['u'], i, line), centre)
            end = ports.get((edge['v'], i, line), centre)
            ramps = []
            if abs(start - centre) > 1e-9:
                ramps.append([0, length * fraction, start, centre])
            if abs(centre - end) > 1e-9:
                ramps.append([length * (1 - fraction), length, centre, end])
            result[i, line] = {'v': 1, 'base': start, 'ramps': ramps,
                              'origin': 0, 'direction': 1, 'period': None}
    return result


