"""Cut the map's layers into vector tiles, one archive per country, so that the page fetches only what is in view.

    python3 scripts/build_tiles.py            every country of the site: China (cn) and those site.json holds
    python3 scripts/build_tiles.py jp kr      only these: a country's files depend on nothing but its own data
    python3 scripts/build_tiles.py --check    cuts nothing; checks the archives that are there against the GeoJSON
    python3 scripts/build_tiles.py --beside   cuts nothing; rewrites only the small files beside the archives

For a country it writes
    data/tiles/<country>.pmtiles    its layers as vector tiles of zoom 0 to 13, in one PMTiles archive
    data/tiles/<country>.json       what the page needs before it draws: which layers the archive has and
                                    what the page used to read off the whole files
    data/tiles/<country>.stations.json   the stations by name and place, for the search and the route fields

It reads the pipeline's results in data/ (rail_hsr.geojson, rail_conv.geojson, metro.geojson,
stations.geojson, yards.geojson, ... for China; <country>_rail.geojson, ... for the others) and
site.json, and nothing else. The GeoJSON files stay the pipeline's result: every check runs on
them, and the page still reads them when its tile switch is off. Run this last, after the scripts
that write those files. China takes a few minutes, another country well under one. Needs
tippecanoe (2.79.0 was used).

What the tiles must keep, and how:
- Every line at every zoom, only coarser further out: nothing is dropped by rate, by tile size or
  by feature count. A feature is left out of a zoom only where the page does not draw it there
  (yards below zoom 9.5, metro stations below 10, ...).
- The line on the track when zoomed in. MapLibre keeps a tile's points on a grid of 8192 across,
  which at the deepest tiles (zoom 13) is a step of 0.6 m at the equator and 0.5 m in China; the
  page draws its zooms 14 to 18 from those tiles. They are not simplified at all; the shallower
  zooms are simplified to a fraction of a screen pixel. check() reads every deepest tile back out
  of the archive, decodes it and measures it against the GeoJSON both ways, and fails above 1 m.
- The order of the features, which is the order the page draws overlapping lines in.
- Only the properties the page reads; the long ones (sources, notes) stay in the GeoJSON.
Not in the tiles: border.geojson and cities.json, two small files the page reads whole in either mode.

Why an archive: a railway is a thin thing. Cut down to zoom 13, China's railways alone are
100,000 tiles, most of them a few hundred bytes: too many files for a repository, a Pages site or
an app bundle. A PMTiles archive is one file that is read in pieces, by HTTP range requests
(vendor/pmtiles.js in the page). Its tiles are gzipped inside it, since a static host does not
compress them on the way.
"""
import argparse
import gzip
import json
import math
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import shapely
import shapely.geometry

ROOT = Path(__file__).resolve().parents[1]
DATA, OUT = ROOT / "data", ROOT / "data" / "tiles"
TIPPECANOE = shutil.which("tippecanoe") or "/opt/homebrew/bin/tippecanoe"
MAXZOOM = 13                # the deepest tiles; the page draws zooms 14 to 18 from them
# MapLibre rounds a tile's points onto a grid of 8192 across (2^13), and tippecanoe rounds onto the
# grid it is given. The deepest tiles are cut on exactly MapLibre's grid: a finer one would be
# rounded twice (measured: 0.58 m off instead of 0.39), a coarser one is a coarser line.
DETAIL = 13
LIMIT_M = 1.0               # the furthest a drawn line may lie from the GeoJSON at the deepest zoom
FAST = ["hsr400", "hsr350", "hsr300", "hsr250", "hsr200", "hsr160", "hsrslow"]

# tile layer -> China's file, the file of a country abroad (<code>_<name>.geojson), the properties
# the page reads from it, and the lowest zoom the page draws a feature of it at. A tile layer has
# the name of the page's source it stands in for; a country has the layers it has files for.
LAYERS = {
    "hsr": dict(cn="rail_hsr", keep="c n d db v e de off", zoom=lambda p: 0),
    # China's branch lines appear at zoom 3.5; the classes abroad have no such rule
    "conv": dict(cn="rail_conv", abroad="rail", keep="c n g jk mini lc off d e o de",
                 zoom=lambda p: 3 if p.get("c") == "branch" and "g" not in p else 0),
    "shared": dict(cn="rail_shared", keep="c n on d db v e de", zoom=lambda p: 0),
    "build": dict(cn="rail_build", abroad="build", keep="c n h g", zoom=lambda p: 0),
    "metro": dict(cn="metro", abroad="metro", keep="n ct col k g jk off", zoom=lambda p: 4),
    # stations on high-speed lines from zoom 5, the others from 8.5; metro stations from 10
    # (a country abroad has one stations file; its metro stations are marked m; t marks a tram stop,
    # which the page's light-rail switch hides with the trams)
    "stations": dict(cn="stations", abroad="stations", abroad_if=lambda p: not p.get("m"), keep="n nz ne h g",
                     zoom=lambda p: 5 if p.get("h") else 8, label=lambda p: 8 if p.get("h") else 10),
    "metro-stations": dict(cn="metro_stations", abroad="stations", abroad_if=lambda p: bool(p.get("m")),
                           keep="n nz ne g m t", zoom=lambda p: 10, label=lambda p: 12),
    "yards": dict(cn="yards", abroad="yards", keep="", zoom=lambda p: 9),
    "depots": dict(cn="depots", abroad="depots", keep="n nz ne", zoom=lambda p: 9, label=lambda p: 10),
}
LINE_LAYERS = ["hsr", "conv", "shared", "build", "metro", "yards"]
# A point's names beside n (nz, ne: scripts/names.py) are what the page writes under its dot, from
# the zoom its label shows at (label above); below that the point comes without them, which keeps
# them out of the many tiles of the shallower zooms. A line's names are not in the tiles: the page
# writes no line names on the map, and takes them from the lists it loads whole (lines.json, the
# metro cities), by n.
NAMES = ("nz", "ne")


def countries():
    """China and the countries abroad that the site holds, as scripts/build.py reads them from site.json."""
    site = json.loads((ROOT / "site.json").read_text()) if (ROOT / "site.json").exists() else {}
    return ["cn"] + [g for g, default in (("jp", False), ("kr", False), ("uk", True)) if site.get(g, default)]


def features(layer, g):
    """The features of one tile layer of one country, in the order the page holds them."""
    spec = LAYERS[layer]
    path = DATA / (f"{spec['cn']}.geojson" if g == "cn" else f"{g}_{spec.get('abroad')}.geojson")
    if (g != "cn" and "abroad" not in spec) or not path.exists():
        return []
    return [f for f in json.loads(path.read_text())["features"]
            if g == "cn" or "abroad_if" not in spec or spec["abroad_if"](f["properties"])]


def tippecanoe_input(g):
    """One feature per line for tippecanoe, each naming its tile layer and its lowest zoom.
    Returns the lines and the layers the country has."""
    lines, layers = [], []
    for layer, spec in LAYERS.items():
        keep = spec["keep"].split()
        for f in features(layer, g):
            p = f["properties"]
            if layer == "metro-stations":
                p = {**p, "m": 1}             # the page marks every metro station; in a tile it has to come marked
            if layer not in layers:
                layers.append(layer)
            props = {k: p[k] for k in keep if p.get(k) is not None}
            low, label = spec["zoom"](p), spec.get("label", lambda p: 0)(p)
            parts = [(low, None, props)]
            if label > low and any(k in props for k in NAMES):
                parts = [(low, label - 1, {k: v for k, v in props.items() if k not in NAMES}), (label, None, props)]
            for minzoom, maxzoom, props in parts:
                lines.append(json.dumps({
                    "type": "Feature",
                    "tippecanoe": {"layer": layer, "minzoom": minzoom, **({"maxzoom": maxzoom} if maxzoom is not None else {})},
                    "properties": props,
                    "geometry": f["geometry"],
                }, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines) + "\n", layers


def cut(g, out, maxzoom=MAXZOOM):
    """Cuts one country's tiles into <out>/<g>.pmtiles. Returns the layers it has."""
    out.mkdir(parents=True, exist_ok=True)
    text, layers = tippecanoe_input(g)
    # tippecanoe notes its command line in the archive: the features go in by standard input and
    # the archive is named without its folder, so that the same data gives the same file anywhere
    subprocess.run([
        TIPPECANOE, "--output", f"{g}.pmtiles", "--force", "--quiet",
        f"--name=Rail Globe {g}", "--description=", "--attribution=© OpenStreetMap contributors",
        "--minimum-zoom=0", f"--maximum-zoom={maxzoom}", f"--full-detail={DETAIL}", "--low-detail=12",
        # nothing dropped: no rate for points, no limit on a tile's size or its feature count
        "--drop-rate=1", "--no-feature-limit", "--no-tile-size-limit",
        # the deepest zoom as the pipeline made it; the others simplified, each to its own grid
        "--simplify-only-low-zooms", "--no-tiny-polygon-reduction",
        # wide lines and their sideways offsets reach a little across a tile's edge
        "--buffer=8",
        "--preserve-input-order", "--no-tile-stats",
    ], check=True, cwd=out, input=text.encode())
    return layers


def beside(g, layers, out):
    """<g>.json, a few bytes the page reads before it draws: the tile layers the country has, and
    what the page used to read off the whole files: the [class, speed band] pairs the lines of a
    country abroad have, and how many lines are being built.
    <g>.stations.json, which the page fetches when the map is up: the names and places of the
    stations as plain columns, for the search and the route fields, which list stations that are
    not on the screen (the page draws them from the tiles). A place is kept to 1e-5 degrees, about
    a metre; g is China's number of the station in the route network, h marks a station on a
    high-speed line, nz and ne are its names in Chinese and English where it has them (null
    where not; see scripts/names.py)."""
    def columns(feats):
        cols = {"n": [f["properties"]["n"] for f in feats],
                "x": [round(f["geometry"]["coordinates"][0] * 1e5) for f in feats],
                "y": [round(f["geometry"]["coordinates"][1] * 1e5) for f in feats]}
        if g == "cn":
            cols["g"] = [f["properties"].get("g") for f in feats]
        if any(f["properties"].get("h") for f in feats):
            cols["h"] = [1 if f["properties"].get("h") else 0 for f in feats]
        for key in ("nz", "ne"):
            if any(key in f["properties"] for f in feats):
                cols[key] = [f["properties"].get(key) for f in feats]
        return cols
    write = lambda name, value: (out / name).write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    write(f"{g}.json", {
        "layers": layers,
        "bands": sorted({(f["properties"].get("jk"), f["properties"].get("c")) for f in features("conv", g) if f["properties"].get("c") in FAST}) if g != "cn" else [],
        "build": len(features("build", g)),
    })
    write(f"{g}.stations.json", {"rail": columns(features("stations", g)), "metro": columns(features("metro-stations", g))})


# ---- reading an archive back (PMTiles version 3) ----

def varint(buf, i):
    value = shift = 0
    while True:
        b = buf[i]
        i += 1
        value |= (b & 0x7F) << shift
        if b < 0x80:
            return value, i
        shift += 7


def archive(path):
    """The header of an archive: where its parts are and how they are compressed."""
    with path.open("rb") as f:
        head = f.read(127)
    if head[:7] != b"PMTiles" or head[7] != 3:
        raise ValueError(f"{path} is not a PMTiles 3 archive")
    u64 = lambda at: int.from_bytes(head[at:at + 8], "little")
    return dict(root=(u64(8), u64(16)), leaves=u64(40), data=u64(56), tiles=u64(72), contents=u64(88),
                inner=head[97], squeezed=head[98], minzoom=head[100], maxzoom=head[101])


def directory(f, info, at, size):
    """The entries of one directory, a leaf directory followed into: (tile id, how many tiles in a
    row have this content, where it is, how long it is)."""
    f.seek(at)
    raw = f.read(size)
    data = gzip.decompress(raw) if info["inner"] == 2 else raw
    n, i = varint(data, 0)
    ids, runs, sizes, places, last = [], [], [], [], 0
    for _ in range(n):
        step, i = varint(data, i)
        last += step
        ids.append(last)
    for column in (runs, sizes):
        for _ in range(n):
            value, i = varint(data, i)
            column.append(value)
    for k in range(n):
        value, i = varint(data, i)
        places.append(places[k - 1] + sizes[k - 1] if value == 0 and k else value - 1)   # 0: right after the one before
    for tile, run, length, place in zip(ids, runs, sizes, places):
        if run:
            yield tile, run, place, length
        else:
            yield from directory(f, info, info["leaves"] + place, length)


def zxy(tile):
    """A tile's zoom, column and row from its number in the archive (zoom by zoom, along a Hilbert curve)."""
    z = 0
    while tile >= 4 ** z:
        tile -= 4 ** z
        z += 1
    x = y = 0
    s = 1
    while s < 2 ** z:
        rx = 1 & (tile >> 1)
        ry = 1 & (tile ^ rx)
        if ry == 0:
            if rx == 1:
                x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        x += s * rx
        y += s * ry
        tile >>= 2
        s *= 2
    return z, x, y


def entries(path):
    """Every tile of an archive: (zoom, x, y, where its content is, how long it is)."""
    info = archive(path)
    with path.open("rb") as f:
        for tile, run, place, length in directory(f, info, *info["root"]):
            for k in range(run):
                yield (*zxy(tile + k), place, length)


def tile_bytes(f, info, place, length):
    f.seek(info["data"] + place)
    raw = f.read(length)
    return gzip.decompress(raw) if info["squeezed"] == 2 else raw


# ---- the check: every deepest tile, read out of the archive and decoded here, against the GeoJSON ----

def fields(buf):
    """The fields of one protobuf message: (number, wire type, value); bytes for the nested ones."""
    i, n = 0, len(buf)
    while i < n:
        key, i = varint(buf, i)
        kind = key & 7
        if kind == 0:
            value, i = varint(buf, i)
        elif kind == 2:
            size, i = varint(buf, i)
            value, i = buf[i:i + size], i + size
        elif kind == 5:
            value, i = buf[i:i + 4], i + 4
        elif kind == 1:
            value, i = buf[i:i + 8], i + 8
        else:
            raise ValueError(f"wire type {kind}")
        yield key >> 3, kind, value


def decode(tile):
    """A vector tile as {layer: (extent, [(geometry type, [[(x, y), ...], ...]), ...])}."""
    layers = {}
    for number, _, layer in fields(tile):
        if number != 3:
            continue
        name, extent, feats = None, 4096, []
        for n, _, v in fields(layer):
            if n == 1:
                name = bytes(v).decode()
            elif n == 5:
                extent = v
            elif n == 2:
                kind, parts = 0, []
                for fn, _, fv in fields(v):
                    if fn == 3:
                        kind = fv
                    elif fn == 4:
                        x = y = j = 0
                        while j < len(fv):
                            command, j = varint(fv, j)
                            op, count = command & 7, command >> 3
                            for _ in range(count if op != 7 else 0):
                                dx, j = varint(fv, j)
                                dy, j = varint(fv, j)
                                x += (dx >> 1) ^ -(dx & 1)
                                y += (dy >> 1) ^ -(dy & 1)
                                if op == 1:
                                    parts.append([])
                                parts[-1].append((x, y))
                feats.append((kind, parts))
        layers[name] = (extent, feats)
    return layers


R = 6378137.0


def mercator(lnglat):
    """Web Mercator metres; a length there is the length on the ground divided by cos(latitude)."""
    a = np.asarray(lnglat, dtype=float).reshape(-1, 2)
    return np.column_stack([np.radians(a[:, 0]) * R, np.log(np.tan(np.pi / 4 + np.radians(a[:, 1]) / 2)) * R])


def ground(distance, y):
    """Mercator distances at Mercator northings y, in metres on the ground."""
    return distance * np.cos(2 * np.arctan(np.exp(np.asarray(y) / R)) - np.pi / 2)


def lnglat(xy):
    return f"{math.degrees(xy[0] / R):.6f}, {math.degrees(2 * math.atan(math.exp(xy[1] / R)) - math.pi / 2):.6f}"


def source_lines(layer, g, step=8):
    """The pipeline's lines in short pieces: the nearest piece to a point is then found quickly.
    A part shorter than the limit (the pipeline leaves a few of two identical points) cannot be
    missed by more than the limit, and a tile may leave it out: such parts are returned apart."""
    parts, tiny = [], []
    for f in features(layer, g):
        geometry = f["geometry"]
        for line in geometry["coordinates"] if geometry["type"] == "MultiLineString" else [geometry["coordinates"]] if geometry["type"] == "LineString" else []:
            xy = mercator(line)
            short = ground(np.hypot(*np.diff(xy, axis=0).T), xy[1:, 1]).sum() < LIMIT_M
            (tiny if short else parts).extend(shapely.linestrings(xy[i:i + step + 1]) for i in range(0, len(xy) - 1, step))
    return parts, tiny


def drawn_lines(job):
    """The lines of some deepest tiles as MapLibre places them: {layer: [coordinates in Mercator metres]}."""
    path, tiles = job
    info = archive(path)
    world = 2 * math.pi * R
    found = {layer: [] for layer in LINE_LAYERS}
    with path.open("rb") as f:
        for z, x, y, place, length in tiles:
            size = world / 2 ** z
            for layer, (extent, feats) in decode(tile_bytes(f, info, place, length)).items():
                if layer not in found:
                    continue
                for kind, lines in feats:
                    for line in lines:
                        if kind == 2 and len(line) > 1:
                            # onto MapLibre's grid of 8192, rounded as JavaScript rounds (halves upward)
                            a = np.floor(np.asarray(line, dtype=float) * (8192 / extent) + 0.5) / 8192
                            found[layer].append(np.column_stack([(x + a[:, 0]) * size - world / 2, world / 2 - (y + a[:, 1]) * size]))
    return found


def check(g, out):
    """One country's deepest tiles, as they are in its archive, against its GeoJSON, both ways, in
    metres on the ground: how far a point of a tile lies from the pipeline's line, and how far a
    point of the pipeline's line lies from what the tiles draw. Returns the largest of all."""
    path = out / f"{g}.pmtiles"
    info = archive(path)
    by_zoom = {}
    for z, x, y, place, length in entries(path):
        by_zoom.setdefault(z, []).append((z, x, y, place, length))
    deepest = by_zoom.get(info["maxzoom"], [])
    drawn = {layer: [] for layer in LINE_LAYERS}
    with ProcessPoolExecutor() as pool:
        for found in pool.map(drawn_lines, [(path, deepest[i:i + 3000]) for i in range(0, len(deepest), 3000)]):
            for layer, lines in found.items():
                drawn[layer] += lines
    print(f"  {g}: {path.stat().st_size / 1e6:.1f} MB, zoom {info['minzoom']} to {info['maxzoom']}, {info['tiles']} tiles ({info['contents']} different): "
          + ", ".join(f"{z}: {len(tiles)}" for z, tiles in sorted(by_zoom.items())))
    worst = 0.0
    for layer in LINE_LAYERS:
        source, tiny = source_lines(layer, g)
        tiles = [shapely.linestrings(line) for line in drawn[layer]]
        if not source:
            continue
        if not tiles:
            print(f"  {g} {layer}: no zoom {info['maxzoom']} tile holds it", file=sys.stderr)
            worst = float("inf")
            continue
        there = shapely.get_coordinates(tiles)
        _, d = shapely.STRtree(source + tiny).query_nearest(shapely.points(there), return_distance=True, all_matches=False)
        to_source = ground(d, there[:, 1])
        here = shapely.get_coordinates(source)
        _, d = shapely.STRtree(tiles).query_nearest(shapely.points(here), return_distance=True, all_matches=False)
        to_tiles = ground(d, here[:, 1])
        worst = max(worst, to_source.max(), to_tiles.max())
        print(f"  {g} {layer}: a point of a zoom {info['maxzoom']} tile is at most {to_source.max():.2f} m from the GeoJSON (99.9% within {np.percentile(to_source, 99.9):.2f}), "
              f"a point of the GeoJSON at most {to_tiles.max():.2f} m from the tiles (99.9% within {np.percentile(to_tiles, 99.9):.2f})"
              + (f"; {len(tiny)} pieces of parts shorter than {LIMIT_M:g} m in the GeoJSON need not be in a tile" if tiny else ""))
        for name, far, at in (("tile", to_source, there), ("GeoJSON", to_tiles, here)):
            for i in np.argsort(far)[::-1][:5]:
                if far[i] > LIMIT_M:
                    print(f"    a {name} point {far[i]:.2f} m off at {lnglat(at[i])}", file=sys.stderr)
    return worst


def main():
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("countries", nargs="*", help="cn, jp, ... (default: China and the countries site.json holds)")
    args.add_argument("--check", action="store_true", help="do not cut; check the archives that are there")
    args.add_argument("--beside", action="store_true", help="do not cut; only rewrite the small files beside the archives")
    args.add_argument("--out", type=Path, default=OUT, help="another folder than data/tiles, for an experiment")
    args.add_argument("--maxzoom", type=int, default=MAXZOOM)
    args = args.parse_args()
    worst = 0.0
    for g in args.countries or countries():
        if args.beside:
            beside(g, tippecanoe_input(g)[1], args.out)
            continue
        if not args.check:
            beside(g, cut(g, args.out, args.maxzoom), args.out)
        far = check(g, args.out)
        print(f"  {g}: furthest from the GeoJSON: {far:.2f} m (limit {LIMIT_M} m)")
        worst = max(worst, far)
    sys.exit(0 if worst <= LIMIT_M else 1)


if __name__ == "__main__":
    main()
