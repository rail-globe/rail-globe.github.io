"""Draw a line once: reduce the tracks of one line to a single track's worth of geometry.

A double line is mapped as two tracks a few metres apart. one_track() keeps one of them and
leaves the other out, while keeping everything that is not just the second track: branches,
spurs, the legs of a junction, and stretches where the two directions run on separate alignments.
join_up() then closes the gaps this opens where two lines meet (each may have kept a different
track at the junction).

Distances are in degrees (0.0001 is about 11 m north-south, 8 to 10 m east-west in China).
"""
import math
from collections import Counter

import shapely
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, substring, unary_union
from shapely.strtree import STRtree

NEAR = 0.00007      # closer than this to track already kept: the same place on the line
GAP = 0.0006        # the second track stays within this of the first, also through stations
KEEP = 0.015        # a stretch further out than GAP for longer than this is a separate alignment
APART = 0.0015      # ... and so is a shorter one that gets this far away
APART_MIN = 0.003   # ... for at least this long
ATTACH = 0.003      # a piece that leaves the kept track this soon after a junction starts at the junction
TAIL = 0.003        # how far a kept piece runs on beside the kept track before and after it swings away
MIN_FAR = 0.0003    # shorter excursions beyond GAP are noise
TOUCH = 0.00012     # two drawn pieces this close read as joined
REACH = 0.03        # how far join_up() follows a track to reach the drawn line
STEP = 0.0004


def lines_of(g):
    return [x for x in (g.geoms if hasattr(g, "geoms") else [g]) if x.geom_type == "LineString" and x.length > 0]


def spans(p, pieces):
    """Where pieces cut out of the run p lie along it, as [from, to] distances, joined where they touch.

    Cutting a run that crosses or closes on itself (a spiral, a balloon loop) also breaks it at
    those crossings, so the fragments are put back together here. Each fragment is located just
    inside its ends, where it cannot be mistaken for the other pass through the same point.
    """
    found = []
    for x in pieces:
        eps = min(1e-6, x.length / 4)
        a = p.project(x.interpolate(eps)) - eps
        b = p.project(x.interpolate(x.length - eps)) + eps
        found.append([max(min(a, b), 0.0), min(max(a, b), p.length)])
    found.sort()
    out = []
    for a, b in found:
        if out and a - out[-1][1] < 2e-6:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def unfold(part, gap=GAP, step=0.002, fine=False):
    """Cut a run where it doubles back on itself.

    At a terminus the two tracks of a line are often joined by a turnback loop or a crossover
    mapped as running track, so joining the ways end to end gives one run that goes out on one
    track and comes back on the other. Two stretches of the run that lie beside each other mirror
    around the turning point: the run is cut there, and one_track() then treats the way back as the
    second track it is.
    """
    length = part.length
    if length < (0.0003 if fine else 8 * gap):
        return [part]
    n = max(8, int(length / step))
    pts = [part.interpolate(length * k / n) for k in range(n + 1)]
    tree = STRtree(pts)
    tangents = []
    for k in range(n + 1) if fine else ():
        a, b = pts[max(0, k - 1)], pts[min(n, k + 1)]
        norm = a.distance(b)
        tangents.append(((b.x-a.x)/norm, (b.y-a.y)/norm) if norm else (0, 0))
    def mirrored(k, j):
        if not fine:
            return j >= k + 2
        # Fine sampling must exclude ordinary neighbouring samples on a straight run.
        # A fold has opposing headings and travels much further than its displacement.
        return ((j-k)*length/n > max(.00015, 2*pts[k].distance(pts[j]))
                and sum(a*b for a,b in zip(tangents[k], tangents[j])) < -.5)
    mids = sorted((k + int(j)) / 2 for k in range(n + 1)
                  for j in tree.query(pts[k], predicate="dwithin", distance=gap)
                  if j > k and mirrored(k, int(j)))
    cuts, group = [], []
    for m in mids + [None]:
        if group and (m is None or m - group[-1] > 3):
            if len(group) >= 3:
                cuts.append(length * group[len(group) // 2] / n)
            group = []
        if m is not None:
            group.append(m)
    margin = .00004 if fine else 2 * gap
    cuts = [c for c in cuts if margin < c < length - margin]
    if not cuts:
        return [part]
    edges = [0.0] + cuts + [length]
    return [x for a, b in zip(edges, edges[1:]) for x in [substring(part, a, b)] if x.geom_type == "LineString" and x.length > 0]


def one_track(parts, near=NEAR, gap=GAP, keep=KEEP, apart=APART, apart_min=APART_MIN):
    """parts: LineStrings of one line, already joined end to end. Returns the LineStrings to draw.

    The longest run of track is taken first. Of every later run only what leaves the corridor of
    the track kept so far is added: a stretch that gets further than `gap` from it, with a short
    lead-in along its own track on either side. Such a stretch is kept when it is long, or when
    it is open at one end: the run ends out there, it left right after a junction, or the kept
    track ends where it starts (so it carries the line on, or closes a hole in it). A stretch that
    only swings out a little and comes back, as the second track does around a station or a
    flyover, is left out; one that gets well away from the kept track is a line of its own on the
    ground and stays. Two tracks may run 5 m apart (railways) or 15 to 40 m (the two tubes of a
    metro): what matters is only whether a stretch leaves the corridor.
    """
    parts = [x for g in parts for x in unfold(g, gap)]
    if len(parts) < 2:
        return list(parts)
    tree = STRtree(parts)
    nodes = Counter(c for g in parts for c in (g.coords[0], g.coords[-1]))
    kept = {}
    for i in sorted(range(len(parts)), key=lambda i: -parts[i].length):
        p = parts[i]
        around = [x for j in tree.query(p, predicate="dwithin", distance=gap) if j != i for x in kept.get(int(j), ())]
        if around:
            w, s, e, n = p.bounds
            around = [c for x in around for c in lines_of(shapely.clip_by_rect(x, w - 2 * gap, s - 2 * gap, e + 2 * gap, n + 2 * gap))]
        if not around:
            kept[i] = [p]
            continue
        path = unary_union(around)
        mids = spans(p, lines_of(p.difference(path.buffer(near, 4))))
        if not mids:
            kept[i] = []
            continue
        wide, well_away = path.buffer(gap, 4), path.buffer(apart, 4)
        met = Counter((round(c[0], 6), round(c[1], 6)) for x in around for c in (x.coords[0], x.coords[-1]))
        loose = [(n, Point(c)) for n, x in enumerate(around) for c in (x.coords[0], x.coords[-1])
                 if met[(round(c[0], 6), round(c[1], 6))] == 1]          # where two kept pieces meet the track carries on
        length, out = p.length, []
        for a, b in mids:
            x = substring(p, a, b)
            if x.geom_type != "LineString" or x.length == 0:
                continue
            # the stretches that leave the corridor of the kept track; excursions close together count as one
            away = []
            for lo, hi in spans(p, lines_of(x.difference(wide))):
                if away and lo - away[-1][1] < 2 * TAIL:
                    away[-1][1], away[-1][2] = hi, away[-1][2] + hi - lo
                else:
                    away.append([lo, hi, hi - lo])
            took = False
            for lo, hi, far_len in away:
                def is_open(at_start):
                    if at_start and lo < 1e-6 or not at_start and length - hi < 1e-6:
                        return True                              # the run ends out here, away from the kept track
                    c = p.interpolate(lo if at_start else hi)    # past the end of the kept track
                    return any(q.distance(c) < 1.2 * gap for _, q in loose)
                # A stretch that leaves the kept track at a junction and ends out there is a branch and
                # was caught above. One that leaves at a junction and comes back (the second track
                # between two station throats) is not open: it has to be long or far away to stay.
                if not (far_len > keep or (far_len > MIN_FAR and (is_open(True) or is_open(False)))
                        or (far_len > apart_min and sum(f.length for f in lines_of(substring(p, lo, hi).difference(well_away))) > apart_min)):
                    continue
                # with a lead-in on either side: back along its own track for as long as it is still
                # closing in on the kept one (two metro tubes never meet, they settle 20 m apart)
                def lead(start, way, limit):
                    at, d = start, path.distance(p.interpolate(start))
                    while abs(at - start) < TAIL:
                        nxt = at + way * 0.0002
                        if not min(limit, start) <= nxt <= max(limit, start):
                            return limit
                        dn = path.distance(p.interpolate(nxt))
                        if dn > d - 0.000005:
                            break
                        at, d = nxt, dn
                    return at
                sa, sb = lead(lo, -1, a), lead(hi, 1, b)
                if sa < ATTACH:
                    sa = 0.0
                if length - sb < ATTACH:
                    sb = length
                piece = substring(p, sa, sb)
                if piece.geom_type == "LineString" and piece.length > 0:
                    out.append(piece)
                    took = True
            if not took and b - a <= 6 * gap:
                # a short stretch inside the corridor is the second track, unless the kept track has a
                # hole right here: its two ends then lie beside the loose ends of two different pieces
                ends = [{n for n, q in loose if q.distance(Point(c)) < gap} for c in (x.coords[0], x.coords[-1])]
                if ends[0] and ends[1] and len(ends[0] | ends[1]) > 1:
                    out.append(x)
        kept[i] = out
    drawn = [x for v in kept.values() for x in v]
    if len(drawn) < 2:
        return drawn
    return lines_of(linemerge(MultiLineString(drawn)))


def smooth(co, reverse=150.0, corner=55.0):
    """A line has no sudden changes of direction. Two kinds are taken out of a coordinate run:

    - a spike: the run turns back on itself (a turnback siding followed out and back, two tracks
      joined at a terminus). The turning point is removed, again and again, until the run goes on.
    - a corner sharper than `corner` degrees where two pieces were joined: two cubic curves
      pass through the vertex with a common tangent. Keeping the vertex matters at junctions,
      where rounding the corner off the line would disconnect a branch attached there.
    """
    def turn(a, b, c):
        scale = math.cos(math.radians(b[1]))
        v1, v2 = ((b[0] - a[0]) * scale, b[1] - a[1]), ((c[0] - b[0]) * scale, c[1] - b[1])
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if not n1 or not n2:
            return 0.0
        return math.degrees(math.acos(max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / n1 / n2))))
    co = [tuple(c) for c in co]
    i = 1
    while 0 < i < len(co) - 1:
        if turn(co[i - 1], co[i], co[i + 1]) > reverse:
            del co[i]
            i = max(i - 1, 1)
        else:
            i += 1
    for _ in range(2):
        out = [co[0]] if co else []
        for a, b, c in zip(co, co[1:], co[2:]):
            if turn(a, b, c) > corner:
                scale = math.cos(math.radians(b[1]))
                vin, vout = ((b[0] - a[0]) * scale, b[1] - a[1]), ((c[0] - b[0]) * scale, c[1] - b[1])
                la, lc = math.hypot(*vin), math.hypot(*vout)
                u, v = (vin[0] / la, vin[1] / la), (vout[0] / lc, vout[1] / lc)
                t = (u[0] + v[0], u[1] + v[1])
                tn = math.hypot(*t)
                tangent = (t[0] / tn, t[1] / tn) if tn > 1e-9 else (-u[1], u[0])
                cut = min(la, lc, 0.0006) / 3

                def xy(dx, dy):
                    return (b[0] + dx / scale, b[1] + dy)

                start, end = xy(-u[0] * cut, -u[1] * cut), xy(v[0] * cut, v[1] * cut)
                controls = [(start, xy(-u[0] * cut * 2 / 3, -u[1] * cut * 2 / 3),
                             xy(-tangent[0] * cut / 3, -tangent[1] * cut / 3), b),
                            (b, xy(tangent[0] * cut / 3, tangent[1] * cut / 3),
                             xy(v[0] * cut * 2 / 3, v[1] * cut * 2 / 3), end)]
                out.append(start)
                for p0, p1, p2, p3 in controls:
                    for i in range(1, 5):
                        q = i / 4
                        out.append(tuple((1 - q) ** 3 * p0[j] + 3 * (1 - q) ** 2 * q * p1[j]
                                         + 3 * (1 - q) * q * q * p2[j] + q ** 3 * p3[j] for j in (0, 1)))
            else:
                out.append(b)
        if len(co) > 1:
            out.append(co[-1])
        co = out
    return co


def bounded_curve(co, per, within, corner):
    """Interpolate inside a corridor without breaking the tangent at a retained vertex.

    Scaling each span's normal displacement separately changes its endpoint heading.
    Instead the two spans use the same tangent direction, and shorten their Bezier
    handles to fit the corridor. Adaptive subdivision follows the endpoint bends even
    when the handles are tiny compared with a long straight chord.
    """
    scale = math.cos(math.radians(co[len(co) // 2][1]))
    pts = [(x * scale, y) for x, y in co]

    def unit(x, y):
        n = math.hypot(x, y)
        return (x / n, y / n) if n else (0.0, 0.0)

    dirs = [unit(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
    lengths = [math.dist(a, b) for a, b in zip(pts, pts[1:])]
    tangents = [dirs[0]]
    turns = [0.0]
    for u, v in zip(dirs, dirs[1:]):
        angle = math.degrees(math.acos(max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))))
        turns.append(angle)
        tangents.append(unit(u[0] + v[0], u[1] + v[1]) if per / 2 < angle <= corner else None)
    tangents.append(dirs[-1])
    turns.append(0.0)
    if co[0] == co[-1]:
        u, v = dirs[-1], dirs[0]
        angle = math.degrees(math.acos(max(-1, min(1, u[0] * v[0] + u[1] * v[1]))))
        turns[0] = turns[-1] = angle
        tangents[0] = tangents[-1] = unit(u[0] + v[0], u[1] + v[1]) if per / 2 < angle <= corner else None
    out = [co[0]]

    def sample(p, depth=0):
        a, b, c, d = p
        chord = unit(d[0] - a[0], d[1] - a[1])
        first, last = unit(b[0] - a[0], b[1] - a[1]), unit(d[0] - c[0], d[1] - c[1])
        heading_error = max(math.degrees(math.acos(max(-1, min(1, t[0] * chord[0] + t[1] * chord[1]))))
                            for t in (first, last) if t != (0.0, 0.0))
        off = max(abs((q[0] - a[0]) * chord[1] - (q[1] - a[1]) * chord[0]) for q in (b, c))
        if depth >= 16 or (heading_error <= per / 2 and off <= within / 12):
            out.append((d[0] / scale, d[1]))
            return
        ab, bc, cd = [((u[0] + v[0]) / 2, (u[1] + v[1]) / 2) for u, v in zip(p, p[1:])]
        abc, bcd = ((ab[0] + bc[0]) / 2, (ab[1] + bc[1]) / 2), ((bc[0] + cd[0]) / 2, (bc[1] + cd[1]) / 2)
        middle = ((abc[0] + bcd[0]) / 2, (abc[1] + bcd[1]) / 2)
        sample((a, ab, abc, middle), depth + 1)
        sample((middle, bcd, cd, d), depth + 1)

    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        direction, length = dirs[i], lengths[i]
        if not length or max(turns[i] if turns[i] <= corner else 0, turns[i + 1] if turns[i + 1] <= corner else 0) <= per / 2:
            out.append(co[i + 1])
            continue
        handles = []
        for j, sign, p in ((i, 1, a), (i + 1, -1, b)):
            tangent = tangents[j] or direction
            cross = abs(tangent[0] * direction[1] - tangent[1] * direction[0])
            # The Bezier weights of its two inner controls sum to at most 3/4.
            # Both controls within 4/3 of the tolerance keep the entire curve inside.
            size = min(length / 3, within * 4 / (3 * cross)) if cross > 1e-10 else length / 3
            handles.append((p[0] + sign * tangent[0] * size, p[1] + sign * tangent[1] * size))
        sample((a, handles[0], handles[1], b))
        out[-1] = co[i + 1]                    # preserve junctions exactly, including float representation
    return out


def curved(co, per=2.5, most=10, shortest=0.00006, corner=60.0, within=None, adaptive=False):
    """A railway curve is an arc, and simplifying leaves it a polygon with a visible angle at every
    vertex. This draws the arc back: between two vertices the line follows a smooth curve through
    them (a centripetal Catmull-Rom spline: it passes through every vertex, so nothing moves off
    the track, and it cannot loop or overshoot), with more points the more the line turns there,
    about one for every `per` degrees. A straight stretch gets none. A real corner, sharper than
    `corner` degrees, is where two pieces were joined: the curve stops and starts again there.

    `within` is the tolerance the line was simplified with (degrees). The track itself lies no
    further than that from the straight line between two vertices, so the curve may not either:
    where it would swing wider (a long stretch that turns one way at one end and the other way at
    the other), it is pulled in towards the straight line until it fits.

    With adaptive=True, shared tangent directions and adaptive Bezier subdivision
    also preserve smooth joins under that constraint. `per` bounds the sampled
    heading change; the fixed `most` and `shortest` limits do not apply in this mode.
    Metro uses this mode because small curves remain visible at street scale."""
    co = [tuple(c) for c in co]
    n = len(co)
    if n < 3:
        return co
    if within and adaptive:
        return bounded_curve(co, per, within, corner)
    scale = math.cos(math.radians(co[n // 2][1]))
    pts = [(x * scale, y) for x, y in co]

    def turn(a, b, c):
        v1, v2 = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if not n1 or not n2:
            return 0.0
        return math.degrees(math.acos(max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / n1 / n2))))
    turns = [0.0] + [turn(pts[i - 1], pts[i], pts[i + 1]) for i in range(1, n - 1)] + [0.0]
    # A long straight next to a short chord would bow along its whole length to meet the curve.
    # It is held straight: a point is set on it as far from the bend as the chord on the other
    # side is long, and the line only curves between the bend and that point.
    held, kept = [pts[0]], [co[0]]
    for i in range(n - 1):
        p1, p2 = pts[i], pts[i + 1]
        length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        before = math.hypot(p1[0] - pts[i - 1][0], p1[1] - pts[i - 1][1]) if i > 0 else 0.0
        after = math.hypot(pts[i + 2][0] - p2[0], pts[i + 2][1] - p2[1]) if i + 2 < n else 0.0
        marks = []
        if turns[i] >= per / 2 and before and length > 2.5 * before:
            marks.append(min(before, length / 3) / length)
        if turns[i + 1] >= per / 2 and after and length > 2.5 * after:
            marks.append(1 - min(after, length / 3) / length)
        for q in sorted(marks):
            held.append((p1[0] + (p2[0] - p1[0]) * q, p1[1] + (p2[1] - p1[1]) * q))
            kept.append(None)
        held.append(p2)
        kept.append(co[i + 1])
    pts, n = held, len(held)
    co = [c if c is not None else (pt[0] / scale, pt[1]) for c, pt in zip(kept, pts)]
    turns = [0.0] + [turn(pts[i - 1], pts[i], pts[i + 1]) for i in range(1, n - 1)] + [0.0]
    out = [co[0]]
    for i in range(n - 1):
        p1, p2 = pts[i], pts[i + 1]
        length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        bend = max(t for t in (turns[i], turns[i + 1]) if t <= corner) if min(turns[i], turns[i + 1]) <= corner else 0.0
        steps = min(most, math.ceil(bend / per), int(length / shortest))
        if steps > 1:
            # beyond an end or a corner the curve has no neighbour to lean on: it leaves straight
            p0 = pts[i - 1] if i > 0 and turns[i] <= corner else (2 * p1[0] - p2[0], 2 * p1[1] - p2[1])
            p3 = pts[i + 2] if i + 2 < n and turns[i + 1] <= corner else (2 * p2[0] - p1[0], 2 * p2[1] - p1[1])
            t1 = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) ** 0.5
            t2 = t1 + length ** 0.5
            t3 = t2 + math.hypot(p3[0] - p2[0], p3[1] - p2[1]) ** 0.5
            if 0 < t1 < t2 < t3:
                added = []
                for k in range(1, steps):
                    t = t1 + (t2 - t1) * k / steps
                    a1 = [(t1 - t) / t1 * p0[j] + t / t1 * p1[j] for j in (0, 1)]
                    a2 = [(t2 - t) / (t2 - t1) * p1[j] + (t - t1) / (t2 - t1) * p2[j] for j in (0, 1)]
                    a3 = [(t3 - t) / (t3 - t2) * p2[j] + (t - t2) / (t3 - t2) * p3[j] for j in (0, 1)]
                    b1 = [(t2 - t) / t2 * a1[j] + t / t2 * a2[j] for j in (0, 1)]
                    b2 = [(t3 - t) / (t3 - t1) * a2[j] + (t - t1) / (t3 - t1) * a3[j] for j in (0, 1)]
                    c = [(t2 - t) / (t2 - t1) * b1[j] + (t - t1) / (t2 - t1) * b2[j] for j in (0, 1)]
                    along = ((c[0] - p1[0]) * (p2[0] - p1[0]) + (c[1] - p1[1]) * (p2[1] - p1[1])) / length ** 2
                    foot = (p1[0] + (p2[0] - p1[0]) * along, p1[1] + (p2[1] - p1[1]) * along)
                    added.append((foot, (c[0] - foot[0], c[1] - foot[1])))
                widest = max(math.hypot(*off) for _, off in added)
                fit = within / widest if within and widest > within else 1.0
                out += [((foot[0] + off[0] * fit) / scale, foot[1] + off[1] * fit) for foot, off in added]
        out.append(co[i + 1])
    return out


def eased(before, after, least=0.00006, bends=False):
    """Two coordinate runs that are to be joined end to start. When the join would be a step to
    the side (two parallel tracks: the ends are abreast of each other), each is cut back by a few
    times the width of the step, so that the join becomes a slant like a train changing tracks.
    A step narrower than `least` is joined as it is. With `bends`, so are two pieces that meet
    at an angle: one turning off the other at a junction."""
    step = math.hypot(before[-1][0] - after[0][0], before[-1][1] - after[0][1])
    if step < least or len(before) < 2 or len(after) < 2:
        return before, after
    a, b = LineString(before), LineString(after)
    back = min(3 * step, a.length / 3, b.length / 3)
    if back <= 0:
        return before, after
    if bends:
        # Only between two pieces that run the same way where they are cut back. Where one turns
        # off the other (the legs of a junction), the join would go across the inside of the bend.
        p, q, r, t = a.interpolate(a.length - back), a.interpolate(a.length), b.interpolate(0), b.interpolate(back)
        da, db = p.distance(q), r.distance(t)
        if not da or not db or ((q.x - p.x) * (t.x - r.x) + (q.y - p.y) * (t.y - r.y)) / da / db < 0.7:
            return before, after
    a, b = substring(a, 0, a.length - back), substring(b, back, b.length)
    if a.geom_type != "LineString" or b.geom_type != "LineString":
        return before, after
    return list(a.coords), list(b.coords)


def stitch(pieces, reach=0.0012, far=0.005, ease=0.00006, bends=False):
    """Make one line continuous: join its pieces wherever they stop short of each other.

    Drawing a double line by one of its tracks leaves seams: the kept track changes from one to
    the other, or a piece ends a few metres from where the next begins. Two ends within `reach`
    are joined into one run (nearest pairs first, each end once, never closing a run on itself),
    and an end that stops within `reach` of the side of another run is carried on to it. Two ends
    further apart, up to `far`, are joined only when each points at the other: a stretch of the
    line that is missing from the data, with the line carrying straight on behind it. Runs come
    back in the direction of their longest piece. `ease` is the narrowest step to the side that
    is turned into a slant; with `bends`, pieces that meet at an angle are joined as they are (the
    metro layers: a light-rail line turning off at a junction must not be cut across the bend).
    """
    runs = [list(g.coords) for g in pieces if g.length > 0]
    if len(runs) < 2:
        return [LineString(r) for r in runs]
    ends = [(i, side, Point(r[0] if side == 0 else r[-1])) for i, r in enumerate(runs) for side in (0, 1)]
    tree = STRtree([e[2] for e in ends])

    def outward(k):
        """Unit vector in which the run leaves through this end."""
        i, side, _ = ends[k]
        g = LineString(runs[i])
        step = min(0.0005, g.length)
        a, b = (g.interpolate(step), g.interpolate(0)) if side == 0 else (g.interpolate(g.length - step), g.interpolate(g.length))
        d = a.distance(b)
        return ((b.x - a.x) / d, (b.y - a.y) / d) if d else (0.0, 0.0)

    def facing(a, b):
        """Do ends a and b point at each other?"""
        pa, pb = ends[a][2], ends[b][2]
        d = pa.distance(pb)
        ux, uy = (pb.x - pa.x) / d, (pb.y - pa.y) / d
        oa, ob = outward(a), outward(b)
        return oa[0] * ux + oa[1] * uy > 0.8 and -(ob[0] * ux + ob[1] * uy) > 0.8
    pairs = set()
    for a, e in enumerate(ends):
        for b in tree.query(e[2], predicate="dwithin", distance=far):
            if a < int(b) and ends[int(b)][0] != e[0]:
                d = e[2].distance(ends[int(b)][2])
                if d <= reach or facing(a, int(b)):
                    pairs.add((d, a, int(b)))
    link, group = {}, list(range(len(runs)))

    def root(i):
        while group[i] != i:
            group[i] = group[group[i]]
            i = group[i]
        return i
    for _, a, b in sorted(pairs):
        if a in link or b in link or root(ends[a][0]) == root(ends[b][0]):
            continue
        link[a], link[b] = b, a
        group[root(ends[a][0])] = root(ends[b][0])
    out, seen = [], set()
    for i in sorted(range(len(runs)), key=lambda i: (2 * i in link) + (2 * i + 1 in link)):   # open ends first
        if i in seen:
            continue
        side = 0 if 2 * i not in link else 1 if 2 * i + 1 not in link else 0     # start from a free end
        chain, longest, k, enter = [], (0.0, False), i, side
        while k is not None and k not in seen:
            seen.add(k)
            co = runs[k] if enter == 0 else runs[k][::-1]
            length = LineString(co).length
            if length > longest[0]:
                longest = (length, enter == 1)
            if chain and chain[-1] != co[0]:
                chain, co = eased(chain, co, ease, bends)
            chain += co if not chain or chain[-1] != co[0] else co[1:]
            nxt = link.get(2 * k + (1 - enter))
            k, enter = (ends[nxt][0], ends[nxt][1]) if nxt is not None else (None, 0)
        out.append(chain[::-1] if longest[1] else chain)
    geoms = [LineString(c) for c in out if len(c) > 1]
    if len(geoms) > 1:          # an end that stops beside another run is carried on to it
        tree = STRtree(geoms)
        whole = list(geoms)
        sliver = {i for i, g in enumerate(whole) if g.length < reach and any(
            int(j) != i and whole[int(j)].length > g.length and whole[int(j)].distance(Point(g.coords[0])) < reach
            and whole[int(j)].distance(Point(g.coords[-1])) < reach
            and all(whole[int(j)].distance(g.interpolate(f, normalized=True)) < GAP for f in (.25, .5, .75))
            for j in tree.query(g, predicate="dwithin", distance=reach))}
        for i, g in enumerate(whole):
            co = list(g.coords)
            if i in sliver:                 # lies beside a longer run from end to end: nothing to join
                geoms[i] = None
                continue
            for at_start in (True, False):
                end = Point(co[0] if at_start else co[-1])
                near = [(whole[int(j)].distance(end), int(j)) for j in tree.query(end, predicate="dwithin", distance=reach)
                        if int(j) != i and int(j) not in sliver]
                if near and 1e-7 < min(near)[0]:
                    d, other = min(near)[0], whole[min(near)[1]]
                    # join at a slant, further along the other run in the direction this one was going
                    inner = Point(co[1] if at_start else co[-2])
                    at = other.project(end)
                    ahead = [other.interpolate(min(max(at + way * 3 * d, 0), other.length)) for way in (1, -1)]
                    q = max(ahead, key=lambda c: c.distance(inner))
                    co = [(q.x, q.y)] + co if at_start else co + [(q.x, q.y)]
            geoms[i] = LineString(co)
        geoms = [g for g in geoms if g is not None]
    return geoms


def bridge(lines, tracks, joined=0.0003, reach=0.03, limit=0.045, project_ends=False):
    """Carry every line through the places where it is interrupted for a short way.

    lines: {line: pieces}, extended in place. tracks: every track there is, whatever its name
    (running lines, station and yard tracks, connecting curves), as coordinate lists. A named line
    often stops at a station throat or a junction and resumes on the other side, with the track
    in between carrying another name or none. The parts of a line that lie within `reach` of each
    other are joined along the shortest way over existing track, as long as that is not longer
    than `limit`; the track in between becomes part of the line.
    """
    import heapq
    from collections import defaultdict
    geoms = [LineString(co) for co in tracks]
    track_tree = STRtree(geoms)
    added = 0
    for key, pieces in lines.items():
        if len(pieces) < 2:
            continue
        tree = STRtree(pieces)
        group = list(range(len(pieces)))

        def root(i):
            while group[i] != i:
                group[i] = group[group[i]]
                i = group[i]
            return i
        for i, g in enumerate(pieces):
            for j in tree.query(g, predicate="dwithin", distance=joined):
                group[root(int(j))] = root(i)
        parts = defaultdict(list)
        for i in range(len(pieces)):
            parts[root(i)].append(i)
        if len(parts) < 2:
            continue
        whole = {r: unary_union([pieces[i] for i in ids]) for r, ids in parts.items()}
        done = set()
        for r in whole:
            near = min(((whole[r].distance(whole[o]), o) for o in whole if o != r), default=None)
            if near is None or near[0] > reach or (min(r, near[1]), max(r, near[1])) in done:
                continue
            done.add((min(r, near[1]), max(r, near[1])))

            def tip(ids, target):       # the piece end of one part nearest the other part
                ends = [Point(c) for i in ids for c in (pieces[i].coords[0], pieces[i].coords[-1])]
                return min(ends, key=lambda e: e.distance(target))
            a, b = tip(parts[r], whole[near[1]]), tip(parts[near[1]], whole[r])
            # the track network around the two ends: tracks are split wherever two of them share a point
            local = [tracks[int(j)] for j in track_tree.query(LineString([a, b]).buffer(limit / 2).envelope)]
            if project_ends and local:
                # A display join can fall inside an OSM way, rather than at its endpoint.
                # Split the actual source way at that projection before finding a track path.
                raw_geoms = [LineString(co) for co in local]
                cuts = defaultdict(list)
                for pt in (a, b):
                    i = min(range(len(raw_geoms)), key=lambda k: raw_geoms[k].distance(pt))
                    cuts[i].append(raw_geoms[i].project(pt))
                split = []
                for i, g in enumerate(raw_geoms):
                    positions = sorted({0.0, g.length, *cuts[i]})
                    for lo, hi in zip(positions, positions[1:]):
                        seg = substring(g, lo, hi)
                        if seg.geom_type == "LineString" and seg.length > 1e-10:
                            split.append(list(seg.coords))
                local = split
            use = Counter(c for co in local for c in set(co))
            adj = defaultdict(list)
            for co in local:
                start = 0
                for i in range(1, len(co)):
                    if i == len(co) - 1 or use[co[i]] > 1:
                        seg = co[start:i + 1]
                        d = LineString(seg).length
                        adj[seg[0]].append((seg[-1], d, seg))
                        adj[seg[-1]].append((seg[0], d, seg[::-1]))
                        start = i
            if not adj:
                continue
            na = min(adj, key=lambda c: (c[0] - a.x) ** 2 + (c[1] - a.y) ** 2)
            nb = min(adj, key=lambda c: (c[0] - b.x) ** 2 + (c[1] - b.y) ** 2)
            if Point(na).distance(a) > 2 * joined or Point(nb).distance(b) > 2 * joined or na == nb:
                continue
            dist, prev, heap = {na: 0.0}, {}, [(0.0, na)]
            while heap:
                d, u = heapq.heappop(heap)
                if u == nb or d > limit:
                    break
                if d > dist[u]:
                    continue
                for v, length, co in adj[u]:
                    if d + length < dist.get(v, 9e9):
                        dist[v], prev[v] = d + length, (u, co)
                        heapq.heappush(heap, (d + length, v))
            if nb not in prev:
                continue
            path, node = [], nb
            while node != na:
                node, co = prev[node]
                path = list(co) + path[1:] if path else list(co)
            pieces.append(LineString(path))
            added += 1
    return added


def join_up(lines):
    """Close the gaps left where lines meet. lines: one (parts, drawn) pair per line; drawn is extended in place.

    A line ends at a junction on one particular track of the other line. If that line was drawn
    by its other track, the end now stops short of it, by anything from the 5 m between two tracks
    to a few hundred metres at a flying junction. From every drawn end that touches nothing
    drawn, the track it stands on (kept or not, of any line) is followed until it comes up beside
    something drawn, and that stretch is added to the line the track belongs to.
    """
    part_geoms = [g for parts, _ in lines for g in parts]
    part_owner = [k for k, (parts, _) in enumerate(lines) for _ in parts]
    drawn_geoms = [g for _, drawn in lines for g in drawn]
    if not part_geoms or not drawn_geoms:
        return 0
    part_tree, drawn_tree = STRtree(part_geoms), STRtree(drawn_geoms)
    added = set()
    for k, g in enumerate(drawn_geoms):
        if g.coords[0] == g.coords[-1]:
            continue
        for c in (g.coords[0], g.coords[-1]):
            end = Point(c)
            if any(j != k for j in drawn_tree.query(end, predicate="dwithin", distance=TOUCH)):
                continue
            best = None
            for q in part_tree.query(end, predicate="dwithin", distance=1e-7):
                track = part_geoms[q]
                t = track.project(end)
                for way in (1, -1):
                    s = t + way * STEP
                    if not 0 <= s <= track.length or g.distance(track.interpolate(s)) < 1e-7:
                        continue            # the track ends here, or this is the piece itself
                    while 0 <= s <= track.length and abs(s - t) <= REACH and (best is None or abs(s - t) < best[0]):
                        if any(j != k for j in drawn_tree.query(track.interpolate(s), predicate="dwithin", distance=TOUCH)):
                            best = (abs(s - t), int(q), min(t, s), max(t, s))
                            break
                        s += way * STEP
            if best:
                added.add((best[1], round(best[2], 6), round(best[3], 6)))
    for q, a, b in added:
        piece = substring(part_geoms[q], a, b)
        if piece.geom_type == "LineString" and piece.length > 0:
            lines[part_owner[q]][1].append(piece)
    return len(added)
