"""Explicit French route aliases and bounded independent-track zoom corrections.

Call canonical_route_key before accumulating route members, then
apply_fr_tram_seats once after side_by_side. Neither function writes country data.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from shapely.geometry import LineString, Point, box, shape
from shapely.affinity import scale
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data/fr_tram_seats.json"
TEMP = Path("/private/tmp/cnrail-europe-review")
GRAIN = 1 / 16


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def load_config():
    return json.loads(CONFIG.read_text())


def validate_extract(extract, config=None):
    """Bind actual decoded rows, including order, geometry and relation members."""
    config = load_config() if config is None else config
    expected = config.get("extract_fields_sha256", {})
    if not expected:
        return
    if extract is None or set(extract) != set(expected):
        raise ValueError("French source preflight requires the complete pinned extract")
    for key, fingerprint in expected.items():
        if digest(extract[key]) != fingerprint:
            raise ValueError(f"Stale French extract field: {key}")


def validate_config(config):
    if config.get("version") != 1 or config.get("country") != "fr":
        raise ValueError("Expected French configuration version 1")
    ids, relations, identities = set(), set(), set()
    for row in config["aliases"]:
        if row["id"] in ids or not row["why"] or not row["asked"]:
            raise ValueError("Duplicate or unauthorised alias")
        ids.add(row["id"])
        if not row["relations"] or len(set(row["relations"])) != len(row["relations"]):
            raise ValueError("Invalid alias relations")
        if relations.intersection(row["relations"]):
            raise ValueError("Relation belongs to multiple aliases")
        relations.update(row["relations"])
        if row["canonical_colour"] not in row["source_colours"]:
            raise ValueError("Canonical colour must be observed in the source")
    for row in config["independent"]:
        identity = tuple(row["identity"])
        if len(identity) != 4 or identity in identities:
            raise ValueError("Independent selectors must have unique full identities")
        identities.add(identity)
        if row["id"] in ids or not row["why"] or not row["asked"]:
            raise ValueError("Duplicate or unauthorised independent correction")
        ids.add(row["id"])
        west, south, east, north = row["bbox"]
        if not (-180 < west < east < 180 and -90 < south < north < 90):
            raise ValueError("Invalid correction bounds")
        if east - west > 0.04 or north - south > 0.04 or not 0 < row["ramp_m"] <= 500:
            raise ValueError("Unbounded independent correction")
        if len(row["line_sha256"]) != 64:
            raise ValueError("Missing frozen line fingerprint")


def canonical_route_key(key, relation_id, config=None):
    """Merge only listed source relations, never nearby/same-name/same-colour lines."""
    config = load_config() if config is None else config
    validate_config(config)
    for row in config["aliases"]:
        if relation_id not in row["relations"]:
            continue
        network, name, colour = key
        if (network, name) != (row["network"], row["name"]) or colour not in row["source_colours"]:
            raise ValueError(f"Stale route identity: {row['id']}/{relation_id}")
        return network, name, row["canonical_colour"]
    return key


def validate_alias_sources(extract, config=None):
    """Preflight the whitelist against the actual production route/master keys."""
    from country import line_of_route
    from process_europe import urban_line_of_route

    config = load_config() if config is None else config
    validate_config(config)
    validate_extract(extract, config)
    relations = {rid: (tags, members) for rid, tags, members in extract["relations"]}
    masters = {ref: tags for tags, members in relations.values()
               if tags.get("type") == "route_master"
               for kind, ref in members if kind == "r"}
    checked = []
    for row in config["aliases"]:
        for rid in row["relations"]:
            if rid not in relations or relations[rid][0].get("route") != "tram":
                raise ValueError(f"Missing tram relation: {rid}")
            tags, _ = relations[rid]
            key = urban_line_of_route(tags, masters.get(rid, {}))
            canonical_route_key(key, rid, config)
            checked.append({"relation": rid, "before": key,
                            "after": canonical_route_key(key, rid, config)})
            if not line_of_route(tags, masters.get(rid, {}))[1]:
                raise ValueError(f"Missing source name: {rid}")
    return checked


def identity(feature):
    props = feature["properties"]
    return props.get("ct"), props.get("n"), props.get("col"), props.get("jk")


def line_fingerprint(features):
    return digest(sorted(({"geometry": f["geometry"],
                           "off": f["properties"].get("off", 0)}
                          for f in features), key=digest))


def parts(feature):
    geometry = feature["geometry"]
    if geometry["type"] not in ("LineString", "MultiLineString"):
        raise ValueError("Expected line geometry")
    return [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]


def bounded_region(row):
    west, south, east, north = row["bbox"]
    latitude = (south + north) / 2
    xscale = 111320 * math.cos(math.radians(latitude))
    region = scale(box(west, south, east, north), xfact=xscale, yfact=111320, origin=(0, 0))
    return scale(region.buffer(row["ramp_m"]), xfact=1 / xscale, yfact=1 / 111320, origin=(0, 0))


def bounded_geometry_fingerprint(geometries, row):
    """Ignore splitting, direction and unrelated distant geometry, not local vertices."""
    region = bounded_region(row)
    geometry = unary_union(geometries).intersection(region).normalize()
    return hashlib.sha256(geometry.wkb).hexdigest()


def bounded_layout_fingerprint(features, row):
    region = bounded_region(row)
    groups = {}
    for feature in features:
        p = feature["properties"]
        layout = {key: p[key] for key in ("off", "op", "ap", "sh", "goff", "lead", "bn") if key in p}
        key = json.dumps(layout, sort_keys=True)
        groups.setdefault(key, []).append(shape(feature["geometry"]))
    return digest(sorted([key, bounded_geometry_fingerprint(lines, row)]
                         for key, lines in groups.items()
                         if unary_union(lines).intersects(region)))


def bounded_source(extract, row):
    """Actual relation members and actual selected original edges in one authorised box."""
    from process_jp import runs_of
    from single_track import one_track
    relations = {rid: members for rid, _, members in extract["relations"]}
    ways = {wid: (tags, co) for wid, tags, co in extract["ways"]}
    wids = sorted({ref for rid in row["relations"] for kind, ref in relations[rid]
                   if kind == "w" and ref in ways
                   and ways[ref][0].get("railway") in ("subway", "tram", "light_rail", "rail", "narrow_gauge")
                   and not ways[ref][0].get("service")})
    kept = one_track(runs_of([ways[wid][1] for wid in wids]))
    region = bounded_region(row)
    local = [[wid, ways[wid][0], ways[wid][1]] for wid in wids
             if LineString(ways[wid][1]).intersects(region)]
    return {"way_ids": wids, "source_sha256": digest(local),
            "selected_sha256": bounded_geometry_fingerprint(kept, row)}


def validate_bounded_display(features, extract, sources, row):
    if extract is None or sources is None:
        raise ValueError(f"Bounded correction requires actual extract/source rows: {row['id']}")
    matches = [s for s in sources if s["name"] == row["identity"][1]
               and s["network"] == row["network"]
               and sorted(s["relations"]) == sorted(row["relations"])]
    if len(matches) != 1:
        raise ValueError(f"Ambiguous bounded actual source: {row['id']}")
    for feature in features:
        p = feature["properties"]
        raw = p.get("rid")
        rids = sorted(map(int, raw.split(","))) if isinstance(raw, str) else sorted(raw or [])
        if p.get("network") != row["network"] or rids != sorted(row["relations"]):
            raise ValueError(f"Stale bounded display network/rid: {row['id']}")
    actual = bounded_source(extract, row)
    expected = row["bounded_validation"]
    for key in ("source_sha256", "selected_sha256"):
        if actual[key] != expected[key]:
            raise ValueError(f"Stale bounded {key}: {row['id']}")
    display = bounded_geometry_fingerprint([shape(f["geometry"]) for f in features], row)
    if display != expected["display_sha256"]:
        raise ValueError(f"Stale bounded local display geometry: {row['id']}")
    layout = bounded_layout_fingerprint(features, row)
    if layout not in expected["reviewed_layout_sha256"]:
        raise ValueError(f"Unreviewed bounded layout change: {row['id']}")
    return {"correction": row["id"], "status": "BOUNDED_SOURCE_SELECTED_DISPLAY_VALIDATED",
            "display_sha256": display, "layout_sha256": layout, **actual}


def apply_fr_tram_seats(features, config=None, *, extract=None, sources=None):
    """Preserve off and coordinates; write goff only within four authorised selectors.

    Stale inputs, an existing displacement, or a second application fail before
    producing a result. No shared-track inference is performed.
    """
    config = load_config() if config is None else config
    validate_config(config)
    validate_extract(extract, config)
    selectors = {tuple(row["identity"]): row for row in config["independent"]}
    for key, row in selectors.items():
        selected = [f for f in features if f["properties"].get("g") == "fr" and identity(f) == key]
        if any(any(k in f["properties"] for k in ("goff", "ap", "sh", "frseat")) for f in selected):
            raise ValueError(f"Conflicting existing displacement: {row['id']}")
        if row.get("bounded_validation"):
            validate_bounded_display(selected, extract, sources, row)
        elif not selected or line_fingerprint(selected) != row["line_sha256"]:
            raise ValueError(f"Stale or already corrected line: {row['id']}")

    out, ledger = [], []
    for fi, feature in enumerate(features):
        props = feature["properties"]
        row = selectors.get(identity(feature)) if props.get("g") == "fr" else None
        if row is None or not props.get("off"):
            out.append(feature)
            continue
        west, south, east, north = row["bbox"]
        xscale = 111320 * math.cos(math.radians((south + north) / 2))
        region = scale(box(west, south, east, north), xfact=xscale, yfact=111320, origin=(0, 0))
        support = region.buffer(row["ramp_m"])
        proposed, records = [], []
        for pi, coords in enumerate(parts(feature)):
            groups = []
            for a, b in zip(coords, coords[1:]):
                point = Point((a[0] + b[0]) / 2 * xscale, (a[1] + b[1]) / 2 * 111320)
                weight = max(0, 1 - region.distance(point) / row["ramp_m"])
                edge = LineString([(a[0] * xscale, a[1] * 111320),
                                   (b[0] * xscale, b[1] * 111320)])
                if not support.covers(edge):
                    weight = 0
                weight = weight * weight * (3 - 2 * weight)
                goff = round(props["off"] * weight / GRAIN) * GRAIN
                if groups and groups[-1][1] == goff:
                    groups[-1][0].append(b)
                else:
                    groups.append([[a, b], goff])
            for coords_out, goff in groups:
                p = dict(props)
                if goff:
                    p.update({"goff": goff, "frseat": row["id"]})
                    records.append({"feature": fi, "part": pi, "correction": row["id"],
                                    "identity": list(identity(feature)), "off": props["off"],
                                    "goff": goff, "from": coords_out[0], "to": coords_out[-1]})
                proposed.append({**feature, "properties": p, "geometry": {
                    "type": "LineString", "coordinates": coords_out}})
        out.extend(proposed if records else [feature])
        ledger.extend(records)
    return out, ledger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--extract", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    target = args.out.resolve()
    if not target.is_relative_to(TEMP) or target == args.input.resolve():
        parser.error("Output must be a separate experiment below /private/tmp/cnrail-europe-review")
    import pickle
    config = load_config()
    raw = args.extract.read_bytes()
    if hashlib.sha256(raw).hexdigest() != config["extract_sha256"]:
        parser.error("Extract bytes differ from the approved source revision")
    extract = pickle.loads(raw)
    validate_alias_sources(extract, config)
    collection = json.loads(args.input.read_text())
    result, ledger = apply_fr_tram_seats(collection["features"], config, extract=extract)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({**collection, "features": result}, ensure_ascii=False) + "\n")
    target.with_suffix(".ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"changes": len(ledger), "out": str(target), "visual_status": "NOT_REVIEWED"}))


if __name__ == "__main__":
    main()
