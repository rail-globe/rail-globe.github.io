"""Assemble the page: inline MapLibre CSS into src/app.html and pack label glyphs.

index.html       local version (doctype + charset, open via a local HTTP server)
dist/index.html  artifact version (no document skeleton; the host wraps it)
"""
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
page = (ROOT / "src" / "app.html").read_text()
page = page.replace("/*MAPLIBRE_CSS*/", (ROOT / "vendor" / "maplibre-gl.css").read_text())
# site.json decides what this build of the site contains, e.g. {"uk": false} leaves the UK out.
site = json.loads((ROOT / "site.json").read_text()) if (ROOT / "site.json").exists() else {}
assert "/*WITH_UK*/true" in page
page = page.replace("/*WITH_UK*/true", "true" if site.get("uk", True) else "false")
local = '<!doctype html>\n<html lang="zh-CN">\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n' + page
(ROOT / "index.html").write_text(local)
(ROOT / "dist").mkdir(exist_ok=True)
(ROOT / "dist" / "index.html").write_text(page)
# Glyph ranges (Open Sans Semibold, SIL OFL) as base64, served to MapLibre by the page itself.
glyphs = {f.stem: base64.b64encode(f.read_bytes()).decode() for f in sorted((ROOT / "vendor" / "glyphs" / "sans").glob("*.pbf"))}
(ROOT / "data" / "glyphs.json").write_text(json.dumps(glyphs))
print("built", len(local), "bytes;", len(glyphs), "glyph ranges")
