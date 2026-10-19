"""Assemble the page: inline MapLibre CSS into src/app.html and pack label glyphs.

index.html       local version (doctype + charset, open via a local HTTP server)
dist/index.html  artifact version (no document skeleton; the host wraps it)
"""
import argparse
import base64
import gzip
import json
from pathlib import Path

from continuous_offset import display_sets

ROOT = Path(__file__).resolve().parents[1]
EUROPE = ("de", "fr", "ch", "es", "nl", "be", "it")
# South-East Asia (scripts/process_sea.py): the countries the page has a configuration for so far.
SEA = ("la", "my", "sg", "th", "id")


def pack_view_ring(ring):
    """Lossless polyline coding for six-decimal rings; finer source rings stay literal."""
    if any(value != round(value, 6) for point in ring for value in point):
        return ring
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


def assemble_page(site=None, offset_artifacts=False):
    page = (ROOT / "src" / "app.html").read_text()
    page = page.replace("/*MAPLIBRE_CSS*/", (ROOT / "vendor" / "maplibre-gl.css").read_text())
    # site.json decides what the build contains; overrides are useful for read-only contracts.
    if site is None:
        site = json.loads((ROOT / "site.json").read_text()) if (ROOT / "site.json").exists() else {}
    for code, default in (("uk", True), ("jp", False), ("kr", False), *((g, False) for g in EUROPE + SEA)):
        marker = f"/*WITH_{code.upper()}*/true"
        assert marker in page
        page = page.replace(marker, "true" if site.get(code, default) else "false")
    enabled = [g for g in EUROPE if site.get(g, False)]
    boundaries = {}
    if enabled:
        data = json.loads((ROOT / "data" / "view_boundaries.json").read_text())
        assert data["crs"] == "WGS84 longitude, latitude"
        for g in enabled:
            geom = data["countries"][g]
            assert geom["type"] == "MultiPolygon" and geom["coordinates"], f"{g}: missing view polygons"
            assert len(data["sources"][g]["sha256"]) == 64, f"{g}: missing source hash"
            boundaries[g] = [[pack_view_ring(ring) for ring in polygon] for polygon in geom["coordinates"]]
    for g in (g for g in SEA if site.get(g, False)):
        # the country's own land, from its admin_level=2 relation, as process_sea.py simplified it
        view = json.loads((ROOT / "data" / f"{g}_view.json").read_text())
        assert view["type"] == "MultiPolygon" and view["coordinates"] and view["source"]["relation"], f"{g}: missing view polygons"
        boundaries[g] = [[pack_view_ring(ring) for ring in polygon] for polygon in view["coordinates"]]
    marker = "/*VIEW_BOUNDARIES*/{}"
    assert marker in page
    page = page.replace(marker, json.dumps(boundaries, separators=(",", ":")))
    codes = ["cn", *[g for g in ("jp", "kr", "uk", *EUROPE) if site.get(g, g == "uk")]]
    manifest = {}
    sets, open_identities = display_sets(ROOT, codes)
    if offset_artifacts:
        destination = ROOT / "dist" / "offsets"
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "open-identities.json").write_text(json.dumps(open_identities, ensure_ascii=False, indent=2))
    for key, features in sets.items():
        points = [point for f in features for co in (f["geometry"]["coordinates"]
                  if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]])
                  for point in co]
        filename = key.replace(":", "-") + ".json.gz"
        manifest[key] = {"url": "dist/offsets/" + filename,
                         "bbox": [min(p[0] for p in points), min(p[1] for p in points),
                                  max(p[0] for p in points), max(p[1] for p in points)]}
        if offset_artifacts:
            destination = ROOT / "dist" / "offsets"
            destination.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(features, separators=(",", ":"), ensure_ascii=False).encode()
            (destination / filename).write_bytes(gzip.compress(payload, mtime=0))
    page = page.replace("/*CONTINUOUS_OFFSET_JS*/", (ROOT / "src" / "continuous-offset.js").read_text())
    page = page.replace("/*CONTINUOUS_OFFSET_MANIFEST*/{}", json.dumps(manifest, separators=(",", ":")))
    # The page reads vector tiles instead of whole GeoJSON files when this is on.
    assert "/*WITH_TILES*/false" in page
    return page.replace("/*WITH_TILES*/false", "true" if site.get("tiles", False) else "false")


def local_page(page):
    return '<!doctype html>\n<html lang="zh-CN">\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n' + page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdout", action="store_true", help="render current sources without writing any artifacts")
    parser.add_argument("--site-json", type=json.loads, help="in-memory site configuration for contract checks")
    args = parser.parse_args()
    if args.site_json is not None and not args.stdout:
        parser.error("--site-json requires --stdout")
    page = assemble_page(args.site_json, offset_artifacts=not args.stdout)
    local = local_page(page)
    if args.stdout:
        print(local, end="")
        return
    (ROOT / "index.html").write_text(local)
    (ROOT / "dist").mkdir(exist_ok=True)
    (ROOT / "dist" / "index.html").write_text(page)
    # Glyph ranges (Open Sans Semibold, SIL OFL), served to MapLibre by the page.
    glyphs = {f.stem: base64.b64encode(f.read_bytes()).decode() for f in sorted((ROOT / "vendor" / "glyphs" / "sans").glob("*.pbf"))}
    (ROOT / "data" / "glyphs.json").write_text(json.dumps(glyphs))
    print("built", len(local), "bytes;", len(glyphs), "glyph ranges")


if __name__ == "__main__":
    main()
