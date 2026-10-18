"""Build view ownership polygons only. Never reads or writes railway data.

Run explicitly to refresh data/view_boundaries.json; normal page builds are offline.
Sources are pinned revisions, with download hashes retained in the generated file.
Coordinates are WGS84. Douglas-Peucker tolerance is 0.0002 degrees (under 23 m),
then coordinates are rounded to six decimals. This is a camera heuristic, not a
survey boundary. Separate source vintages may disagree at the border itself.
"""
import argparse
import base64
import hashlib
import json
import math
import struct
from pathlib import Path
from urllib.request import urlopen

from shapely.geometry import LinearRing, MultiPolygon, Polygon, mapping, shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
GB = "https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/9469f09/releaseData/gbOpen"
DEFAULT_CACHE = Path("/private/tmp/cnrail-europe-review/borders/sources")
SOURCES = {
    "de": {
        "url": f"{GB}/DEU/ADM0/geoBoundaries-DEU-ADM0.geojson",
        "sha256": "1a0ed87d95e64f3b7dd3a6e23add532d9c70301c1ad8f8fb1664ebac6699bdbe",
        "publisher": "BKG via geoBoundaries", "year": 2021,
        "metadata": "https://www.geoboundaries.org/api/current/gbOpen/DEU/ADM0/",
        "license": "Data licence Germany - attribution 2.0",
        "license_url": "https://www.govdata.de/dl-de/by-2-0",
    },
    "fr": {
        "url": "https://raw.githubusercontent.com/gregoiredavid/france-geojson/45daa2d069a8da3ec4efb6672388fc3dc02e36e2/metropole.geojson",
        "sha256": "d1f4aec3fbc274d4af3f5930302a342d3efe0ea1daf410fbeef535346167bf0c",
        "publisher": "IGN ADMIN EXPRESS COG via france-geojson", "year": 2018,
        "metadata": "https://github.com/gregoiredavid/france-geojson/tree/45daa2d069a8da3ec4efb6672388fc3dc02e36e2",
        "license": "Etalab Open Licence",
        "license_url": "https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
        "coverage": "Metropolitan France including Corsica; upstream already simplified to 25%.",
    },
    "ch": {
        "url": f"{GB}/CHE/ADM0/geoBoundaries-CHE-ADM0.geojson",
        "sha256": "3eb2414cea931ee2c2927d718b8ef57b4e492543bd8a34af4233e1d43007a55d",
        "publisher": "swisstopo via geoBoundaries", "year": 2022,
        "metadata": "https://www.geoboundaries.org/api/current/gbOpen/CHE/ADM0/",
        "license": "swisstopo Open Government Data",
        "license_url": "https://www.swisstopo.admin.ch/en/terms-of-use-free-geodata-and-geoservices",
    },
    "es": {
        "url": f"{GB}/ESP/ADM0/geoBoundaries-ESP-ADM0.geojson",
        "sha256": "27ccbe16a21a63f9e7c380fd5570aed790bd501e431be156c0ca9e062413bc25",
        "publisher": "IGN Spain via geoBoundaries", "year": 2017,
        "metadata": "https://www.geoboundaries.org/api/current/gbOpen/ESP/ADM0/",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
    },
    "nl": {
        "url": f"{GB}/NLD/ADM0/geoBoundaries-NLD-ADM0.geojson",
        "sha256": "626345fb2e69cf4ac95ffa0db737a725dc041f455dcdb892293dcbabc5034881",
        "publisher": "National Georegister via geoBoundaries", "year": 2022,
        "metadata": f"{GB}/NLD/ADM0/geoBoundaries-NLD-ADM0-metaData.json",
        "license": "CC0 1.0", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "coverage": "European Netherlands, including Wadden islands; not Caribbean territories.",
    },
    "be": {
        "url": "https://gisco-services.ec.europa.eu/distribution/v2/countries/geojson/CNTR_RG_01M_2024_4326.geojson",
        "sha256": "556a81995108778335b8551f0d8929e86dcbcaab206ba512ba12928eafce505f",
        "cache_file": "gisco-CNTR_RG_01M_2024_4326.geojson",
        "selector": {"CNTR_ID": "BE"},
        "publisher": "Eurostat / European Commission GISCO", "year": 2024,
        "metadata": "https://gisco-services.ec.europa.eu/distribution/v2/countries/",
        "license": "European Commission reuse, attribution required",
        "license_url": "https://ec.europa.eu/eurostat/web/gisco/geodata/geographical-information",
        "coverage": "1:1 million generalized Belgium, including larger Baarle and Vennbahn exclaves; smaller exclaves and counter-enclaves are unresolved.",
    },
    "it": {
        "url": f"{GB}/ITA/ADM0/geoBoundaries-ITA-ADM0.geojson",
        "sha256": "793947db758b55b649daa58564c4ab641fea0f39164e16a955d5e2862f4b171a",
        "publisher": "ISTAT via geoBoundaries", "year": 2023,
        "metadata": f"{GB}/ITA/ADM0/geoBoundaries-ITA-ADM0-metaData.json",
        "license": "CC BY 3.0", "license_url": "https://creativecommons.org/licenses/by/3.0/",
        "coverage": "Italy including Sicily, Sardinia and smaller islands.",
    },
}
TOLERANCE = 0.0002


def load_source(code, cache=DEFAULT_CACHE, offline=False):
    source = SOURCES[code]
    target = cache / source.get("cache_file", f"{code}-ADM0.geojson")
    if target.exists():
        raw = target.read_bytes()
    else:
        if offline:
            raise FileNotFoundError(target)
        with urlopen(source["url"], timeout=90) as response:
            raw = response.read()
        cache.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != source["sha256"]:
        raise ValueError(f"{code}: source hash changed: {digest}")
    data = json.loads(raw)
    if source.get("selector"):
        data = {**data, "features": [f for f in data["features"] if all(
            f["properties"].get(key) == value for key, value in source["selector"].items())]}
        if not data["features"]:
            raise ValueError(f"{code}: source selector returned no polygons")
    return data, {**source, "download_bytes": len(raw)}


def segment_distance_sq(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    fraction = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy))) if dx or dy else 0
    return (p[0] - a[0] - fraction * dx) ** 2 + (p[1] - a[1] - fraction * dy) ** 2


def pack_ring(ring):
    """Lossless polyline6, with little-endian float64 for finer source precision."""
    if any(value != round(value, 6) for point in ring for value in point):
        numbers = [value for point in ring for value in point]
        return {"f64": base64.b64encode(struct.pack(f"<{len(numbers)}d", *numbers)).decode("ascii")}
    encoded, previous = [], (0, 0)
    for point in ring:
        current = tuple(round(value * 1e6) for value in point)
        for value, old in zip(current, previous):
            delta = value - old
            number = delta * 2 if delta >= 0 else -delta * 2 - 1
            while number >= 32:
                encoded.append(chr((number & 31 | 32) + 63))
                number >>= 5
            encoded.append(chr(number + 63))
        previous = current
    return "".join(encoded)


def topology_ownership(polygons):
    original = shape({"type": "MultiPolygon", "coordinates": polygons})
    if not original.is_valid:
        raise ValueError("Invalid source ownership geometry")
    reduced = original.simplify(TOLERANCE, preserve_topology=True)
    precise = mapping(reduced)["coordinates"]
    result, literal_rings = [], 0
    for polygon in precise:
        rings = []
        for ring in polygon:
            rounded = [[round(x, 6), round(y, 6)] for x, y in ring]
            if len(set(map(tuple, rounded))) < 3 or not LinearRing(rounded).is_simple:
                rounded = [list(p) for p in ring]
                literal_rings += 1
            rings.append(rounded)
        if not Polygon(rings[0], rings[1:]).is_valid:
            rings = [[list(p) for p in ring] for ring in polygon]
            literal_rings += len(rings)
        result.append(rings)
    if not MultiPolygon([Polygon(p[0], p[1:]) for p in result]).is_valid:
        # Rounding can make distinct nearby islands touch. Restore only the
        # simplified polygons in actual invalid pairs, never the whole country.
        for _ in range(3):
            geometries = [Polygon(p[0], p[1:]) for p in result]
            tree = STRtree(geometries)
            restore = set()
            for i, geometry in enumerate(geometries):
                for j in tree.query(geometry):
                    if j > i and not MultiPolygon([geometry, geometries[j]]).is_valid:
                        restore.update((i, int(j)))
            if not restore:
                break
            for i in restore:
                result[i] = [[list(p) for p in ring] for ring in precise[i]]
        if not MultiPolygon([Polygon(p[0], p[1:]) for p in result]).is_valid:
            # Last resort retains the already simplified valid topology, not
            # all original vertices. Float64 encoding preserves it exactly.
            result = [[[list(p) for p in ring] for ring in polygon] for polygon in precise]
    return result, {
        "method": "Topology-preserving simplification; local precision fallback only",
        "source_vertices": sum(len(ring) for polygon in polygons for ring in polygon),
        "view_vertices": sum(len(ring) for polygon in result for ring in polygon),
        "non_six_decimal_rings": sum(any(v != round(v, 6) for p in ring for v in p)
                                     for polygon in result for ring in polygon),
    }


def simplify_open(points):
    keep = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    while pending:
        first, last = pending.pop()
        if last - first < 2:
            continue
        at = max(range(first + 1, last), key=lambda i: segment_distance_sq(points[i], points[first], points[last]))
        if segment_distance_sq(points[at], points[first], points[last]) > TOLERANCE ** 2:
            keep.add(at)
            pending.extend([(first, at), (at, last)])
    return [points[i] for i in sorted(keep)]


def simplify_ring(ring):
    assert len(ring) >= 4 and ring[0] == ring[-1], "unclosed source ring"
    assert all(len(p) == 2 and all(math.isfinite(v) for v in p) for p in ring), "invalid source coordinates"
    # Split the closed ring at a far vertex so it is not simplified against a zero-length chord.
    split = max(range(1, len(ring) - 1), key=lambda i: segment_distance_sq(ring[i], ring[0], ring[0]))
    reduced = simplify_open(ring[:split + 1])[:-1] + simplify_open(ring[split:])
    rounded = [[round(x, 6), round(y, 6)] for x, y in reduced]
    if len({tuple(p) for p in rounded}) < 3:
        return ring
    return rounded


def build(cache=DEFAULT_CACHE, offline=False, codes=None):
    countries, sources, fallbacks = {}, {}, {}
    for code in codes or SOURCES:
        data, sources[code] = load_source(code, cache, offline)
        features = data["features"] if data["type"] == "FeatureCollection" else [
            data if data["type"] == "Feature" else {"geometry": data}]
        polygons = []
        for feature in features:
            geom = feature["geometry"]
            assert geom["type"] in ("Polygon", "MultiPolygon"), f"{code}: not polygons"
            polygons.extend(geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]])
        countries[code] = {"type": "MultiPolygon", "coordinates": [[simplify_ring(ring) for ring in polygon] for polygon in polygons]}
        if not shape(countries[code]).is_valid:
            coordinates, fallbacks[code] = topology_ownership(polygons)
            countries[code] = {"type": "MultiPolygon", "coordinates": coordinates}
        print(code, sum(len(ring) for polygon in polygons for ring in polygon), "source vertices ->",
              sum(len(ring) for polygon in countries[code]["coordinates"] for ring in polygon), "view vertices")
    return {
        "purpose": "Camera country ownership only; not displayed national borders or railway data.",
        "crs": "WGS84 longitude, latitude",
        "simplification_degrees": TOLERANCE,
        "coordinate_decimals": 6,
        "precision_note": "Invalid simplified ownership polygons retain valid topology or original precision; finer rings remain literal in the frontend.",
        "validity_fallbacks": fallbacks,
        "attribution": "geoBoundaries, BKG, swisstopo, IGN Spain, IGN France / france-geojson, National Georegister, Eurostat, ISTAT; per-source licences below.",
        "sources": sources,
        "countries": countries,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "view_boundaries.json")
    args = parser.parse_args()
    result = build(args.cache_dir, args.offline)
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")
    print("built", output.name, output.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
