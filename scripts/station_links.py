"""The fast lines that run past a railway station without stopping there.

The routing network links a railway station to the track of every line within a few hundred metres
of its dot. A high-speed line on a viaduct beside a station of the old line is then a line "of"
that station, and a route changes trains where no train stops (新市 on Taiwan's 縱貫線, 250 m from
the 台灣高速鐵路, reported 2026-10-13). Two kinds of evidence say that a fast line passes:

  the track: the line is not at the dot (more than ON_LINE away), and it has no turnout near the
      station (plain running line: the tracks of a station branch off the line), or another
      station, of another name, lies clearly nearer to it (六家 beside the 高鐵新竹 station);
  the timetable (data/trains/index.json, mainland China only): the station has trains, and none of
      the kinds that run on a dedicated high-speed line (G, D, C, S) stops there.

The rule only takes links away, and only where the two do not contradict each other: where the
track says the fast lines pass and the timetable says fast trains stop (the dot is far from the
platforms, or OSM has no station tracks there), the station keeps its links as they were. A
station never loses its last line. Conventional lines are not judged: nothing here tells a
passing freight line from one whose trains stop.

Fast trains also run on old lines (the D trains of the 陇海线 at 咸阳), so "fast trains stop here"
does not always mean that the fast line beside the station is theirs. Such a station, once looked
up, is listed in data/rail_stop_overrides.json with its source: no fast line stops there.
"""
import math
from collections import defaultdict

FAST = ("hsr350", "hsr250", "hsr200")
DEDICATED = ("hsr350", "hsr250")     # passenger lines: only G, D, C and S trains run on them
FAST_TRAINS = ("G", "D", "C", "S")
M = 111320.0                         # metres in a degree of latitude
ON_LINE = 60.0                       # metres: the dot is on the line
MARGIN = 60.0                        # metres: another station is "clearly nearer" by more than this
TURNOUT_R = 0.010                    # degrees (~1.1 km): the throat of a station lies this close to its dot
RIVAL_R = 0.010                      # degrees: another station this close competes for the line
SAME_STATION_R = 0.03                # degrees (~3 km): a timetable stop of the same name this close is the station
CELL = 0.01


def pack(c):
    return (round(c[0] * 1e6) << 32) | (round(c[1] * 1e6) & 0xFFFFFFFF)


def turnouts(tracks):
    """The places where track branches, from the coordinates of all railway track (running lines,
    sidings, yards): a point where three or more tracks end, or that lies inside one track and
    on another. Two tracks that only meet end to end are one track drawn in two pieces."""
    ends, inner = defaultdict(int), defaultdict(int)
    for co in tracks:
        if len(co) < 2:
            continue
        ends[pack(co[0])] += 1
        ends[pack(co[-1])] += 1
        for c in co[1:-1]:
            inner[pack(c)] += 1
    return {q for q, n in ends.items() if n >= 3 or q in inner} | {q for q, n in inner.items() if n >= 2}


def fast_stops(index):
    """From the train data: (name, lon, lat, do fast trains stop here?) for every stop that has trains."""
    kinds = defaultdict(set)
    for trip in index.get("trips", ()):
        for stop in trip["stops"]:
            kinds[stop[0]].add(trip.get("type"))
    return [(s["name"], s["lon"], s["lat"], bool(kinds[i] & set(FAST_TRAINS)))
            for i, s in enumerate(index.get("stops", ())) if kinds[i]]


LISTED_R = 0.005                     # degrees: a listed station is the one of that name this close


def passing(stations, ways, turn, timetable=(), reach=0.007, listed=()):
    """stations: [(name, lon, lat)]; ways: [(class, line, coordinates)] of railway track; turn: the
    packed turnouts; timetable: fast_stops(); listed: [(name, lon, lat)] of the stations looked
    up, where no fast line stops. Returns ({station index: the fast lines to leave unlinked},
    rows for the report). A listed station that is not found, or found twice, is an error."""
    found = {entry: [i for i, (name, x, y) in enumerate(stations)
                     if name == entry[0] and math.hypot(x - entry[1], y - entry[2]) <= LISTED_R] for entry in listed}
    wrong = {entry[0]: len(hits) for entry, hits in found.items() if len(hits) != 1}
    if wrong:
        raise ValueError(f"listed stations not found exactly once: {wrong}")
    looked_up = {hits[0] for hits in found.values()}
    cells = set()
    for _, x, y in stations:
        cx, cy = int(x // CELL), int(y // CELL)
        cells.update((cx + dx, cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    near = defaultdict(list)
    for wi, (_, _, co) in enumerate(ways):
        for x, y in co:
            cell = (int(x // CELL), int(y // CELL))
            if cell in cells:
                near[cell].append((x, y, wi))
    timed = defaultdict(list)
    for name, x, y, fast in timetable:
        timed[name].append((x, y, fast))

    def around(x, y, table):
        cx, cy = int(x // CELL), int(y // CELL)
        return (item for dx in (-1, 0, 1) for dy in (-1, 0, 1) for item in table.get((cx + dx, cy + dy), ()))

    lines_at = []                # per station: line -> [distance in metres, turnout near?, class]
    for _, x, y in stations:
        cosy = math.cos(math.radians(y))
        best = {}
        for vx, vy, wi in around(x, y, near):
            d = math.hypot((vx - x) * cosy, vy - y)
            if d > max(reach, TURNOUT_R):
                continue
            cls, line, _ = ways[wi]
            row = best.setdefault(line, [float("inf"), False, cls])
            if d * M < row[0]:
                row[0], row[2] = d * M, cls
            if d <= TURNOUT_R and pack((vx, vy)) in turn:
                row[1] = True
        lines_at.append({line: row for line, row in best.items() if row[0] <= reach * M})
    grid = defaultdict(list)
    for i, (_, x, y) in enumerate(stations):
        grid[(int(x // CELL), int(y // CELL))].append(i)

    skip, rows = {}, []
    for i, (name, x, y) in enumerate(stations):
        lines = lines_at[i]
        fast = sorted(line for line, row in lines.items() if row[2] in FAST)
        if not fast:
            continue
        cosy = math.cos(math.radians(y))
        why = {line: "looked up: no fast line stops here" for line in fast} if i in looked_up else {}
        for line in fast:
            d, turnout, _ = lines[line]
            if d <= ON_LINE or line in why:
                continue
            if not turnout:
                why[line] = "no turnout by the station"
                continue
            rival = min((lines_at[j][line][0], stations[j][0]) for j in list(around(x, y, grid)) + [i]
                        if (j == i or (stations[j][0] != name and line in lines_at[j]
                                       and math.hypot((stations[j][1] - x) * cosy, stations[j][2] - y) <= RIVAL_R)))
            if rival[0] < d - MARGIN:
                why[line] = f"{rival[1]} is nearer to it"
        stops = [fast_here for sx, sy, fast_here in timed.get(name, ())
                 if math.hypot((sx - x) * cosy, sy - y) <= SAME_STATION_R]
        if stops and any(stops) and all(line in why for line in fast) and i not in looked_up:
            for line in fast:                      # fast trains stop, yet the track finds no fast line: left as it was
                rows.append({"station": name, "at": [x, y], "line": line, "metres": round(lines[line][0]),
                             "kept": "fast trains stop here by the timetable; track: " + why[line]})
            continue
        if stops and not any(stops):
            for line in fast:
                if lines[line][2] in DEDICATED:
                    why.setdefault(line, "no fast train stops here by the timetable")
        if why and len(why) == len(lines):         # never the last line: the nearest stays
            del why[min(why, key=lambda line: lines[line][0])]
        if why:
            skip[i] = set(why)
            rows += [{"station": name, "at": [x, y], "line": line, "class": lines[line][2],
                      "metres": round(lines[line][0]), "passes": reason} for line, reason in sorted(why.items())]
    return skip, rows
