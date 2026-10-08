"""Where one line runs along another line's path, found exactly.

Lines in each other's company are drawn along one path (scripts/process_osm.py). The samples that
find the company are 40 m apart, which is the size of a whole light-rail junction: taken as they
are, a line that turns off is carried along the other line's path to the next sample and joined
across from there, inside the bend. Here the place where a line comes onto a path and the place
where it leaves it are found to a few metres, and the line's own track is brought over to meet the
path, so the line follows its own curve through a junction.

Distances are in degrees (0.0001 is about 11 m).
"""
import math

from shapely.geometry import LineString

# Light rail runs in streets: curves of 25 m radius, the three legs of a junction within 100 m of
# each other, a railway viaduct 30 m to the side. A corridor 55 m wide takes all of that for one
# path. A light-rail line is in another line's company only on the same track (or the second track
# of the same double line), for however short a way, and is drawn on its own track everywhere else.
TRACK = 0.00015      # ~17 m: on the same track, or on its second track
TRACK_MIN = 0.0006   # ~65 m: shorter company on one track is a crossing
FINE = 0.00005       # ~5 m: how exactly the place is found where a line comes onto another one's path, and leaves it


def heading(g, at, d=0.00008):
    a, b = g.interpolate(max(at - d, 0)), g.interpolate(min(at + d, g.length))
    n = math.hypot(b.x - a.x, b.y - a.y)
    return ((b.x - a.x) / n, (b.y - a.y) / n) if n else (0.0, 0.0)


def beside(piece, pos, ref, near):
    """Does piece, at pos, run along ref: within near of it, not past its end, going the same way?"""
    pt = piece.interpolate(pos)
    on, d = ref.project(pt), ref.distance(pt)
    if d > near or (d > 0.00003 and not 0 < on < ref.length):
        return False
    h, k = heading(piece, pos), heading(ref, on)
    return abs(h[0] * k[0] + h[1] * k[1]) > 0.9


def exactly(piece, ref, lo, hi, near, floor, ceiling):
    """Where piece runs along ref, to within FINE. The samples had it from lo to hi; each end is
    moved in to where the piece really is beside ref, then out for as long as it still is (not
    beyond floor and ceiling, where the stretches before and after lie). None if it nowhere is."""
    while lo < hi and not beside(piece, lo, ref, near):
        lo = min(lo + FINE, hi)
    while hi > lo and not beside(piece, hi, ref, near):
        hi = max(hi - FINE, lo)
    if not beside(piece, lo, ref, near):
        return None
    while lo - FINE >= floor and beside(piece, lo - FINE, ref, near):
        lo -= FINE
    while hi + FINE <= ceiling and beside(piece, hi + FINE, ref, near):
        hi += FINE
    return lo, hi


def settled(piece, ref, lo, hi):
    """The stretch of piece along ref with its ends moved in to where the piece still runs at the
    distance from ref that it keeps: on it, or on the track beside it. Past the points of a junction
    the line is still close to ref and still going much the same way, but it is on its way out."""
    n = max(2, int((hi - lo) / FINE) + 1)
    at = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
    d = [ref.distance(piece.interpolate(v)) for v in at]
    reach = max(1, int(0.0004 / FINE))
    i, j = 0, n - 1
    while i < j and d[i] > min(d[i:i + reach + 1]) + 0.000015:
        i += 1
    while j > i and d[j] > min(d[max(j - reach, 0):j + 1]) + 0.000015:
        j -= 1
    return at[i], at[j]


def meeting(own, before, after):
    """A line's own track between two stretches drawn along other lines' paths (either may be
    None), moved over at its ends to start and finish on those paths. The path may be the second
    track of the double line, 5 m to the side: the line comes over to its own track gradually,
    within six times that distance, and keeps the shape of its curve."""
    co = list(own.coords)
    cum = [0.0]
    for (x1, y1), (x2, y2) in zip(co, co[1:]):
        cum.append(cum[-1] + math.hypot(x2 - x1, y2 - y1))
    length, shifts = cum[-1], []                  # (at the start?, dx, dy, how far along the shift dies out)
    for ref, pos in ((before, 0.0), (after, length)):
        if ref is None:
            continue
        a = own.interpolate(pos)
        b = ref.interpolate(ref.project(a))
        step = a.distance(b)
        if 1e-7 < step < 2 * TRACK:
            shifts.append((pos == 0.0, b.x - a.x, b.y - a.y, min(length, max(6 * step, 0.0002))))
    if not shifts:
        return own
    marks = set(cum)                              # with vertices close enough together for the move to be gradual
    for start, _, _, far in shifts:
        marks |= {v if start else length - v for v in [k * FINE for k in range(1, int(far / FINE) + 1)] + [far]}
    out = []
    for v in sorted(m for m in marks if 0 <= m <= length):
        pt = own.interpolate(v)
        x, y = pt.x, pt.y
        for start, dx, dy, far in shifts:
            w = max(0.0, 1 - (v if start else length - v) / far)
            x, y = x + dx * w, y + dy * w
        out.append((x, y))
    return LineString(out)
