"""Display-only, distance-parametrised offsets. Coordinates are never rewritten.

op is a JSON string (also legal as a vector-tile property):
{v: 1, base: number, ramps: [[lo, hi, before, after], ...], origin: number,
 direction: +1|-1, period: number|null}.
Distances use the same WGS84 coordinate arclength as side_by_side. Direction
converts a chain's right-hand seat to the original feature's right-hand seat.
The quintic ramps have zero first and second derivatives at both ends.
"""
import json
from collections import defaultdict


def source_identity(props):
    """Actual route identity when present; preserve the four-country legacy key."""
    if "network" not in props and "rid" not in props:
        return props.get("r"), props.get("n")
    return ("source", *(str(props.get(k, "")) for k in ("g", "r", "ct", "network", "rid", "n", "col")))


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * t * (10 + t * (-15 + 6 * t))


def profile(runs, ramp, closed=False):
    if not runs:
        return {"v": 1, "base": 0, "ramps": [], "origin": 0, "direction": 1, "period": None}
    cuts = []
    pairs = list(zip(runs, runs[1:]))
    length = runs[-1][1]
    if closed:
        pairs.append((runs[-1], [length, length + runs[0][1], *runs[0][2:]]))
    for a, b in pairs:
        if a[2] == b[2]:
            continue
        left = min(ramp, .45 * (a[1] - a[0]))
        right = min(ramp, .45 * (b[1] - b[0]))
        if a[3] < b[3]:
            lo, hi = a[1] - left, a[1]
        elif a[3] > b[3]:
            lo, hi = b[0], b[0] + right
        else:
            lo, hi = a[1] - left / 2, b[0] + right / 2
        if hi > lo:
            cuts.append([lo, hi, a[2], b[2]])
    return {"v": 1, "base": runs[0][2], "ramps": cuts, "origin": 0,
            "direction": 1, "period": length if closed else None}


def value_at(spec, distance):
    at = spec.get("origin", 0) + spec.get("direction", 1) * distance
    period = spec.get("period")
    if period:
        at %= period
    value = spec["base"]
    for lo, hi, before, after in spec["ramps"]:
        probes = (at, at + period) if period else (at,)
        for probe in probes:
            if lo <= probe <= hi:
                return spec.get("direction", 1) * (before + (after - before) * smooth((probe - lo) / (hi - lo)))
        if at >= hi:
            value = after
    return spec.get("direction", 1) * value


def encode(spec, origin=0, direction=1):
    return json.dumps({**spec, "origin": origin, "direction": direction}, separators=(",", ":"))


def chains(parts):
    """Join only exact, unambiguous endpoints of one identity, including rings.

    Returns [(coords, [(part_index, chain_start, direction), ...])]. No nearest
    neighbour matching, bridging, changing track selection, or moving endpoints.
    Junctions of degree >2 remain separate and are handled as display ports.
    """
    ends = defaultdict(list)
    for i, (key, _, geom) in enumerate(parts):
        for end in (0, -1):
            ends[(key, tuple(geom.coords[end]))].append((i, end))
    used, out = set(), []
    for seed in range(len(parts)):
        if seed in used:
            continue
        key = parts[seed][0]
        # Find an open endpoint before walking. Closed components retain their
        # original start; identity canonicalisation must not rewrite geometry.
        current, end, seen = seed, 0, set()
        while current not in seen:
            seen.add(current)
            port = ends[(key, tuple(parts[current][2].coords[end]))]
            if len(port) != 2:
                break
            other = next((p for p in port if p[0] != current), None)
            if other is None:
                break
            current, entered = other
            end = -1 if entered == 0 else 0
        if current in seen and len(ends[(key, tuple(parts[current][2].coords[end]))]) == 2:
            current, end = seed, 0
        coords, members, distance = [], [], 0.0
        while current not in used:
            used.add(current)
            geom = parts[current][2]
            direction = 1 if end == 0 else -1
            co = list(geom.coords) if direction == 1 else list(geom.coords)[::-1]
            members.append((current, distance, direction))
            coords.extend(co if not coords else co[1:])
            distance += geom.length
            port = ends[(key, tuple(co[-1]))]
            if len(port) != 2:
                break
            other = next((p for p in port if p[0] != current and p[0] not in used), None)
            if other is None:
                break
            current, end = other
        out.append((coords, members))
    return out


def display_sets(root, codes):
    """Read-only build input for the continuous display source.

    Keep all parts of an offset participant, including its zero-seat approach.
    This lets a full-path renderer join speed/class boundaries before any tile
    clipping. The original GeoJSON and PMTiles stay authoritative for routing.
    """
    sets = {}
    open_identities = []
    files = {"hsr": "rail_hsr", "conv": "rail_conv", "metro": "metro", "shared": "rail_shared"}
    for code in codes:
        for layer, native in files.items():
            if code != "cn" and layer not in ("conv", "metro"):
                continue
            name = native if code == "cn" else f"{code}_{'rail' if layer == 'conv' else layer}"
            file_path = root / "data" / (name + ".geojson")
            if not file_path.exists():
                continue
            features = json.loads(file_path.read_text())["features"]
            ambiguous = set()
            cities_path = root / "data" / (f"{code}_metro_cities.json" if code != "cn" else "metro_cities.json")
            if layer == "metro" and cities_path.exists():
                for city in json.loads(cities_path.read_text()):
                    counts = defaultdict(int)
                    for line in city["lines"]:
                        counts[(city["n"], line["n"], line.get("col"))] += 1
                    ambiguous.update(key for key, count in counts.items() if count > 1)
            blocked = {(f["properties"].get("ct"), f["properties"].get("n"), f["properties"].get("col"))
                       for f in features if (f["properties"].get("ct"), f["properties"].get("n"), f["properties"].get("col")) in ambiguous
                       and ("network" not in f["properties"] or "rid" not in f["properties"])}
            open_identities.extend({"country": code, "layer": layer, "ct": ct, "n": n, "col": col,
                                    "reason": "ambiguous source identity; missing network/rid"}
                                   for ct, n, col in sorted(blocked))
            features = [f for f in features if (f["properties"].get("ct"), f["properties"].get("n"),
                        f["properties"].get("col")) not in blocked]
            def identity(f):
                p = f["properties"]
                # Old archives lack network/rid. Include all colliding siblings
                # in the display sidecar, but never join their source identities.
                return tuple(p.get(k) for k in ("g", "ct", "n", "col", "zf", "zn"))
            affected = {identity(f) for f in features if f["properties"].get("op")
                        or f["properties"].get("off") or f["properties"].get("goff")}
            if affected:
                sets[f"{code}:{layer}"] = [f for f in features if identity(f) in affected]
    return sets, open_identities
