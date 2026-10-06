"""Build China's national land boundary (plus the South China Sea dashed line) for the map.

Source : Aliyun DataV.GeoAtlas (areas_v3), GCJ-02.
Method : the country-level outline is coarse (~6 km per vertex), so border counties are fetched
         individually and unioned with an eroded country polygon; the exterior ring between the
         Yalu and Beilun river mouths is the land boundary. Coordinates are converted to WGS-84.
Output : data/border.geojson
"""
import json
import math
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "border"
CACHE.mkdir(parents=True, exist_ok=True)
API = "https://geo.datav.aliyun.com/areas_v3/bound/{}.json"
BORDER_PROVINCES = ["210000", "220000", "230000", "150000", "620000", "650000", "540000", "530000", "450000"]
NEAR = 0.25            # degrees: administrative units this close to the coarse boundary are refined
YALU = (124.30, 39.80)   # China-DPRK boundary meets the Yellow Sea
BEILUN = (108.06, 21.52)  # China-Vietnam boundary meets the Beibu Gulf


def get(code):
    """Fetch one DataV file with on-disk cache. Returns None when the file does not exist."""
    p = CACHE / f"{code}.json"
    if p.exists():
        txt = p.read_text()
        return json.loads(txt) if txt.strip() else None
    req = urllib.request.Request(API.format(code), headers={"User-Agent": "Mozilla/5.0 CNRailMap/1.0"})
    for attempt in range(6):
        try:
            data = urllib.request.urlopen(req, timeout=40).read()
            p.write_bytes(data)
            time.sleep(0.1)
            return json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                p.write_text("")
                return None
            err = e
        except Exception as e:  # transient network errors
            err = e
        time.sleep(1 + attempt * 2)
    raise RuntimeError(f"{code}: {err}")


def geom(feature):
    g = shape(feature["geometry"])
    return g if g.is_valid else g.buffer(0)


# --- GCJ-02 -> WGS-84 (iterative inverse of the standard forward transform) ---
A, EE = 6378245.0, 0.00669342162296594323


def _dlat(x, y):
    r = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    r += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    r += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return r


def _dlon(x, y):
    r = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    r += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    r += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return r


def wgs_to_gcj(lon, lat):
    dlat, dlon = _dlat(lon - 105.0, lat - 35.0), _dlon(lon - 105.0, lat - 35.0)
    rad = lat / 180.0 * math.pi
    magic = 1 - EE * math.sin(rad) ** 2
    sq = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sq) * math.pi)
    dlon = (dlon * 180.0) / (A / sq * math.cos(rad) * math.pi)
    return lon + dlon, lat + dlat


def gcj_to_wgs(lon, lat):
    wx, wy = lon, lat
    for _ in range(4):
        gx, gy = wgs_to_gcj(wx, wy)
        wx, wy = wx + (lon - gx), wy + (lat - gy)
    return round(wx, 5), round(wy, 5)


def split_ring(ring, a, b):
    """Return the longer of the two arcs of a closed ring between the vertices nearest a and b."""
    pts = list(ring.coords)[:-1]
    ia = min(range(len(pts)), key=lambda i: (pts[i][0] - a[0]) ** 2 + (pts[i][1] - a[1]) ** 2)
    ib = min(range(len(pts)), key=lambda i: (pts[i][0] - b[0]) ** 2 + (pts[i][1] - b[1]) ** 2)
    lo, hi = sorted((ia, ib))
    arc1, arc2 = pts[lo:hi + 1], pts[hi:] + pts[:lo + 1]
    return max((LineString(arc1), LineString(arc2)), key=lambda l: l.length)


# 1. coarse country polygon and coarse land boundary (used only to choose what to refine)
country = geom(get("100000")["features"][0])
mainland = max(country.geoms, key=lambda g: g.area)
coarse_border = split_ring(mainland.exterior, YALU, BEILUN)
print(f"coarse land boundary: {len(coarse_border.coords)} vertices")

# 2. walk province -> prefecture -> county, keeping units near the boundary
counties = []
for prov in BORDER_PROVINCES:
    for pref in get(prov + "_full")["features"]:
        pp = pref["properties"]
        if geom(pref).distance(coarse_border) > NEAR:
            continue
        kids = get(f"{pp['adcode']}_full") if pp.get("level") == "city" and pp.get("childrenNum", 0) else None
        if not kids:
            counties.append(str(pp["adcode"]))
            continue
        for c in kids["features"]:
            if geom(c).distance(coarse_border) <= NEAR:
                counties.append(str(c["properties"]["adcode"]))
print(f"refining {len(counties)} border units")

with ThreadPoolExecutor(4) as ex:
    detailed = [geom(d["features"][0]) for d in ex.map(get, counties) if d]

# 3. union with an eroded interior; the exterior between the two river mouths is the land boundary
solid = unary_union(detailed + [mainland.buffer(-0.2)]).buffer(0.004).buffer(-0.004)
solid = max(solid.geoms, key=lambda g: g.area) if solid.geom_type == "MultiPolygon" else solid
border = split_ring(solid.exterior, YALU, BEILUN).simplify(0.0003, preserve_topology=False)
land = [gcj_to_wgs(x, y) for x, y in border.coords]
print(f"land boundary: {len(land)} vertices, ~{border.length * 100:.0f} km (rough)")

# 4. South China Sea dashed line (drawn as dash-shaped polygons in the source)
jd = next(f for f in get("100000_full")["features"] if str(f["properties"]["adcode"]).endswith("JD"))
dashes = [[[gcj_to_wgs(x, y) for x, y in ring] for ring in poly] for poly in jd["geometry"]["coordinates"]]

out = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"k": "land"}, "geometry": {"type": "LineString", "coordinates": land}},
    {"type": "Feature", "properties": {"k": "sea"}, "geometry": {"type": "MultiPolygon", "coordinates": dashes}},
]}
p = ROOT / "data" / "border.geojson"
p.write_text(json.dumps(out, separators=(",", ":")))
print(f"{p.name}: {p.stat().st_size / 1e3:.0f} KB")
