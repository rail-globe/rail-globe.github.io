"""Build inland national boundary lines, separately from camera ownership.

Never reads or writes railway data or China's existing border. The input is
hash-pinned; normal page builds stay offline.
"""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
from urllib.request import urlopen

from shapely.geometry import LineString

from build_view_boundaries import pack_ring

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / "data" / "cache" / "borders"
COUNTRIES = {"de": "DEU", "fr": "FRA", "ch": "CHE", "es": "ESP",
             "nl": "NLD", "be": "BEL", "it": "ITA", "at": "AUT", "hu": "HUN"}
EUROPE_BOUNDS = (-25, 34, 45, 72)
SOURCE = {
    "url": "https://gisco-services.ec.europa.eu/distribution/v2/countries/geojson/CNTR_BN_01M_2024_4326.geojson",
    "sha256": "096d0008e122cefa608a97ba27c9702b5ec3348f80f0219821d515594b28f6c2",
    "cache_file": "gisco-lines-meta.json",
    "publisher": "European Commission / Eurostat GISCO",
    "year": 2024, "scale": "1:1 million",
    "metadata": "https://gisco-services.ec.europa.eu/distribution/v2/countries/countries-2024-files.html",
    "attribute_reference": "https://sdi.eea.europa.eu/datashare/s/sptXqwkQr5g7Bp5/download?files=Static-map-documentation-preparation-of-raw-data-2023-09.pdf&path=%2Feea_v_3035_1_mio_map-template-4_p_2023-now_v01_r00",
    "license": "Non-commercial use; visible EuroGeographics acknowledgement required.",
    "license_url": "https://ec.europa.eu/eurostat/web/gisco/geodata/administrative-units",
}


def load_source(cache=DEFAULT_CACHE, offline=False):
    target = cache / SOURCE["cache_file"]
    if target.exists():
        raw = target.read_bytes()
    else:
        if offline:
            raise FileNotFoundError(target)
        with urlopen(SOURCE["url"], timeout=90) as response:
            raw = response.read()
        if hashlib.sha256(raw).hexdigest() != SOURCE["sha256"]:
            raise ValueError("GISCO source hash changed; refusing unpinned download")
        cache.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SOURCE["sha256"]:
        raise ValueError(f"GISCO source hash changed: {digest}")
    data = json.loads(raw)
    if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise ValueError("Expected GISCO boundary FeatureCollection")
    return data, {**SOURCE, "download_bytes": len(raw)}


def country_uri(value):
    return isinstance(value, str) and len(value) == 3 and all("A" <= c <= "Z" for c in value)


def line_parts(feature):
    geometry = feature.get("geometry") or {}
    if geometry.get("type") == "LineString":
        parts = [geometry["coordinates"]]
    elif geometry.get("type") == "MultiLineString":
        parts = geometry["coordinates"]
    else:
        raise ValueError("Expected national boundary lines, not polygons")
    if not parts:
        raise ValueError("Empty national boundary")
    for points in parts:
        if len(points) < 2 or any(
                len(p) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in p)
                or not -180 <= p[0] <= 180 or not -90 <= p[1] <= 90 for p in points):
            raise ValueError("Invalid boundary coordinates")
        line = LineString(points)
        if not line.is_valid or not line.is_simple or line.length == 0:
            raise ValueError("Invalid or self-intersecting boundary line")
    return parts


def in_scope(points):
    inside = [EUROPE_BOUNDS[0] <= x <= EUROPE_BOUNDS[2]
              and EUROPE_BOUNDS[1] <= y <= EUROPE_BOUNDS[3] for x, y in points]
    if any(inside) and not all(inside):
        # A scope edge must never become a fabricated national border.
        raise ValueError("Boundary straddles project scope; review instead of clipping")
    return all(inside)


def select_boundaries(data):
    selected, excluded, seen = [], [], set()
    iso3 = set(COUNTRIES.values())
    for feature in data["features"]:
        props = feature.get("properties") or {}
        left, right = props.get("LEFT_URI"), props.get("RIGHT_URI")
        if not iso3.intersection((left, right)):
            continue
        boundary_id = props.get("CNTR_BN_ID")
        if not isinstance(boundary_id, int) or boundary_id in seen:
            raise ValueError("Missing or duplicate GISCO boundary ID")
        seen.add(boundary_id)
        flag = props.get("COAS_FLAG")
        if flag not in ("T", "F"):
            raise ValueError("Missing or unknown COAS_FLAG")
        if flag == "T":
            excluded.append({"id": boundary_id, "reason": "coastline"})
            continue
        if not country_uri(left) or not country_uri(right) or left == right:
            excluded.append({"id": boundary_id, "reason": "not two distinct countries"})
            continue
        kept = []
        for index, points in enumerate(line_parts(feature)):
            if in_scope(points):
                kept.append(index)
            else:
                excluded.append({"id": boundary_id, "part": index, "reason": "outside project Europe"})
        if kept:
            selected.append((feature, kept))
    return sorted(selected, key=lambda item: item[0]["properties"]["CNTR_BN_ID"]), excluded


def build(cache=DEFAULT_CACHE, offline=False):
    data, source = load_source(cache, offline)
    selected, excluded = select_boundaries(data)
    features, counts = [], {}
    for code, iso3 in COUNTRIES.items():
        coordinates, records, neighbors = [], [], set()
        for feature, indices in selected:
            props = feature["properties"]
            left, right = props["LEFT_URI"], props["RIGHT_URI"]
            if iso3 not in (left, right):
                continue
            parts = line_parts(feature)
            coordinates.extend(parts[index] for index in indices)
            neighbors.add(right if iso3 == left else left)
            records.append({"id": props["CNTR_BN_ID"], "left": left, "right": right,
                            "parts": indices, "COAS_FLAG": props["COAS_FLAG"],
                            "POL_STAT": props.get("POL_STAT")})
        if not coordinates:
            raise ValueError(f"{code}: no inland boundaries selected")
        features.append({"type": "Feature", "properties": {"g": code, "k": "land"},
                         "geometry": {"type": "MultiLineString", "coordinates": coordinates}})
        vertices = sum(map(len, coordinates))
        counts[code] = {
            "source_vertices": vertices, "display_vertices": vertices, "parts": len(coordinates),
            "closed_parts": sum(points[0] == points[-1] for points in coordinates),
            "neighbors": sorted(neighbors), "boundaries": records,
            "bbox": [min(p[0] for points in coordinates for p in points),
                     min(p[1] for points in coordinates for p in points),
                     max(p[0] for points in coordinates for p in points),
                     max(p[1] for points in coordinates for p in points)],
            "continuous_error_bound_degrees": 0,
        }
    return {
        "type": "FeatureCollection",
        "purpose": "Visible inland national boundaries only; no coastlines or maritime delimitations; not ADM1 borders.",
        "crs_note": "WGS84 longitude, latitude",
        "simplification_degrees": 0,
        "precision_note": "Original GISCO 1M coordinates, endpoints and line parts retained exactly.",
        "error_method": "Coordinate identity to selected source parts; zero additional error, not source positional accuracy.",
        "selection": {"COAS_FLAG": "F", "countries": "Distinct non-null LEFT_URI and RIGHT_URI (ISO3)",
                      "scope_bbox": list(EUROPE_BOUNDS),
                      "scope_method": "Whole source parts, no clipping or artificial scope-edge lines",
                      "unique_in_scope_boundaries": len(selected), "excluded": excluded},
        "limitations": [
            "Inland international boundaries through rivers and lakes are retained; this is not a dry-land mask.",
            "GISCO 1M is generalized, not survey accuracy. Small enclaves and counter-enclaves may be absent.",
            "Baarle retains four closed source parts; Vennbahn retains one closed source part, not all exclaves.",
            "French overseas boundaries are excluded; Ceuta and Melilla land boundaries are included.",
            "A shared boundary is duplicated by g for independent country switches, with identical coordinates.",
        ],
        "sources": {"gisco": source}, "counts": counts, "features": features,
    }


def packed_boundaries(result, canonical_bytes):
    return {**result, "encoding": "polyline6-xy",
            "canonical_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
            "features": [{**feature, "geometry": {**feature["geometry"],
                         "coordinates": [pack_ring(points) for points in feature["geometry"]["coordinates"]]}}
                         for feature in result["features"]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "data/europe_borders.geojson")
    args = parser.parse_args()
    result = build(args.cache_dir, args.offline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    canonical = (json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n").encode()
    args.output.write_bytes(canonical)
    packed = (json.dumps(packed_boundaries(result, canonical), ensure_ascii=True, separators=(",", ":")) + "\n").encode()
    packed_output = args.output.with_name(args.output.stem + ".packed.json")
    packed_output.write_bytes(packed)
    print(json.dumps({"output": str(args.output), "bytes": len(canonical),
                      "sha256": hashlib.sha256(canonical).hexdigest(),
                      "gzip_bytes": len(gzip.compress(canonical, mtime=0)),
                      "packed_output": str(packed_output), "packed_bytes": len(packed),
                      "packed_sha256": hashlib.sha256(packed).hexdigest(),
                      "packed_gzip_bytes": len(gzip.compress(packed, mtime=0)),
                      "counts": result["counts"]}, indent=2))


if __name__ == "__main__":
    main()
