"""Direction-aware junction endpoint profiles shared by every build entry."""
import math
from shapely.geometry import LineString

SHORT = 120.0   # metres: a stretch between two junction ports shorter than this ramps port to port
# A neck (after_neck below): two stretches within TOGETHER of each other at equal distance from the
# node for at least NECK_MIN, parting within NECK; their ways compared over PARTED after that.
TOGETHER = 2.0
NECK_MIN = 4.0
NECK = 30.0
PARTED = 15.0
# Cities whose endpoint bundles look past a neck before calling a line's way through a node a
# turn back (2026-10-22, output/junction-fix4a): pinches Karlsruhe Tullastraße 6 -> 3 lines,
# Hamburg Berliner Tor 3 -> 2, Hanover Goetheplatz gone; self-crossings as before. Only for a line
# on two stretches of the node (the tight-turn rule and a line held through a branch node): let
# through spines and branches as well, Tullastraße's S7, S8 and S51 knotted on the wye's two
# curves and Hamburg's S5 crossed its bundle (its seat is on the wrong side for the turn).
# Elsewhere every line through such a node takes the common zero port, as before.
NECK_CITIES = ("卡尔斯鲁厄", "汉堡", "汉诺威")

def offset_profiles(edges, order, drawings, keep=(), necks=False):
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
    def direction(index, node):
        edge = edges[index]
        coords = edge['co'] if edge['u'] == node else edge['co'][::-1]
        path = LineString(coords)
        point = path.interpolate(min(8, path.length * .25))
        dx, dy = point.x - coords[0][0], point.y - coords[0][1]
        length = math.hypot(dx, dy)
        return (dx / length, dy / length) if length else (0, 0)

    def reverses(i, j, node, through=False):
        # within 60 degrees 8 m out, or over the stretches' first 30 m (order.angle)
        if necks and through:
            parted = after_neck(i, j, node)
            if parted is not None:
                return parted
        a, b = direction(i, node), direction(j, node)
        far = abs(math.remainder(order.angle[node, i] - order.angle[node, j], 2 * math.pi))
        return a[0] * b[0] + a[1] * b[1] > math.cos(math.radians(60)) or far < math.radians(60)

    def after_neck(i, j, node):
        """Two stretches that leave the node along one short neck and then part: whether they still
        run within 60 degrees of each other over PARTED metres after parting (None: no neck).
        close_short joins a junction a few metres off a street to the node on it, and the stretches
        of both then start along the same street (Karlsruhe Tullastraße, Hamburg Berliner Tor,
        Hanover Goetheplatz; 2026-10-22). Measured at the node, every line through such a junction
        seemed to turn back on itself and was given the common zero port. Two stretches parting at
        an angle from the node itself (Karlsruhe Marktplatz, Durlacher Tor, Entenfang) have no neck."""
        paths = []
        for index in (i, j):
            edge = edges[index]
            paths.append(LineString(edge['co'] if edge['u'] == node else edge['co'][::-1]))
        reach = min(p.length for p in paths)
        s = 1.0
        while s <= min(NECK, reach) and paths[0].interpolate(s).distance(paths[1].interpolate(s)) <= TOGETHER:
            s += 1.0
        if s < NECK_MIN or s > NECK or s + PARTED / 3 > reach:
            return None
        ways = []
        for p in paths:
            a, b = p.interpolate(s), p.interpolate(min(s + PARTED, reach))
            length = math.hypot(b.x - a.x, b.y - a.y) or 1
            ways.append(((b.x - a.x) / length, (b.y - a.y) / length))
        return ways[0][0] * ways[1][0] + ways[0][1] * ways[1][1] > math.cos(math.radians(60))

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
        if necks and tight_turn and i != j:
            parted = after_neck(i, j, node)
            tight_turn = tight_turn if parted is None else parted
        if ((node, i, line) not in ports and (node, line) not in protected_ports
                and order.next.get((node, j, line)) == i and tight_turn):
            ports[node, i, line] = ports[node, j, line] = 0.0
    # Junctions where one source line meets three or more of its own stretches
    # (a branch, a loop or merged variants of one line). Until 2026-10-22 every
    # line at such a node converged on the node (an hourglass: Innsbruck
    # Bürgerstraße, Halle Marktplatz, Munich Karlsplatz). Now every line keeps
    # the port its own source continuation gives it. The branching line runs
    # on through the node along a spine, its pair of stretches with the most
    # source votes between them (then the straightest), holding the seat of
    # the wider of the two; each other stretch of it is a branch leaving the
    # spine where its votes go, from the same seat. The page chains the spine
    # through the node and starts a branch on the spine's offset (jn, below).
    # A line the source gives no continuation at all at the node keeps the
    # common zero-offset port, as does a line with a loop stretch there and a
    # line turning back on itself through the node (two of its stretches
    # leaving within 60 degrees, as the tight-turn rule above); a line that
    # ends at the node ends at its own seat.
    incident = {}
    for i, edge in enumerate(edges):
        for node in (edge['u'], edge['v']):
            counts = incident.setdefault(node, {})
            for line in edge['lines']:
                counts[line] = counts.get(line, 0) + 1
    branch_nodes = {node for node, counts in incident.items() if max(counts.values()) > 2}
    # The ports as before 2026-10-22 (every line at a branch node on the common
    # centre) stay the profile below z13 (op.lo): there the seats are a few
    # pixels apart and a held seat folds round the junction's short corners.
    old_ports = dict(ports)
    for i, edge in enumerate(edges):
        for node in (edge['u'], edge['v']):
            if node in branch_nodes:
                for line in edge['lines']:
                    if (node, line) not in protected_ports:
                        old_ports[node, i, line] = 0.0
    width = lambda i: (len(order.order[i]), LineString(edges[i]['co']).length, -i)
    sign = lambda i, node: 1 if edges[i]['u'] == node else -1

    def seat_out(i, node, line):
        """The line's port at node on stretch i, seen outward from the node."""
        ranks = order.out_pos(i, node)
        value = ports.get((node, i, line))
        return value * sign(i, node) if value is not None else ranks[line] - (len(ranks) - 1) / 2

    def hold(i, j, node, line):
        """Stretch j takes the line's port on stretch i, on the same side of the line's way through."""
        if (node, j, line) not in ports:
            ports[node, j, line] = -seat_out(i, node, line) * sign(j, node)

    joins = {}
    for node in sorted(branch_nodes):
        if node in keep:            # a hand-verified bend case keeps its earlier ports
            for i in order.at[node]:
                for line in edges[i]['lines']:
                    if (node, line) not in protected_ports:
                        ports[node, i, line] = 0.0
            continue
        for line in sorted(incident[node]):
            if (node, line) in protected_ports:
                continue
            mine = [i for i in order.at[node] if line in edges[i]['lines']]
            votes = lambda i, j: (order.connections.get((node, i, line), {}).get(j, 0)
                                  + order.connections.get((node, j, line), {}).get(i, 0))
            known = any(order.connections.get((node, i, line)) for i in mine)
            loop = any(edges[i]['u'] == edges[i]['v'] for i in mine)
            if incident[node][line] == 1:
                continue            # the line ends here: it ends at its own seat
            if not known or (incident[node][line] > 2 and loop):
                for i in mine:
                    ports[node, i, line] = 0.0
                continue
            if incident[node][line] == 2:
                # a line going through a branch node: one port on both sides;
                # where it turns back on itself there, the common zero port
                if len(mine) == 2 and reverses(*mine, node, through=True):
                    for i in mine:
                        ports[node, i, line] = 0.0
                elif len(mine) == 2 and votes(*mine):
                    a, c = sorted(mine, key=width, reverse=True)
                    hold(a, c, node, line)
                    joins[node, a, line] = joins[node, c, line] = ('h', None)
                continue
            straight = lambda i, j: abs(math.remainder(order.angle[node, i] - order.angle[node, j], 2 * math.pi))
            a, c = max(((i, j) for i in mine for j in mine if i < j),
                       key=lambda pair: (votes(*pair), straight(*pair), max(width(pair[0]), width(pair[1]))))
            a, c = sorted((a, c), key=width, reverse=True)
            trunks = {b: max((a, c), key=lambda t: (votes(b, t), straight(b, t))) for b in mine if b not in (a, c)}
            if reverses(a, c, node) or any(reverses(b, t, node) for b, t in trunks.items()):
                # the line turns back on itself here: all its parts meet at the node
                for i in mine:
                    ports[node, i, line] = 0.0
                continue
            hold(a, c, node, line)
            joins[node, a, line] = ('s', c)
            joins[node, c, line] = ('s', a)
            for b, trunk in trunks.items():
                hold(trunk, b, node, line)
                joins[node, b, line] = ('t', trunk)

    def away(i, line, node):
        """The first point of the line's drawing on stretch i that is not the node, as written."""
        co = drawings[i, line] if edges[i]['u'] == node else drawings[i, line][::-1]
        return next((list(p) for p in co[1:] if tuple(p) != tuple(co[0])), list(co[-1]))
    def profile_of(i, edge, k, line, ports, short):
        fraction = min(.3, 150 / max(LineString(edge['co']).length, 1))
        centre = k - (len(order.order[i]) - 1) / 2
        length = LineString(drawings[i, line]).length
        start = ports.get((edge['u'], i, line), centre)
        end = ports.get((edge['v'], i, line), centre)
        ramps = []
        if (short and (edge['u'], i, line) in ports and (edge['v'], i, line) in ports
                and (edge['u'] in branch_nodes or edge['v'] in branch_nodes)
                and LineString(edge['co']).length < SHORT and edge['u'] != edge['v']):
            # a short stretch at a branch node carries the line from one port to
            # the next in one ramp, not out to its seat and back
            if abs(start - end) > 1e-9:
                ramps.append([0, length, start, end])
        else:
            if abs(start - centre) > 1e-9:
                ramps.append([0, length * fraction, start, centre])
            if abs(centre - end) > 1e-9:
                ramps.append([length * (1 - fraction), length, centre, end])
        return {'v': 1, 'base': start, 'ramps': ramps, 'origin': 0, 'direction': 1, 'period': None}

    result = {}
    for i, edge in enumerate(edges):
        for k, line in enumerate(order.order[i]):
            profile = profile_of(i, edge, k, line, ports, True)
            ends = [joins.get((node, i, line)) for node in (edge['u'], edge['v'])]
            if any(ends) and edge['u'] != edge['v']:
                # jn: for each end at such a node, the spine partner ('s') or the trunk a branch
                # leaves ('t'), named by that stretch's first drawn point away from the node, or
                # 'h': 1 for a line held through the node on one port
                profile['jn'] = [None if e is None else {e[0]: 1 if e[1] is None else away(e[1], line, node)}
                                 for e, node in zip(ends, (edge['u'], edge['v']))]
            low = profile_of(i, edge, k, line, old_ports, False)
            if any(low[key] != profile[key] for key in ('base', 'ramps')):
                profile['lo'] = low
            result[i, line] = profile
    return result
