"""Seats given by hand along a corridor.

Each kind of line is laid out on its own: urban lines side by side with each other, a railway on
its own track, a suburban service one step beside the railway it runs on. Where lines of several
kinds share a corridor they are drawn over one another when zoomed out (北京北 to 昌平: 13 号线,
昌平线, 京包客专线, 怀柔－密云线, S2 线 and 东北环线, two to five of them at a time).

data/seat_overrides.json lists such corridors, each looked at by hand. A corridor has a spine (a
line, between two points), which stays on its own track, and for every other line named a list of
places along the spine with the seat the line takes from there on: so many steps to the right of
the spine's direction (negative: to its left), or null for no seat. A line has its seat where it
runs along the spine within `reach`; a change of seat is spread over `ramp` around its place, in
eighths of a step as the layout's own changes are, `ramp` metres to a step. Lines not named are left as they are.

Zoomed out, a line seated beside a spine is drawn along the spine's own path, so that the two are
exactly parallel: on its own track it would wander with the 20 to 100 m that really lie between
the two tracks, which shows as a wavy line beside a straight one (owner, 2026-10-13). Such a
stretch is written twice: with zf: 1 along the spine, shown below zoom SWAP, and with zn: 1 on its
own track, shown from there on (the page and scripts/build_tiles.py know the two marks; whatever
reads the lines as tracks takes the zn one and leaves zf out).

A railway seated this way is back on its track when zoomed in, as any railway beside another. An
urban line carries the move as goff, which the page takes off again when zoomed in. A suburban
service (k: "s") is drawn one step to the right of its path where the data says nothing; here it
gets a seat (off) of its own.
"""
import heapq
import json
import math
from pathlib import Path

from shapely.geometry import LineString, Point
from shapely.ops import linemerge, substring, unary_union

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "data" / "seat_overrides.json"
M = 111320.0            # metres in a degree of latitude
GRAIN = 25.0            # metres: a line is cut no finer than this
JOIN = 15.0             # metres: pieces of a spine this close meet
SPINE_END = 300.0       # metres: a spine must reach this near the places its corridor is listed from and to
LOOSE = 2.5             # once in a corridor a line stays in it while it is within this many times the reach
MEET = 3.0              # metres: a track that ends this close to another piece runs into it
BLEND = 1500.0          # metres: over this length a line comes off its own track onto the spine's path, zoomed out
FADE = 4                # steps: a seat no larger than this has faded within FADE x ramp of a corridor
EIGHTH = 8              # seats are written in eighths of a step


class Corridor:
    def __init__(self, row, spine_paths):
        self.name = row["name"]
        self.cos = math.cos(math.radians((row["from"][1] + row["to"][1]) / 2))
        a, b = Point(self.xy(row["from"])), Point(self.xy(row["to"]))
        self.spine = through([LineString([self.xy(p) for p in co]) for co in spine_paths if len(co) > 1], a, b)
        off = max(Point(self.spine.coords[0]).distance(a), Point(self.spine.coords[-1]).distance(b))
        if off > SPINE_END:
            raise ValueError(f"seat override {row['name']!r}: {row['spine']} does not run from 'from' to 'to' (an end is {off:.0f} m away)")
        self.reach, self.ramp = row["reach_m"], row["ramp_m"]
        self.seats = {line: sorted(((self.spine.project(Point(self.xy(step["at"]))), step["seat"]) for step in steps), key=lambda step: step[0])
                      for line, steps in row["seats"].items()}
        # the seat a line comes with from another corridor, where it joins this one
        self.before = {line: steps[0]["before"] for line, steps in row["seats"].items() if "before" in steps[0]}

    def xy(self, p):
        """Metres on a plane that is true along this corridor."""
        return (p[0] * self.cos * M, p[1] * M)

    def seat(self, line, s):
        """(seat, how much of it) of a line at s metres along the spine."""
        steps = self.seats[line]
        k = min(range(len(steps)), key=lambda i: abs(s - steps[i][0]))
        before, after = (steps[k - 1][1] if k else self.before.get(line)), steps[k][1]
        span = self.ramp * max(1.0, abs((after or 0) - (before or 0)))        # so many metres to a step
        if abs(s - steps[k][0]) < span / 2 and not (before is None or after is None):
            return before + (after - before) * ((s - steps[k][0]) / span + 0.5), 1.0      # a change of seat
        value = None                    # (to or from no seat nothing is blended here: faded() makes that change)
        for at, seat in steps:
            if at <= s:
                value = seat
        return (0.0, 0.0) if value is None else (value, 1.0)

    def along(self, p, q, loose=False):
        """(metres along the spine, running the spine's way?) of a piece of line from p to q, or
        None away from it. loose: for a piece between two that are in the corridor, which stays
        in it while it is within LOOSE times the reach (the tracks of a station spread)."""
        mid = Point((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        if self.spine.distance(mid) > self.reach * (LOOSE if loose else 1):
            return None
        s = self.spine.project(mid)
        if s <= 0 or s >= self.spine.length:
            return None
        a, b = self.spine.interpolate(max(s - 30, 0)), self.spine.interpolate(min(s + 30, self.spine.length))
        dx, dy, ex, ey = q[0] - p[0], q[1] - p[1], b.x - a.x, b.y - a.y
        dot = (dx * ex + dy * ey) / ((math.hypot(dx, dy) or 1) * (math.hypot(ex, ey) or 1))
        return (s, dot > 0) if abs(dot) > (0.5 if loose else 0.7) else None      # a line that crosses is not in the corridor


def through(paths, a, b):
    """The way along a line from a to b: one path through its pieces, however the line is cut up.
    A line is not one string of track: it forks where its two tracks part round a station, and
    is cut where its design speed changes. The longest piece alone can stop short of the place a
    corridor is listed to begin at (京雄城际线 at 大兴机场: the seats of the 大兴机场线 began 7.7 km
    late, 2026-10-13). Pieces within JOIN metres of each other are taken to meet."""
    near = a.buffer(a.distance(b) * 0.6 + 3000).union(b.buffer(a.distance(b) * 0.6 + 3000)).envelope
    noded = unary_union([g for g in paths if g.intersects(near)])
    pieces = [g for g in getattr(noded, "geoms", [noded]) if g.geom_type == "LineString" and g.length > 0]
    if not pieces:
        raise ValueError("no track of the spine near its corridor")
    start, goal = (min(range(len(pieces)), key=lambda i: pieces[i].distance(p)) for p in (a, b))
    ta, tb = pieces[start].project(a), pieces[goal].project(b)
    if start == goal:
        return substring(pieces[start], ta, tb)
    ends = [(g.coords[0], g.coords[-1]) for g in pieces]
    key = lambda p: (round(p[0] / JOIN), round(p[1] / JOIN))
    at = {}
    for i, (p, q) in enumerate(ends):
        at.setdefault(key(p), []).append((i, 0))
        at.setdefault(key(q), []).append((i, 1))

    def meeting(p):                     # the piece ends at this place, and in the cells round it
        kx, ky = key(p)
        return [hit for dx in (-1, 0, 1) for dy in (-1, 0, 1) for hit in at.get((kx + dx, ky + dy), ())]
    best = {(start, 0): ta, (start, 1): pieces[start].length - ta}      # (piece, the end reached) -> metres
    came, heap, done = {}, [(d, k) for k, d in best.items()], set()
    heapq.heapify(heap)
    found = None
    while heap:
        d, (i, side) = heapq.heappop(heap)
        if (i, side) in done:
            continue
        done.add((i, side))
        for j, other in meeting(ends[i][side]):
            if j == i:
                continue
            if j == goal:
                total = d + (tb if other == 0 else pieces[goal].length - tb)
                if found is None or total < found[0]:
                    found = (total, (i, side), other)
                continue
            step = d + pieces[j].length
            far = (j, 1 - other)
            if step < best.get(far, math.inf):
                best[far], came[far] = step, (i, side)
                heapq.heappush(heap, (step, far))
    if found is None:
        raise ValueError("the spine's track does not join up between 'from' and 'to'")
    _, last, entered = found
    chain = []
    while last in came:
        i, side = last
        chain.append(list(pieces[i].coords) if side == 1 else list(pieces[i].coords)[::-1])
        last = came[last]
    first = substring(pieces[start], ta, 0 if last[1] == 0 else pieces[start].length)
    tail = substring(pieces[goal], 0 if entered == 0 else pieces[goal].length, tb)
    coords = list(first.coords)
    for part in chain[::-1] + [list(tail.coords)]:
        coords += part[1:] if coords and part and math.hypot(part[0][0] - coords[-1][0], part[0][1] - coords[-1][1]) < 1e-6 else part
    return LineString(coords)


def corridors(country, features, path=FILE):
    """The corridors listed for a country, with their spines taken from the features given."""
    if not path.exists():
        return []
    out = []
    for row in json.loads(path.read_text(encoding="utf-8"))["corridors"]:
        missing = [key for key in ("name", "country", "spine", "from", "to", "reach_m", "ramp_m", "seats", "why", "asked") if not row.get(key)]
        if missing:
            raise ValueError(f"seat override {row.get('name')!r} lacks {missing}")
        if row["country"] != country:
            continue
        paths = [co for f in features if f["properties"].get("n") == row["spine"] and not f["properties"].get("zf")
                 for co in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]])]
        if not paths:
            raise ValueError(f"seat override {row['name']!r}: no line named {row['spine']}")
        out.append(Corridor(row, paths))
    return out


def finer(coords, near):
    """The path with a point at least every GRAIN metres where it runs by one of the corridors
    (within reach and what a seat takes to fade); elsewhere as it is: [(lon, lat)]."""
    first = near[0]
    out = [tuple(coords[0])]
    for a, b in zip(coords, coords[1:]):
        n = 1
        if any(LineString([c.xy(a), c.xy(b)]).distance(c.spine) <= c.reach + FADE * c.ramp for c in near):
            (ax, ay), (bx, by) = first.xy(a), first.xy(b)
            n = max(1, int(math.ceil(math.hypot(bx - ax, by - ay) / GRAIN)))
        out += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(1, n + 1)]
    return out


def faded(want, far, was, ramp, seeds=(None, None), pins=(None, None)):
    """The move of every piece of a path off its own place, with no jump: [steps to the right].
    want: the seat wanted per piece (None outside every corridor); far: metres along the path at
    each point; seeds: the move the line arrives with at the start and at the end of the path
    (from the piece of the line that meets it there). In a corridor a line has its seat in full.
    Out of it the move is worn away over `ramp` metres to a step: a line comes to its seat on
    the way in and gives it up on the way out, where it runs alone and the fade is not seen;
    fading inside the corridor would bend it towards the spine just before its track turns away."""
    n = len(want)
    mid = [(far[i] + far[i + 1]) / 2 for i in range(n)]
    move = [w - was if w is not None else None for w in want]

    def sweep(order, seed, edge):
        out, last = [0.0] * n, (seed, edge) if seed else None
        for i in order:
            if move[i] is not None:
                last = (move[i], mid[i])
            elif last is not None:
                left = abs(last[0]) - abs(mid[i] - last[1]) / ramp
                out[i] = math.copysign(left, last[0]) if left > 0 else 0.0
        return out
    forward, back = sweep(range(n), seeds[0], far[0]), sweep(range(n - 1, -1, -1), seeds[1], far[-1])
    out = [move[i] if move[i] is not None else max(forward[i], back[i], key=abs) for i in range(n)]
    # pins: the move the path must have at its start and at its end (None: free). Where a line
    # ends, or goes on under a name that is not seated, nothing carries the move on and it is
    # gone by the end (pin 0); where a track runs into another piece of the lines seated, part
    # way along it, it ends with what that piece has there. Otherwise the next piece would start
    # a step aside from where this one ends, which shows as a break.
    for i in range(n):
        for pin, room in ((pins[0], (mid[i] - far[0]) / ramp), (pins[1], (far[-1] - mid[i]) / ramp)):
            if pin is not None and abs(out[i] - pin) > room:
                out[i] = pin + math.copysign(room, out[i] - pin)
    return out


def seated(props, steps, urban):
    """The properties of a piece whose seat is `steps` to the right of its own direction (None: as it was)."""
    if steps is None:
        return props
    out = dict(props)
    guest = out.get("k") == "s"
    was = out.get("off", 1 if guest else 0)
    if steps == was:
        return props
    out["off"] = steps
    if urban and not guest:             # an urban line: the page takes the move off again when zoomed in
        out["goff"] = round((out.get("goff", 0) + steps - was) * EIGHTH) / EIGHTH
    if not urban:                       # a railway keeps its own width whichever side it is seated on
        out["lead"] = 1
    return out


def apply(features, listed, urban=False):
    """The features with the lines of the corridors seated. urban: these are urban lines (the
    metro file). Returns (features, receipt)."""
    lines = {}                          # line -> [[feature index, fine points, wanted, metres, was]]
    spines = {}                         # (feature, path of its line, line) -> the corridor that seats each piece
    for fi, f in enumerate(features):
        props, geometry = f["properties"], f["geometry"]
        mine = [c for c in listed if props.get("n") in c.seats]        # a line may run in several corridors
        if not mine:
            continue
        was = props.get("off", 1 if props.get("k") == "s" else 0)
        for co in (geometry["coordinates"] if geometry["type"] == "MultiLineString" else [geometry["coordinates"]]):
            if len(co) < 2:
                continue
            near = [c for c in mine if LineString([c.xy(p) for p in co]).distance(c.spine) <= c.reach + FADE * c.ramp]
            fine = finer(co, near) if near else [tuple(p) for p in co]
            want, far, spine_at, spread = [], [0.0], [], []
            for a, b in zip(fine, fine[1:]):
                target, spine, wide = None, None, None
                for corridor in near:               # the first corridor that seats the line here
                    where = corridor.along(corridor.xy(a), corridor.xy(b))
                    seat, share = corridor.seat(props["n"], where[0]) if where is not None else (0.0, 0.0)
                    if share:
                        target, spine = (seat if where[1] else -seat), corridor
                        break
                    where = corridor.along(corridor.xy(a), corridor.xy(b), loose=True)
                    seat, share = corridor.seat(props["n"], where[0]) if where is not None else (0.0, 0.0)
                    if share and wide is None:
                        wide = ((seat if where[1] else -seat), corridor)
                want.append(target)
                spine_at.append(spine)
                spread.append(wide)
                (ax, ay), (bx, by) = mine[0].xy(a), mine[0].xy(b)
                far.append(far[-1] + math.hypot(bx - ax, by - ay))
            i = 0                                   # between two pieces in a corridor, what has only spread stays in it
            while i < len(want):
                if want[i] is None and spread[i] is not None:
                    j = i
                    while j < len(want) and want[j] is None and spread[j] is not None:
                        j += 1
                    if 0 < i and j < len(want) and want[i - 1] is not None and want[j] is not None:
                        for k in range(i, j):
                            want[k], spine_at[k] = spread[k]
                    i = j
                else:
                    i += 1
            lines.setdefault(props["n"], []).append([fi, fine, want, far, was, mine[0].ramp])
            spines[(fi, len(lines[props["n"]]) - 1, props["n"])] = spine_at
    runs, receipt = {}, []              # feature index -> {seat: [coordinate lists]}
    paths = [row for rows in lines.values() for row in rows]
    ends = {}
    for k, (_, fine, _, _, _, _) in enumerate(paths):
        for side in (0, -1):
            ends.setdefault((round(fine[side][0], 6), round(fine[side][1], 6)), []).append((k, side))
    flat = [LineString([listed[0].xy(p) for p in fine]) for _, fine, _, _, _, _ in paths]
    pins = [[None, None] for _ in paths]
    hosts = {}                          # (path, end) -> (the path it runs into, the piece of it there)
    for meet in ends.values():
        if len(meet) > 1:
            continue
        k, side = meet[0]
        slot = 0 if side == 0 else 1
        pins[k][slot] = 0.0
        tip = Point(listed[0].xy(paths[k][1][side]))
        for j, g in enumerate(flat):
            if j != k and g.distance(tip) < MEET:
                metres = paths[j][3]
                at = g.project(tip)
                hosts[(k, slot)] = (j, min(max(sum(1 for d in metres if d <= at) - 1, 0), len(metres) - 2))
                break
    seeds = [[None, None] for _ in paths]

    def all_moves():
        return [faded(want, far, was, ramp, tuple(seeds[k]), tuple(pins[k])) for k, (_, _, want, far, was, ramp) in enumerate(paths)]
    moves = all_moves()
    for _ in range(6):                              # a seat fades on into the piece that follows, whatever its name
        changed = False
        for (k, slot), (j, i) in hosts.items():
            there = moves[j][i]
            way = flat[k].coords[1 if slot == 0 else -2], flat[k].coords[0 if slot == 0 else -1]
            ahead = flat[j].coords[i], flat[j].coords[i + 1]
            dot = (way[1][0] - way[0][0]) * (ahead[1][0] - ahead[0][0]) + (way[1][1] - way[0][1]) * (ahead[1][1] - ahead[0][1])
            # the same side of the track: written the other way, or arriving at the start, the sign is turned
            same = (dot >= 0) == (slot == 1)
            value = there if same else -there
            if abs((pins[k][slot] or 0.0) - value) > 0.05:
                pins[k][slot] = value
                changed = True
        for meet in ends.values():
            for k, side in meet:
                carried = moves[k][side] if moves[k] else 0.0
                for j, other in meet:
                    if j == k:
                        continue
                    arrives = carried if side != other else -carried        # a piece written the other way has the sign turned
                    slot = 0 if other == 0 else 1
                    if abs(arrives) > abs(seeds[j][slot] or 0.0) + 1e-9 and abs(arrives) > abs(moves[j][other]) + 0.05:
                        seeds[j][slot] = arrives
                        changed = True
        if not changed:
            break
        moves = all_moves()
    alongside = [by for rows in lines.values() for by in [None] * len(rows)]
    k = 0
    for name, rows in lines.items():
        for n in range(len(rows)):
            alongside[k] = spines[(rows[n][0], n, name)]
            k += 1
    for k, ((fi, fine, want, far, was, ramp), move) in enumerate(zip(paths, moves)):
        level = on_spine(fine, far, alongside[k])
        last = object()
        for i, m in enumerate(move):
            steps = round((was + m) * EIGHTH) / EIGHTH
            steps = None if steps == was else steps
            pa, pb = [round(fine[i][0], 7), round(fine[i][1], 7)], [round(fine[i + 1][0], 7), round(fine[i + 1][1], 7)]
            if pa == pb:
                continue
            qa, qb = level[i], level[i + 1]
            key = (steps, qa != pa or qb != pb)             # drawn elsewhere when zoomed out?
            mine = runs.setdefault(fi, {})
            if key == last and mine[key][-1][0][-1] == pa:
                mine[key][-1][0].append(pb)
                mine[key][-1][1].append(qb)
            else:
                mine.setdefault(key, []).append(([pa, pb], [qa, qb]))
            last = key
    out = []
    shape_of = lambda coords: {"type": "LineString", "coordinates": coords[0]} if len(coords) == 1 else {"type": "MultiLineString", "coordinates": coords}
    for fi, f in enumerate(features):
        if fi not in runs or set(runs[fi]) <= {(None, False)}:
            out.append(f)
            continue
        props = f["properties"]
        for steps, twice in sorted(runs[fi], key=lambda v: (v[0] is not None, v[0] or 0, v[1])):
            pieces = runs[fi][(steps, twice)]
            mine = seated(props, steps, urban)
            if not twice:
                out.append({**f, "properties": mine, "geometry": shape_of([near for near, _ in pieces])})
            else:
                out.append({**f, "properties": {**mine, "zn": 1}, "geometry": shape_of([near for near, _ in pieces])})
                out.append({**f, "properties": {**mine, "zf": 1}, "geometry": shape_of([far for _, far in pieces])})
            if steps is not None:
                receipt.append({"line": props["n"], "seat": steps,
                                "km": round(sum(LineString([listed[0].xy(p) for p in near]).length for near, _ in pieces) / 1000, 2)})
    return out, receipt


def on_spine(fine, far, by):
    """The points of a path as it is drawn zoomed out: on the path of the spine it is seated
    beside (the foot of each point on the spine), and coming off its own track onto it over
    BLEND metres where the seated stretch begins and ends."""
    n = len(fine)
    inside = [by[max(i - 1, 0)] or by[min(i, n - 2)] for i in range(n)]       # the corridor at each point
    if not any(inside):
        return [[round(x, 7), round(y, 7)] for x, y in fine]
    # Where a line passes from one corridor to the next (S2 线 from the 东北环线 to the 京包客专线) it is
    # on its own track too: the feet on two spines lie apart, and joining them would draw a
    # stroke across from one spine to the other.
    edge = [inside[i] is None or (i and inside[i - 1] is not None and inside[i - 1] is not inside[i])
            or (i < n - 1 and inside[i + 1] is not None and inside[i + 1] is not inside[i]) for i in range(n)]
    away = [math.inf] * n               # metres along the path to the nearest point not beside a spine
    reach = math.inf
    for i in range(n):
        reach = 0.0 if edge[i] else reach + (far[i] - far[i - 1] if i else 0.0)
        away[i] = reach
    reach = math.inf
    for i in range(n - 1, -1, -1):
        reach = 0.0 if edge[i] else reach + (far[i + 1] - far[i] if i < n - 1 else 0.0)
        away[i] = min(away[i], reach)
    out = []
    for i, (x, y) in enumerate(fine):
        c = inside[i]
        if c is None:
            out.append([round(x, 7), round(y, 7)])
            continue
        foot = c.spine.interpolate(c.spine.project(Point(c.xy((x, y)))))
        fx, fy = foot.x / (c.cos * M), foot.y / M
        w = min(1.0, away[i] / BLEND)
        out.append([round(x + (fx - x) * w, 7), round(y + (fy - y) * w, 7)])
    return out


LAYERS = ("rail_hsr.geojson", "rail_conv.geojson", "rail_shared.geojson")


def keep_base(root=ROOT):
    """Set aside the urban layer as scripts/process_osm.py wrote it, before any seat by hand:
    reseat() starts from it every time, so the list can be changed and applied again on its own."""
    base = root / "data" / "raw" / "seat_base"
    base.mkdir(parents=True, exist_ok=True)
    (base / "metro.geojson").write_bytes((root / "data" / "metro.geojson").read_bytes())


def reseat(root=ROOT):
    """Seat the urban lines of the corridors listed: data/metro.geojson from the layer set aside.
    The railways are seated where they are coloured by design speed (scripts/design_speeds.py)."""
    data = root / "data"
    base = data / "raw" / "seat_base" / "metro.geojson"
    if not base.exists():
        # data/metro.geojson already carries its seats: seated again it grew run after run
        # (1914 -> 2066 -> 2252 features, 2026-10-21)
        raise SystemExit("data/raw/seat_base/metro.geojson is missing: scripts/process_osm.py sets it aside; "
                         "to seat the railways alone: python3 scripts/seat_overrides.py rail")
    fc = json.loads(base.read_text())
    rail = [f for name in LAYERS for f in json.loads((data / name).read_text())["features"]]
    listed = corridors("cn", rail + fc["features"], data / "seat_overrides.json")
    feats, receipt = apply(fc["features"], listed, urban=True)
    (data / "metro.geojson").write_text(json.dumps({**fc, "features": feats}, ensure_ascii=False, separators=(",", ":")))
    told(receipt, "urban lines", len(listed))
    return receipt


def told(receipt, what, corridors_listed):
    by = {}
    for row in receipt:
        by[row["line"]] = by.get(row["line"], 0) + row["km"]
    print(f"seats by hand in {corridors_listed} corridors, {what}: " + (", ".join(f"{line} {km:.1f} km" for line, km in sorted(by.items())) or "none"), flush=True)


if __name__ == "__main__":
    # after the list has changed: the railways are coloured and seated again, then the urban lines
    # (python3 scripts/seat_overrides.py rail: the railways only, the urban layer as it is)
    import sys
    from design_speeds import apply as colour
    colour(ROOT)
    if sys.argv[1:] != ["rail"]:
        reseat(ROOT)
