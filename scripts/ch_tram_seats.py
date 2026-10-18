"""Bounded, source-authorised Swiss tram seating and its isolated review runner."""
import argparse
import copy
import hashlib
import json
import math
import pickle
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from shapely.affinity import scale as geo_scale
from shapely.geometry import LineString, Point, shape
from shapely.ops import linemerge, substring, unary_union
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from side_by_side import side_by_side

CT = {"zurich": "\u82cf\u9ece\u4e16", "basel": "\u5df4\u585e\u5c14",
      "bern": "\u4f2f\u5c14\u5c3c", "geneva": "\u65e5\u5185\u74e6",
      "lausanne": "\u6d1b\u6851"}
CONFIG = ROOT / "data/ch_tram_seats.json"
PROFILES = ROOT / "data/ch_tram_profiles.json"
SAMPLE_M = 10
GRAIN = 1 / 16


def source_identity(row):
    return ("urban", "ch", row["ct"], row["network"], row["name"],
            row["col"], tuple(sorted(row["relations"])))


def feature_key(props):
    return props.get("ct"), props.get("n"), props.get("col")


def resolve_source(props, sources):
    """A full network/rid selector must match one actual source row, not a union."""
    candidates = [row for row in sources if feature_key(props) ==
                  (row["ct"], row["name"], row["col"])]
    if "network" in props:
        candidates = [row for row in candidates if row["network"] == props["network"]]
    if "rid" in props:
        raw = props["rid"]
        try:
            rids = sorted(int(value) for value in
                          (raw.split(",") if isinstance(raw, str) else raw))
        except (TypeError, ValueError):
            return None
        candidates = [row for row in candidates if sorted(row["relations"]) == rids]
    return candidates[0] if len(candidates) == 1 else None


def source_signature(sources):
    rows = [{**s, "relations": sorted(s["relations"]), "way_ids": sorted(s["way_ids"])}
            for s in sources]
    return digest(sorted(rows, key=source_identity))


def way_signature(ways, sources):
    wids = sorted({w for s in sources for w in s["way_ids"]})
    rows = []
    for wid in wids:
        tags, co = ways[wid]
        forward = [list(p) for p in co]
        rows.append([wid, tags, min(forward, forward[::-1])])
    return digest(rows)


@dataclass
class Chain:
    corridor: dict
    source: dict
    geometry: LineString
    seats: dict
    support: object
    owners: dict


def metric(g, latitude, inverse=False):
    x, y = 111320 * math.cos(math.radians(latitude)), 111320
    return geo_scale(g, xfact=1 / x if inverse else x,
                     yfact=1 / y if inverse else y, origin=(0, 0))


def tangent(g, at):
    a = g.interpolate(max(0, at - 5))
    b = g.interpolate(min(g.length, at + 5))
    dx, dy = b.x - a.x, b.y - a.y
    norm = math.hypot(dx, dy)
    return (dx / norm, dy / norm) if norm else (0, 0)


def compile_corridors(config, ways, sources):
    """Every service must own every configured way; proximity never grants ownership."""
    if config.get("version") != 1 or config.get("country") != "ch":
        raise ValueError("Expected Swiss seat configuration version 1")
    identities = defaultdict(list)
    for source in sources:
        identities[(source["ct"], source["name"])].append(source)
    chains, ids = [], set()
    for corridor in config["corridors"]:
        cid = corridor["id"]
        if cid in ids:
            raise ValueError(f"Duplicate corridor {cid}")
        ids.add(cid)
        if corridor.get("enabled") is False:
            if not corridor.get("open_reason"):
                raise ValueError(f"Missing disabled-corridor reason: {cid}")
            continue
        order = corridor["order"]
        if len(order) < 2 or len(set(order)) != len(order):
            raise ValueError(f"Invalid service order: {cid}")
        if not corridor.get("why") or not corridor.get("asked"):
            raise ValueError(f"Missing manual authority: {cid}")
        reach, ramp = corridor["reach_m"], corridor["ramp_m"]
        if not 0 < reach <= 8 or not 0 < ramp <= 500:
            raise ValueError(f"Unbounded reach or ramp: {cid}")
        for row_index, row in enumerate(corridor["chains"]):
            members = row["lines"]
            if len(set(members)) != len(members) or len(members) < 2 or not set(members) <= set(order):
                raise ValueError(f"Invalid chain membership: {cid}")
            wids = row["way_ids"]
            if not wids or len(set(wids)) != len(wids):
                raise ValueError(f"Invalid source way list: {cid}")
            bound_owners = {}
            for member in members:
                owners = identities.get((corridor["ct"], member), [])
                selector = corridor.get("source_selectors", {}).get(member)
                if selector:
                    owners = [owner for owner in owners
                              if owner["network"] == selector["network"]
                              and sorted(owner["relations"]) == sorted(selector["relations"])]
                # Ambiguous legacy display rows remain OPEN. Never combine
                # pieces owned by different networks to prove one service.
                owners = [owner for owner in owners if set(wids) <= set(owner["way_ids"])]
                if not owners:
                    raise ValueError(f"Unproven common source: {cid}/{member}")
                bound_owners[member] = {source_identity(owner) for owner in owners}
            if any(w not in ways or ways[w][0].get("service") for w in wids):
                raise ValueError(f"Missing way or service track: {cid}")
            raw = unary_union([LineString(ways[w][1]) for w in wids])
            raw = linemerge(raw) if raw.geom_type == "MultiLineString" else raw
            if raw.geom_type != "LineString" or raw.is_empty or not raw.is_simple:
                raise ValueError(f"Branched or non-simple chain: {cid}")
            latitude = sum(p[1] for p in (row["from"], row["to"])) / 2
            g = metric(raw, latitude)
            start, end = metric(Point(row["from"]), latitude), metric(Point(row["to"]), latitude)
            if g.distance(start) > 1 or g.distance(end) > 1:
                raise ValueError(f"Stale chain endpoints: {cid}")
            # Membership changes can split a way at an interior position. Crop
            # the authorised raw chain; never extend it to a nearby endpoint.
            a, b = g.project(start), g.project(end)
            if abs(a - b) < 1:
                raise ValueError(f"Degenerate chain: {cid}")
            g = substring(g, a, b)
            if Point(g.coords[0]).distance(start) > 1 or Point(g.coords[-1]).distance(end) > 1:
                raise ValueError(f"Stale chain endpoints: {cid}")
            axis = (corridor.get("chain_directions", [])[row_index]
                    if corridor.get("chain_directions") else corridor.get("direction"))
            if axis:
                reference = metric(LineString([axis["from"], axis["to"]]), latitude)
                dx = reference.coords[-1][0] - reference.coords[0][0]
                dy = reference.coords[-1][1] - reference.coords[0][1]
                gx = g.coords[-1][0] - g.coords[0][0]
                gy = g.coords[-1][1] - g.coords[0][1]
                norm = math.hypot(dx, dy) * math.hypot(gx, gy)
                if not norm:
                    raise ValueError(f"Degenerate fixed direction: {cid}")
                agreement = (dx * gx + dy * gy) / norm
                if abs(agreement) < 0.5:
                    raise ValueError(f"Chain conflicts with fixed direction: {cid}")
                if agreement < 0:
                    g = LineString(list(g.coords)[::-1])
            # Fixed corridor seats avoid re-ordering when a service branches
            # off, while keeping the bundle centred on its source track.
            centre = (len(order) - 1) / 2
            seats = {name: order.index(name) - centre for name in members}
            geographic = substring(raw, raw.project(Point(row["from"])), raw.project(Point(row["to"])))
            if metric(Point(row["from"]), latitude).distance(Point(g.coords[0])) > 1e-6:
                geographic = LineString(list(geographic.coords)[::-1])
            chains.append(Chain(corridor, {**row, "latitude": latitude,
                                          "coordinates": [list(co) for co in geographic.coords]}, g,
                                seats, g.buffer(reach), bound_owners))
    return chains


def validate_sources(extract, sources, config):
    ways = {wid: (tags, co) for wid, tags, co in extract["ways"]}
    if config.get("source_manifest_sha256") and digest(extract["sources"]) != config["source_manifest_sha256"]:
        raise ValueError("Source manifest differs from the frozen manual configuration")
    if config.get("source_rows_sha256") and source_signature(sources) != config["source_rows_sha256"]:
        raise ValueError("Source identities or membership differ from the manual configuration")
    if config.get("source_ways_sha256") and way_signature(ways, sources) != config["source_ways_sha256"]:
        raise ValueError("Source way geometry or tags differ from the manual configuration")
    if len({source_identity(row) for row in sources}) != len(sources):
        raise ValueError("Duplicate actual source identity")
    return ways


def profile_value(spec, distance_m):
    """Unquantised seat units; a renderer applies zoom/width once, not sh twice."""
    if not 0 <= distance_m <= spec["length_m"]:
        raise ValueError("Profile distance outside its bounded source path")
    if spec["kind"] == "shared":
        return {"soff": spec["seat"], "sh": 1.0}
    t = min(1.0, distance_m / spec["ramp_m"])
    weight = 1 - t * t * t * (10 + t * (-15 + 6 * t))
    return {"soff": spec["seat"] * weight, "sh": 0.0}


def continuous_config(config):
    """Activate the five authorised local candidates only in the new review path."""
    active = copy.deepcopy(config)
    for corridor in active["corridors"]:
        if corridor.get("continuous_candidate"):
            corridor["enabled"] = True
        if corridor["ct"] == CT["bern"]:
            corridor["order"] = ["Tram 6", "Tram 7", "Tram 8", "Tram 9"]
    return active


def selected_display(extract, sources):
    """Deterministic actual one_track result and its own production display path."""
    from process_jp import TOL, rounded, runs_of
    from single_track import one_track, stitch
    ways = {wid: co for wid, _, co in extract["ways"]}
    out = {}
    for owner in sources:
        light = owner["route_kinds"].get("subway", 0) < sum(
            v for k, v in owner["route_kinds"].items() if k != "subway")
        if not light:
            continue
        kept = one_track(runs_of([ways[wid] for wid in sorted(owner["way_ids"])]))
        native = rounded(stitch(kept, bends=True), TOL["light"], (6, 6, 0.00004), adaptive=True)
        out[source_identity(owner)] = {"kept": kept, "native": native}
    return out


def apply_ch_continuous_seats(features, extract, *, sources, metadata, config=None,
                              selected=None, review=False):
    """Local dry-run hook: exact source/selected proof, then bounded display mapping.

    Output op uses the generic renderer's WGS84 coordinate arclength, not metres.
    Source geometry and each input coordinate are retained. No proximity test can
    authorise sharing: intervals first intersect actual selected original edges.
    """
    from continuous_offset import encode, profile, value_at
    config = json.loads(CONFIG.read_text()) if config is None else config
    if not review:
        raise ValueError("Continuous Swiss seats require an isolated review dry-run")
    active = continuous_config(config)
    sidecar = build_ch_seat_profiles(extract, sources, metadata, active, review=True)
    selected = selected_display(extract, sources) if selected is None else selected
    out, ledger = [], []
    for fi, feature in enumerate(features):
        props = feature["properties"]
        if props.get("g") != "ch" or props.get("jk") != "urban":
            out.append(feature)
            continue
        owner = resolve_source(props, sources)
        if owner is None:
            out.append(feature)
            ledger.append({"feature": fi, "status": "OPEN_AMBIGUOUS_SOURCE"})
            continue
        owner_key = source_identity(owner)
        actual = selected.get(owner_key)
        if not actual:
            out.append(feature)
            ledger.append({"feature": fi, "status": "OPEN_MISSING_SELECTED"})
            continue
        kept = unary_union(actual["kept"])
        applicable = [p for p in sidecar["profiles"]
                      if tuple(p["identity"]) == owner_key and p["kind"] == "shared"]
        paths = [LineString(co) for co in actual["native"]]
        native_specs = []
        for native in paths:
            intervals = []
            for spec in applicable:
                # Intersection is on raw selected edges, never fitted neighbours.
                common = kept.intersection(LineString(spec["coordinates"]))
                # compile_corridors already proves every listed owner contains
                # every configured source way. Only this owner's selected edge
                # is needed to bind its display path; the peers may select the
                # opposite track of the same two-track corridor.
                pieces = [g for g in (common.geoms if hasattr(common, "geoms") else [common])
                          if g.geom_type == "LineString" and g.length > 1e-8]
                for piece in pieces:
                    lo, hi = native.project(Point(piece.coords[0])), native.project(Point(piece.coords[-1]))
                    if abs(hi - lo) < 1e-8:
                        continue
                    mapped = substring(native, min(lo, hi), max(lo, hi))
                    if mapped.hausdorff_distance(piece) > .00012:
                        continue
                    reference = LineString(spec["coordinates"])
                    source_a = reference.project(Point(piece.coords[0]))
                    source_b = reference.project(Point(piece.coords[-1]))
                    sign = 1 if (hi - lo) * (source_b - source_a) > 0 else -1
                    intervals.append((min(lo, hi), max(lo, hi), spec["seat"] * sign,
                                      spec["corridor"], spec["way_ids"]))
            cuts = sorted({0.0, native.length} | {v for row in intervals for v in row[:2]})
            runs, records = [], []
            for lo, hi in zip(cuts, cuts[1:]):
                middle = (lo + hi) / 2
                hits = [r for r in intervals if r[0] <= middle <= r[1]]
                seats = {r[2] for r in hits}
                if len(seats) > 1:
                    ledger.append({"feature": fi, "status": "OPEN_FIXED_SEAT_CONFLICT",
                                   "identity": owner_key, "from_deg": lo, "to_deg": hi,
                                   "corridors": sorted({r[3] for r in hits})})
                    seat, count = 0, 1
                else:
                    seat, count = (next(iter(seats)), 2) if hits else (0, 1)
                if runs and runs[-1][2:] == [seat, count]:
                    runs[-1][1] = hi
                else:
                    runs.append([lo, hi, seat, count])
                if hits and len(seats) == 1:
                    records.append({"from_deg": lo, "to_deg": hi, "seat": seat,
                                    "corridors": sorted({r[3] for r in hits}),
                                    "way_ids": sorted({w for r in hits for w in r[4]})})
            # 1200m per seat step at low zoom; profile ramps live on independent
            # approaches, while the full shared interval retains its fixed seat.
            ramp = 1200 / 111320
            native_specs.append((native, profile(runs, ramp, closed=native.is_ring), records))
        proposed, bound = [], False
        for pi, co in enumerate(coordinates(feature)):
            part = LineString(co)
            matches = []
            for native, op, records in native_specs:
                a, b = native.project(Point(co[0])), native.project(Point(co[-1]))
                if list(native.coords) == list(part.coords):
                    a, b = 0, native.length
                elif list(native.coords)[::-1] == list(part.coords):
                    a, b = native.length, 0
                if native.is_ring and part.is_ring and abs(native.length - part.length) < 1e-10:
                    if list(native.coords) == list(part.coords):
                        a, b = 0, native.length
                    elif list(native.coords)[::-1] == list(part.coords):
                        a, b = native.length, 0
                candidate = substring(native, a, b)
                # side_by_side slices this same path; numerical tolerance only.
                if (candidate.geom_type == "LineString"
                        and candidate.hausdorff_distance(part) < 1e-10
                        and abs(candidate.length - part.length) < 1e-10):
                    matches.append((native, op, records, a, b))
            if len(matches) != 1:
                proposed.append({**feature, "geometry": {"type": "LineString", "coordinates": co}})
                ledger.append({"feature": fi, "part": pi, "status": "OPEN_NATIVE_PATH_BINDING",
                               "identity": owner_key})
                continue
            native, op, records, a, b = matches[0]
            if not records:
                proposed.append({**feature, "geometry": {"type": "LineString", "coordinates": co}})
                continue
            direction = 1 if b > a else -1
            p = {k: v for k, v in props.items() if k not in ("off", "op", "ap", "sh", "goff", "lead", "bn")}
            p.update(op=encode(op, a, direction), off=value_at(
                {**op, "origin": a, "direction": direction}, part.length / 2), chseat=2)
            proposed.append({**feature, "properties": p,
                             "geometry": {"type": "LineString", "coordinates": co}})
            bound = True
            ledger.append({"feature": fi, "part": pi, "status": "BOUND_SELECTED_ORIGINAL_EDGES",
                           "identity": owner_key, "geometry_sha256": digest(co),
                           "selected_sha256": digest([list(g.coords) for g in actual["kept"]]),
                           "native_sha256": digest(actual["native"]), "op": json.loads(p["op"]),
                           "records": records, "direction": direction})
        out.extend(proposed if bound else [feature])
    return out, ledger


def apply_ch_verified_profiles(features, *, sources, profiles=None):
    """Apply reviewed continuous profiles to exact current display geometry.

    The compact profile file is generated from source-authorised selected
    edges. Every configured profile must match once; there is no spatial
    fallback and no automatic acceptance after a source or geometry change.
    """
    from continuous_offset import encode, value_at
    if not any(f["properties"].get("g") == "ch"
               and f["properties"].get("jk") == "urban" for f in features):
        return features, []
    profiles = json.loads(PROFILES.read_text()) if profiles is None else profiles
    if profiles.get("version") != 1 or profiles.get("country") != "ch":
        raise ValueError("Expected Swiss continuous profile version 1")
    if source_signature(sources) != profiles.get("source_rows_sha256"):
        raise ValueError("Swiss continuous profiles do not match actual source rows")
    configured = {}
    for row in profiles.get("profiles", []):
        raw = row.get("identity")
        if not isinstance(raw, list) or len(raw) != 7 or not isinstance(raw[-1], list):
            raise ValueError("Invalid Swiss profile identity")
        owner = (*raw[:-1], tuple(raw[-1]))
        key = owner, row.get("geometry_sha256")
        if key in configured:
            raise ValueError("Duplicate Swiss continuous profile")
        configured[key] = row
    used, out, ledger = set(), [], []
    for index, feature in enumerate(features):
        props = feature["properties"]
        if props.get("g") != "ch" or props.get("jk") != "urban":
            out.append(feature)
            continue
        owner = resolve_source(props, sources)
        geom = feature["geometry"]
        if owner is None or geom.get("type") != "LineString":
            out.append(feature)
            continue
        key = source_identity(owner), digest(geom["coordinates"])
        row = configured.get(key)
        if row is None:
            out.append(feature)
            continue
        op = row["op"]
        line = LineString(geom["coordinates"])
        p = {k: v for k, v in props.items()
             if k not in ("off", "op", "ap", "sh", "goff", "lead", "bn")}
        p.update({"op": encode(op, op.get("origin", 0), op.get("direction", 1)),
                  "off": value_at(op, line.length / 2), "chseat": 2})
        out.append({**feature, "properties": p})
        used.add(key)
        ledger.append({"feature": index, "identity": list(key[0]),
                       "geometry_sha256": key[1],
                       "selected_sha256": row["selected_sha256"],
                       "native_sha256": row["native_sha256"],
                       "status": "VERIFIED_CONTINUOUS_PROFILE"})
    missing = set(configured) - used
    if missing:
        raise ValueError(f"{len(missing)} Swiss continuous profiles no longer match display geometry")
    return out, ledger


def build_ch_seat_profiles(extract, sources, metadata, config=None, *, review=False):
    """Source-only profiles. Never infer selected/display ownership by distance.

    Shared chains hold full seats at their ports. Only an exact OSM node with
    one same-service continuation can inherit a seat onto an independent path.
    Multiway branches, incompatible fixed-side seats and missing node evidence
    remain OPEN. This sidecar neither edits features nor enables publication.
    """
    config = json.loads(CONFIG.read_text()) if config is None else config
    if config.get("publication_state") == "review-only" and not review:
        raise ValueError("Swiss tram seats are review-only; production visual acceptance is incomplete")
    if not config.get("raw_metadata_sha256") or digest(metadata) != config["raw_metadata_sha256"]:
        raise ValueError("Missing or stale pinned raw node metadata")
    ways = validate_sources(extract, sources, config)
    if any(not c.get("direction") for c in config["corridors"] if c.get("enabled") is not False):
        raise ValueError("Continuous seating requires an explicit fixed corridor direction")
    chains = compile_corridors(config, ways, sources)
    raw = metadata["ways"]
    bindings = [[wid, raw.get(str(wid), {}).get("nodes"), ways[wid][1]]
                for wid in sorted({w for owner in sources for w in owner["way_ids"]})]
    if digest(bindings) != config.get("raw_node_coordinates_sha256"):
        raise ValueError("Missing or stale node-to-coordinate binding")
    node_coords, owner_ports = {}, defaultdict(list)
    for owner in sources:
        for wid in owner["way_ids"]:
            row = raw.get(str(wid))
            if row is None or len(row["nodes"]) != len(ways[wid][1]):
                raise ValueError(f"Missing node/coordinate binding: {wid}")
            for node, co in zip(row["nodes"], ways[wid][1]):
                if node in node_coords and node_coords[node] != tuple(co):
                    raise ValueError(f"Conflicting coordinates for actual node: {node}")
                node_coords[node] = tuple(co)
            for end in (0, -1):
                owner_ports[(source_identity(owner), row["nodes"][end])].append((wid, end))
    shared_ports, profiles, ledger = defaultdict(list), [], []
    for ci, chain in enumerate(chains):
        row = chain.source
        geo = LineString(row["coordinates"])
        # Determine the original configured endpoint, without rounding a fitted
        # coordinate into an OSM node. Interior cuts have no invented node.
        forward = metric(Point(row["from"]), row["latitude"]).distance(Point(chain.geometry.coords[0])) < 1e-6
        ends = [row["from"], row["to"]] if forward else [row["to"], row["from"]]
        for name, seats in chain.seats.items():
            for owner_key in sorted(chain.owners[name]):
                pid = f"{chain.corridor['id']}:{ci}:{digest(owner_key)[:16]}"
                spec = {"id": pid, "kind": "shared", "identity": owner_key,
                        "corridor": chain.corridor["id"], "way_ids": row["way_ids"],
                        "coordinates": [list(co) for co in geo.coords],
                        "length_m": chain.geometry.length, "seat": seats,
                        "ramp_m": chain.corridor["ramp_m"], "ports": []}
                profiles.append(spec)
                for end, co in enumerate(ends):
                    nodes = {node for wid in row["way_ids"]
                             for node, point in zip(raw[str(wid)]["nodes"], ways[wid][1])
                             if tuple(point) == tuple(co)}
                    node = next(iter(nodes)) if len(nodes) == 1 else None
                    port = {"node": node, "at": co, "end": end, "status": "OPEN_NO_NODE"}
                    spec["ports"].append(port)
                    if node is not None:
                        shared_ports[(owner_key, node)].append((spec, port, chain))
                    else:
                        ledger.append({"profile": pid, **port})
    claimed = set()
    for (owner_key, node), peers in sorted(shared_ports.items()):
        configured = {wid for spec, _, _ in peers for wid in spec["way_ids"]}
        continuations = [(wid, end) for wid, end in owner_ports[(owner_key, node)]
                         if wid not in configured]
        # A peer's end is incoming and its start outgoing. Their signed seats
        # must agree in a common traversal direction, including reversed chains.
        signed = [spec["seat"] * (1 if port["end"] else -1) for spec, port, _ in peers]
        shared_join = (len(peers) == 2 and not continuations
                       and peers[0][1]["end"] != peers[1][1]["end"]
                       and abs(signed[0] + signed[1]) < 1e-12)
        status = "INHERITED_SHARED_PORT" if shared_join else "OPEN_SHARED_PORT_CONFLICT"
        if len(peers) == 1:
            status = "OPEN_NO_CONTINUATION" if not continuations else "OPEN_BRANCH_AMBIGUOUS"
            if len(continuations) == 1:
                spec, port, chain = peers[0]
                wid, end = continuations[0]
                def structure(w):
                    tags = raw[str(w)]["tags"]
                    return tuple(tags.get(key, default) for key, default in
                                 (("layer", "0"), ("gauge", None), ("bridge", "no"), ("tunnel", "no")))
                seed_level = {structure(w) for w in spec["way_ids"] if node in raw[str(w)]["nodes"]}
                level = structure(wid)
                if seed_level != {level} or raw[str(wid)]["tags"].get("service"):
                    status = "OPEN_LEVEL_CONFLICT"
                else:
                    selected, co_out, visited = [], [], set()
                    current = (wid, end)
                    while current is not None:
                        next_wid, entered = current
                        if next_wid in visited or (owner_key, next_wid) in claimed:
                            status = "OPEN_CONTINUATION_COLLISION"
                            break
                        visited.add(next_wid)
                        points = list(ways[next_wid][1])
                        if entered == -1:
                            points.reverse()
                        selected.append(next_wid)
                        co_out.extend(points if not co_out else points[1:])
                        path_m = metric(LineString(co_out), chain.source["latitude"])
                        if path_m.length >= spec["ramp_m"]:
                            status = "INHERITED_INDEPENDENT_PORT"
                            break
                        next_node = raw[str(next_wid)]["nodes"][-1 if entered == 0 else 0]
                        if (owner_key, next_node) in shared_ports:
                            status = "OPEN_SHORT_SHARED_CONNECTOR"
                            break
                        next_options = [(w, e) for w, e in owner_ports[(owner_key, next_node)]
                                        if w != next_wid]
                        if not next_options:
                            status = "INHERITED_TERMINAL_PORT"
                            break
                        if (len(next_options) != 1 or structure(next_options[0][0]) != level
                                or raw[str(next_options[0][0])]["tags"].get("service")):
                            status = "OPEN_BRANCH_OR_LEVEL_CHANGE"
                            break
                        current = next_options[0]
                    if status.startswith("INHERITED_"):
                        claimed.update((owner_key, w) for w in selected)
                        profiles.append({"id": spec["id"] + f":branch:{node}",
                                         "kind": "independent", "identity": owner_key,
                                         "corridor": spec["corridor"], "way_ids": selected,
                                         "coordinates": [list(co) for co in co_out],
                                         "length_m": path_m.length,
                                         "seat": spec["seat"] * (1 if port["end"] else -1),
                                         "ramp_m": min(spec["ramp_m"], path_m.length),
                                         "inherited_node": node, "ports": []})
        for spec, port, _ in peers:
            port["status"] = status
            ledger.append({"profile": spec["id"], **port,
                           "continuation_way_ids": [wid for wid, _ in continuations]})
    return {"version": 1, "country": "ch", "publication_state": "review-only",
            "distance_units": "local-metric-metres", "seat_units": "renderer-slot",
            "geometry_mutated": False, "source_rows_sha256": source_signature(sources),
            "raw_metadata_sha256": digest(metadata), "profiles": profiles,
            "display_binding": "REQUIRES_ACTUAL_SELECTED_BOUNDED_ORIGINAL_EDGES",
            "ports": ledger}


def apply_ch_tram_seats(features, extract, config=None, sources=None, *, review=False):
    """Local post-side_by_side overlay; no geometry fitting or other-country changes."""
    config = json.loads(CONFIG.read_text()) if config is None else config
    if sources is None:
        raise ValueError("Pass the actual urban source rows; implicit geometry replay is forbidden")
    if config.get("publication_state") == "review-only" and not review:
        raise ValueError("Swiss tram seats are review-only; production visual acceptance is incomplete")
    ways = validate_sources(extract, sources, config)
    chains = compile_corridors(config, ways, sources)
    out, ledger = [], []
    for fi, f in enumerate(features):
        props = f["properties"]
        if props.get("g") != "ch" or props.get("jk") != "urban":
            out.append(f)
            continue
        identity = feature_key(props)
        # Production has no network/route id on its display features. Do not guess
        # which Basel Tram 8 variant a same-name, same-colour feature belongs to.
        owner = resolve_source(props, sources)
        if owner is None:
            out.append(f)
            ledger.append({"feature": fi, "identity": identity, "status": "OPEN_AMBIGUOUS_SOURCE"})
            continue
        candidates = [c for c in chains if c.corridor["ct"] == props["ct"]
                      and props["n"] in c.seats
                      and source_identity(owner) in c.owners[props["n"]]]
        if not candidates:
            out.append(f)
            continue
        proposed, records, touched = [], [], False
        for part_index, co in enumerate(coordinates(f)):
            original = LineString(co)
            latitude = sum(p[1] for p in co) / len(co)
            g = metric(original, latitude)
            if g.length == 0:
                proposed.append(f)
                continue
            geographic_marks = np.concatenate(([0], np.cumsum(np.linalg.norm(np.diff(np.asarray(co), axis=0), axis=1))))
            metric_marks = np.concatenate(([0], np.cumsum(np.linalg.norm(np.diff(np.asarray(g.coords), axis=0), axis=1))))
            local = [metric(metric(c.geometry, c.source["latitude"], inverse=True), latitude) for c in candidates]
            tree = STRtree(local)
            supports = [h.buffer(c.corridor["reach_m"]) for h, c in zip(local, candidates)]
            authorised = {w for c in candidates for w in c.source["way_ids"]}
            independent = [metric(LineString(ways[w][1]), latitude)
                           for w in owner["way_ids"] if w not in authorised]
            independent_tree = STRtree(independent)
            cuts = np.linspace(0, g.length, max(1, math.ceil(g.length / SAMPLE_M)) + 1)
            groups = []
            for lo, hi in zip(cuts, cuts[1:]):
                middle = (lo + hi) / 2
                point, direction = g.interpolate(middle), tangent(g, middle)
                eligible = []
                piece = substring(g, float(lo), float(hi))
                for index in tree.query(point, predicate="dwithin", distance=8):
                    c, h = candidates[int(index)], local[int(index)]
                    at = h.project(point)
                    axis = tangent(h, at)
                    dot = sum(a * b for a, b in zip(axis, direction))
                    if at <= 0 or at >= h.length or abs(dot) < 0.92 or not supports[int(index)].covers(piece):
                        continue
                    distance = h.distance(point)
                    # A fitted display path has no way ids. Reject it if a
                    # non-corridor source track is an equally plausible host.
                    conflict = False
                    for peer in independent_tree.query(point, predicate="dwithin", distance=distance + 0.5):
                        other = independent[int(peer)]
                        axis2 = tangent(other, other.project(point))
                        if abs(sum(a * b for a, b in zip(axis2, direction))) >= 0.92:
                            conflict = True
                            break
                    if conflict:
                        continue
                    eligible.append((h.distance(point), c.corridor["id"], int(index), at, dot))
                p = dict(props)
                cid = None
                if eligible:
                    _, cid, index, at, dot = min(eligible)
                    c, h = candidates[index], local[index]
                    weight = min(1.0, at / c.corridor["ramp_m"], (h.length - at) / c.corridor["ramp_m"])
                    weight = weight * weight * (3 - 2 * weight)
                    seat = c.seats[props["n"]] * (1 if dot > 0 else -1)
                    # sh is not multiplied into off; the renderer applies it once.
                    p["off"] = round((props.get("off", 0) * (1 - weight) + seat * weight) / GRAIN) * GRAIN
                    p.update({"ap": 1, "sh": round(weight, 6), "goff": 0,
                              "bn": len(c.source["lines"]), "lead": int(c.seats[props["n"]] == 0)})
                    touched = True
                    records.append({"feature": fi, "part": part_index, "corridor": cid,
                                    "identity": source_identity(owner),
                                    "from_m": round(float(lo), 3), "to_m": round(float(hi), 3),
                                    "at": list(metric(point, latitude, inverse=True).coords[0]),
                                    "seat": seat, "off": p["off"], "sh": p["sh"],
                                    "source_distance_m": round(h.distance(point), 6)})
                signature = (digest(p), cid)
                if groups and groups[-1][3] == signature:
                    groups[-1][1] = float(hi)
                else:
                    groups.append([float(lo), float(hi), p, signature])
            for lo, hi, p, _ in groups:
                # Cut the original geographic geometry, not its metric round trip.
                line = substring(original, float(np.interp(lo, metric_marks, geographic_marks)),
                                 float(np.interp(hi, metric_marks, geographic_marks)))
                proposed.append({**f, "properties": p, "geometry": {
                    "type": "LineString", "coordinates": [list(x) for x in line.coords]}})
        out.extend(proposed if touched else [f])
        ledger.extend(records)
    return out, ledger


def coordinates(feature):
    geom = feature["geometry"]
    return geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source_groups(extract):
    """Use the production route/master identity, not spatial proximity."""
    from process_europe import COUNTRIES, urban_line_of_route
    from country import urban_groups
    from process_jp import km
    cfg = COUNTRIES["ch"]
    ways = {wid: (tags, co) for wid, tags, co in extract["ways"]}
    relations = {rid: (tags, members) for rid, tags, members in extract["relations"]}
    masters = {ref: tags for tags, members in relations.values()
               if tags.get("type") == "route_master" for kind, ref in members if kind == "r"}
    routes = defaultdict(lambda: {"ways": set(), "kinds": Counter(), "en": [], "relations": []})
    for rid, (tags, members) in relations.items():
        if tags.get("type") != "route" or tags.get("route") not in cfg.urban:
            continue
        key = urban_line_of_route(tags, masters.get(rid, {}))
        if not key[1]:
            continue
        row = routes[key]
        row["relations"].append(rid)
        for kind, ref in members:
            if kind == "w" and ref in ways:
                t, co = ways[ref]
                if t.get("railway") in cfg.urban | cfg.rail and not t.get("service"):
                    row["ways"].add(ref)
                    row["kinds"][tags["route"]] += km(co)
    return ways, urban_groups(cfg, routes)


def replay_urban(extract, prototypes):
    """Only the production urban geometry block; no rail, stations or country writes."""
    from process_europe import COUNTRIES
    from process_jp import TOL, geometry, km, readable_on_dark, rounded, runs_of
    from single_track import one_track, stitch
    cfg = COUNTRIES["ch"]
    ways, groups = source_groups(extract)
    features, sources, omitted = [], [], []
    for group_key, parts in sorted(groups.items(), key=lambda kv: tuple(v or "" for v in kv[0])):
        names = sorted({n for n, _ in parts})
        name = names[0] if len(names) == 1 else group_key[0]
        wids = sorted(set().union(*(line["ways"] for _, line in parts)))
        kinds = sum((line["kinds"] for _, line in parts), Counter())
        rids = sorted(set(r for _, line in parts for r in line["relations"]))
        if not wids:
            continue
        light = kinds["subway"] < sum(v for k, v in kinds.items() if k != "subway")
        drawn = stitch(one_track(runs_of([ways[w][1] for w in wids])), bends=True)
        simp = rounded(drawn, TOL["light" if light else "metro"],
                       (6, 6, 0.00004) if light else (5, 4, 0.0003), adaptive=True)
        if not simp or sum(km(co) for co in simp) < cfg.metro_min_km:
            omitted.append({"name": name, "network": group_key[0], "relations": rids,
                            "way_ids": wids, "reason": "production metro_min_km",
                            "km": sum(km(co) for co in simp)})
            continue
        mid = LineString(max(simp, key=len)).interpolate(0.5, normalized=True)
        city = next((c[0] for c in cfg.cities
                     if math.hypot((c[1] - mid.x) * math.cos(math.radians(mid.y)), c[2] - mid.y) < c[3]),
                    cfg.elsewhere)
        col = readable_on_dark(group_key[-1]) if group_key[-1] else "#5cc8ff"
        proto = next((f["properties"] for f in prototypes if f["properties"].get("ct") == city
                      and f["properties"].get("n") == name and f["properties"].get("col") == col), {})
        props = {k: v for k, v in proto.items() if k not in ("off", "bn", "sh", "ap", "lead", "goff")}
        props.update({"r": "CH", "g": "ch", "ct": city, "n": name, "col": col,
                      "jk": "urban" if light else "subway"})
        features.append({"type": "Feature", "properties": props, "geometry": geometry(simp)})
        sources.append({"ct": city, "name": name, "network": group_key[0], "col": col,
                        "way_ids": wids, "relations": rids, "route_kinds": dict(kinds)})
    return features, sources, omitted


def shared_inventory(ways, sources):
    """Exact way sharing, split at membership changes and branches."""
    members = defaultdict(set)
    for row in sources:
        if row["route_kinds"].get("subway"):
            continue
        for wid in row["way_ids"]:
            members[wid].add(source_identity(row))
    groups = defaultdict(list)
    for wid, keys in members.items():
        if len(keys) > 1:
            groups[tuple(sorted(keys))].append(wid)
    rows = []
    for keys, wids in sorted(groups.items()):
        raw = unary_union([LineString(ways[w][1]) for w in sorted(wids)])
        merged = linemerge(raw) if raw.geom_type == "MultiLineString" else raw
        lines = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
        for g in sorted(lines, key=lambda g: g.bounds):
            owned = [w for w in sorted(wids) if LineString(ways[w][1]).intersection(g).length > 0]
            scale = 111320 * math.cos(math.radians(g.centroid.y))
            from shapely.affinity import scale as geo_scale
            length = geo_scale(g, xfact=scale, yfact=111320, origin=(0, 0)).length
            rows.append({"ct": keys[0][2], "lines": [k[4] for k in keys],
                         "identities": [list(k) for k in keys], "way_ids": owned,
                         "length_m": round(length, 2), "from": list(g.coords[0]),
                         "to": list(g.coords[-1]), "at": list(g.interpolate(0.5, normalized=True).coords[0]),
                         "coordinates": list(g.coords)})
    return rows


def write_json(file_path, value):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def review(args):
    out = Path(args.out).resolve()
    allowed = Path("/private/tmp/cnrail-europe-review/tram")
    if not out.is_relative_to(allowed):
        raise ValueError("Experiments must stay in /private/tmp/cnrail-europe-review/tram")
    out.mkdir(parents=True, exist_ok=True)
    paths = [ROOT / "data/raw/extract_ch.pkl", ROOT / "data/ch_metro.geojson",
             ROOT / "scripts/country.py", ROOT / "scripts/process_europe.py",
             ROOT / "scripts/side_by_side.py", ROOT / "src/app.html"]
    receipt = {"base": "56011d91f9c0c4204614c9847a6d42d18b183373",
               "inputs": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    extract = pickle.loads(paths[0].read_bytes())
    existing = json.loads(paths[1].read_text())["features"]
    frozen = Path(args.frozen).resolve() if args.frozen else None
    if frozen:
        previous = json.loads((frozen / "receipt.json").read_text())
        for key in ("data/raw/extract_ch.pkl", "data/ch_metro.geojson"):
            if receipt["inputs"][key] != previous["inputs"][key]:
                raise ValueError(f"Frozen baseline changed: {key}")
        native = json.loads((frozen / "native.geojson").read_text())["features"]
        before = json.loads((frozen / "before.geojson").read_text())["features"]
        sources = json.loads((frozen / "sources.json").read_text())
        omitted = json.loads((frozen / "omitted.json").read_text())
        receipt["reused_receipt_sha256"] = hashlib.sha256((frozen / "receipt.json").read_bytes()).hexdigest()
    else:
        native, sources, omitted = replay_urban(extract, existing)
        before = side_by_side(native)
    config = json.loads(CONFIG.read_text())
    after, changes = apply_ch_tram_seats(before, extract, config, sources=sources, review=True)
    receipt.update({"baseline_exact": before == existing, "native_lines": len(native),
                    "baseline_features": len(before), "source_snapshot": extract["sources"],
                    "native_sha256": digest(native), "baseline_sha256": digest(before),
                    "after_sha256": digest(after), "after_features": len(after),
                    "changed_samples": len([r for r in changes if "corridor" in r]),
                    "config_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
                    "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "visual_status": "NOT_REVIEWED"})
    ways, _ = source_groups(extract)
    inventory = shared_inventory(ways, sources)
    for name, value in (("native.geojson", {"type": "FeatureCollection", "features": native}),
                        ("before.geojson", {"type": "FeatureCollection", "features": before}),
                        ("after.geojson", {"type": "FeatureCollection", "features": after}),
                        ("sources.json", sources), ("omitted.json", omitted),
                        ("config.json", config),
                        ("changes.json", changes),
                        ("shared.json", inventory), ("receipt.json", receipt)):
        write_json(out / name, value)
    print(json.dumps({**receipt, "shared_chains": len(inventory),
                      "shared_over_330m": sum(r["length_m"] >= 330 for r in inventory)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/private/tmp/cnrail-europe-review/tram/v2")
    parser.add_argument("--frozen", help="Reuse a completed urban-only replay instead of repeating it")
    review(parser.parse_args())
