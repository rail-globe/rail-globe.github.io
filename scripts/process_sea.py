"""South-East Asia through the shared country pipeline (scripts/country.py): Laos, Thailand,
Malaysia, Singapore and Indonesia, one configuration each.

    python3 scripts/extract_osm.py la         laos-latest.osm.pbf -> data/raw/extract_la.pkl (with its border)
    python3 scripts/process_sea.py la         -> data/la_rail.geojson, la_metro.geojson, la_build.geojson,
                                                 la_stations.geojson, la_lines.json, la_metro_cities.json,
                                                 la_facts.json, la_yards.geojson, la_depots.geojson, la_view.json

What the five share, and is here once:

- Each country is its own land. The Geofabrik extracts are cut wider than the border (the Laos
  file has the Chinese end of the Friendship Tunnel, the Thai end of the Friendship Bridge) and
  one file holds Malaysia, Singapore and Brunei, so every track, station and named yard is clipped
  to the country's boundary=administrative, admin_level=2 relation, read from the same file by
  scripts/extract_osm.py. Where two countries are both drawn from OSM their pieces meet on the
  same border ways. Where a neighbour's line already ends a little way beyond the cut (China's
  中老昆万线 ends at the node where OSM's track changes its name, 38 m north of the border in
  OSM), the piece is continued along its own OSM way to that end, so that the two meet at one
  point; nothing else beyond the border is drawn.
- Names: n is the name in the country's own writing. Lao names in OSM often carry the Chinese
  name after them (ຫຼວງພະບາງ 琅勃拉邦); the Chinese is taken off n, and the Chinese name comes
  only from the country's table (data/<g>_names.tsv), each row with its source, never from OSM's
  name:zh. The page shows Thai and Lao names with their Chinese name, else their English one
  (ລາວ (English)); the other three with their Chinese name or alone.
- Classes: fast lines by name, with their design speed and its source (FAST); a line can be put
  in a class by name where the tags say otherwise (KIND); else main or branch by usage. The class
  of 160 km/h lines is called 快速铁路 in every country that has one (the China–Laos railway,
  Malaysia's ECRL once it opens).
"""
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

sys.path.insert(0, str(Path(__file__).resolve().parent))
from country import LIKE_EUROPE, OUT, Country, platform_siding, run

HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")
JOIN_M = 200          # metres: how far beyond the border a piece may run along its own way to meet a neighbour's line end
SAME_POINT_M = 1.0    # metres: a neighbour's line end this close to a vertex of the way is that vertex
VIEW_TOL = 0.01       # degrees: the outline the page tells the country by (which country a place is in)


def metres(a, b):
    return math.hypot((a[0] - b[0]) * math.cos(math.radians((a[1] + b[1]) / 2)), a[1] - b[1]) * 111320


def without_han(name):
    """A name without the Chinese written after it (ທາງລົດໄຟ ລາວ-ຈີນ 磨万铁路 -> ທາງລົດໄຟ ລາວ-ຈີນ),
    or the name as it is if it is all Chinese."""
    name = name or ""
    if not HAN.search(name):
        # (a name with no Chinese keeps its brackets: "BU 11 (Bandar Utama 11)" had lost its last one, 2026-10-19)
        return re.sub(r"\s+", " ", name).strip()
    rest = re.sub(r"[（(]\s*[)）]", " ", HAN.sub(" ", name))      # the brackets the Chinese stood in
    rest = re.sub(r"\s+", " ", rest).strip(" -–—/;,")
    return rest or re.sub(r"\s+", " ", name).strip()


def land_of(territory):
    polys = [Polygon(rings[0], rings[1:]) for rings in territory["polygons"]]
    land = unary_union(polys)
    if land.is_empty or not land.is_valid:
        sys.exit(f"the territory of {territory['iso']} is not a valid area")
    return land


def neighbour_ends(code):
    """The ends of the lines already drawn by the countries around: China's railway files, and
    the rail files of the other countries of this script."""
    names = ["rail_hsr", "rail_conv", "rail_shared", "rail_build"] + [f"{g}_{k}" for g in SEA if g != code for k in ("rail", "build")]
    ends = []
    for name in names:
        path = OUT / f"{name}.geojson"
        if not path.exists():
            continue
        for f in json.loads(path.read_text())["features"]:
            geom = f["geometry"]
            for co in geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]:
                if len(co) > 1:
                    ends += [(name, tuple(co[0])), (name, tuple(co[-1]))]
    return ends


def clip(ex, code, joins_out=None):
    """The extract with only what lies on the country's land (see the docstring). joins_out:
    a list that receives one row per piece continued to a neighbour's line end."""
    land = land_of(ex["territory"])
    inside, edge = prep(land), land.boundary
    near = [(name, p) for name, p in neighbour_ends(code) if edge.distance(Point(p)) * 111320 < JOIN_M * 2]
    ways, cut, dropped, joined = [], 0, 0, []
    next_id = {}
    for wid, t, co in ex["ways"]:
        line = LineString(co)
        if inside.contains(line):
            ways.append((wid, t, co))
            continue
        if not inside.intersects(line):
            dropped += 1
            continue
        part = line.intersection(land)
        pieces = [g for g in (part.geoms if hasattr(part, "geoms") else [part]) if g.geom_type == "LineString" and g.length > 0]
        cut += 1
        for k, piece in enumerate(pieces):
            pco = [(round(x, 7), round(y, 7)) for x, y in piece.coords]
            for at_start in (True, False):
                end = Point(pco[0] if at_start else pco[-1])
                if edge.distance(end) > 1e-7:
                    continue
                # the segment of the way the cut lies on, and its vertex outside the land
                i = min(range(len(co) - 1), key=lambda j: LineString(co[j:j + 2]).distance(end))
                step = 1 if not inside.contains(Point(co[i + 1])) else -1
                j, walked, path = (i + 1 if step == 1 else i), metres(end.coords[0], co[i + 1] if step == 1 else co[i]), []
                while 0 <= j < len(co) and walked <= JOIN_M:
                    path.append(co[j])
                    hit = next((name for name, p in near if metres(p, co[j]) <= SAME_POINT_M), None)
                    if hit:
                        # (a neighbour's end less than a metre beyond the cut is the cut: the two meet
                        # already, as Thailand's and Laos's halves of the Friendship Bridge do)
                        if walked >= SAME_POINT_M:
                            pco = (path[::-1] + pco) if at_start else (pco + path)
                            joined.append({"way": wid, "neighbour": hit, "at": list(co[j]), "beyond_border_m": round(walked, 1)})
                        break
                    j += step
                    if 0 <= j < len(co):
                        walked += metres(co[j - step], co[j])
            if len(pco) > 1:
                ways.append((wid if k == 0 else wid * 1000 + k, t, pco))   # (no OSM way id is that large)
    keep = lambda lon, lat: inside.covers(Point(lon, lat))
    conf = SEA[code]
    # a station's name without the code of its platform on the line map (Kuala Lumpur's "KG21 Cochrane",
    # name:en "Cochrane"), where the country writes them so
    plain_station = (lambda name: conf["STATION_CODE"].sub("", without_han(name)).strip()) if conf.get("STATION_CODE") else without_han
    stations = [(dict(t, name=plain_station(t.get("name"))) if t.get("name") else t, lon, lat)
                for t, lon, lat in ex["stations"] if keep(lon, lat)]
    named = [dict(o, name=without_han(o["name"])) for o in ex.get("named") or [] if keep(*o["at"])]
    places = [(kind, dict(t, name=without_han(t.get("name"))) if t.get("name") else t, lon, lat)
              for kind, t, lon, lat in ex.get("places") or [] if keep(lon, lat)]
    print(f"{code}: clipped to relation {ex['territory']['relation']} ({ex['territory']['name']}): "
          f"{len(ex['ways'])} ways -> {len(ways)} ({cut} cut at the border, {dropped} outside); "
          f"stations {len(ex['stations'])} -> {len(stations)}; named ground {len(ex.get('named') or [])} -> {len(named)}; "
          f"continued to a neighbour's line end: {joined or 'none'}", flush=True)
    if joins_out is not None:
        joins_out += joined
    if conf.get("GENERIC_EN"):
        ways = [(wid, {k: v for k, v in t.items() if not (k == "name:en" and v in conf["GENERIC_EN"])}, co) for wid, t, co in ways]
    if conf.get("NOT_OPEN"):
        before = sum(1 for _, t, _ in ways if t.get("railway") == "rail")
        ways = [(wid, dict(t, railway="construction", construction="rail") if t.get("railway") == "rail" and not t.get("service")
                 and (t.get("name") or "") in conf["NOT_OPEN"] else t, co) for wid, t, co in ways]
        print(f"{code}: {before - sum(1 for _, t, _ in ways if t.get('railway') == 'rail')} ways of lines not open taken as being built", flush=True)
    relations = light_routes(conf, ex["relations"])
    if conf.get("NOT_NAMING"):
        relations = [r for r in relations if not (r[1].get("route") == "railway" and (r[1].get("name") or "") in conf["NOT_NAMING"])]
    if conf.get("SERVICE_RAILWAY"):
        # route=railway relations that are train services, not the line a track belongs to (Malaysia's
        # Ekspres Rakyat Timuran, Shuttle Timuran and Shuttle Selatan, network KTM Intercity and KTM
        # Komuter): a track in one of them and in its line's relation would have two names.
        kept = [r for r in relations if not (r[1].get("route") == "railway" and conf["SERVICE_RAILWAY"].search(r[1].get("network") or ""))]
        print(f"{code}: {len(relations) - len(kept)} route=railway relations of train services left out", flush=True)
        relations = kept
    RELATIONS[code], TERRITORY[code] = relations, ex["territory"]
    return {**ex, "ways": ways, "stations": stations, "named": named, "places": places, "relations": relations}


MEET_M = 150          # metres: a drawn line's end this near a neighbour's line end on the border is taken to it


def meet_neighbours(code, territory):
    """Where a neighbour's railway line ends on this country's border and one of this country's
    drawn lines ends near it, but not on it, the line is drawn on to that point. Both countries
    cut their track at the same border way, but each draws one track of a station's several
    (scripts/single_track.py), and at Padang Besar Malaysia's drawn track ends 68 m short of the
    point where Thailand's leaves the border. Returns one row per line so drawn on."""
    path = OUT / f"{code}_rail.geojson"
    data = json.loads(path.read_text())
    edge = land_of(territory).boundary
    theirs = [(name, p) for name, p in neighbour_ends(code) if edge.distance(Point(p)) * 111320 < 2]
    ends = []                                             # (feature, part or None, at the start?)
    for f in data["features"]:
        geom = f["geometry"]
        parts = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
        for k, co in enumerate(parts):
            ends += [(f, k if geom["type"] == "MultiLineString" else None, True), (f, k if geom["type"] == "MultiLineString" else None, False)]
    point = lambda f, k, start: (f["geometry"]["coordinates"][k] if k is not None else f["geometry"]["coordinates"])[0 if start else -1]
    met = []
    for name, p in theirs:
        near = sorted((metres(point(*e), p), i) for i, e in enumerate(ends))
        if not near or near[0][0] < SAME_POINT_M or near[0][0] > MEET_M:
            continue                                      # already meeting, or nothing of ours near
        f, k, start = ends[near[0][1]]
        co = f["geometry"]["coordinates"][k] if k is not None else f["geometry"]["coordinates"]
        co.insert(0, list(p)) if start else co.append(list(p))
        met.append({"line": f["properties"].get("n"), "neighbour": name, "at": list(p), "drawn_on_m": round(near[0][0], 1)})
    if met:
        from owned_output import atomic_json
        atomic_json(path, data)
    print(f"{code}: lines drawn on to a neighbour's line end on the border: {met or 'none'}", flush=True)
    return met


def write_view(ex, code):
    """The country's outline for the page (which country a place is in), simplified."""
    land = land_of(ex["territory"]).simplify(VIEW_TOL, preserve_topology=True)
    polys = list(land.geoms) if isinstance(land, MultiPolygon) else [land]
    coords = [[[[round(x, 6), round(y, 6)] for x, y in poly.exterior.coords]] + [[[round(x, 6), round(y, 6)] for x, y in hole.coords] for hole in poly.interiors]
              for poly in polys]
    view = {"type": "MultiPolygon", "coordinates": coords,
            "source": {"relation": ex["territory"]["relation"], "iso": ex["territory"]["iso"],
                       "files": [s["file"] for s in ex.get("sources", [])], "tolerance_deg": VIEW_TOL}}
    (OUT / f"{code}_view.json").write_text(json.dumps(view, separators=(",", ":")))
    print(f"{code}_view.json: {sum(len(r) for p in coords for r in p)} points", flush=True)


# ---------------------------------------------------------------- the five countries
# FAST: line name -> (class, design speed in km/h, only a top speed?, source).
# KIND: line name -> class, where the line's own tags would put it in another.
# SAME_LINE: a second name of one line -> the name it is drawn under.
# GENERIC: names a country's track carries that name no line (Malaysia's "KTM", the railway's
#   initials on 1,600 km of its track): such track is unnamed, and takes the name of its
#   route=railway relation (railway_relation_names), else of the line it joins.
# SERVICE_RAILWAY: networks of route=railway relations that are train services (left out, see clip).
# URBAN_TRAINS: route=train relations drawn as metro lines over the railway, as Korea's 수도권 전철
#   lines over KORAIL's (owner's decisions of 2026-10-19: KTM Komuter by line, the airport lines
#   with the city lines), matched on "network | route_master's name | route's name";
#   URBAN_TRAIN_KIND: their class, a metro line's unless given (Jakarta's KRL: "commuter").
# URBAN_SKIP: route relations of metro kinds that are not lines of the city (people movers inside
#   an airport, a line out of service), matched on "network | name | operator | ref".
# URBAN_SAME: a second name of one metro line -> the name it is drawn under.
# URBAN_CITY: (pattern on "network | name", city): a line listed under a city whatever its middle.
# BUILD_FAST: line being built -> (class, km/h, only a top speed?, source).
# STATION_CODE: what is taken off the front of a station's name.
SEA = {
    # Laos (output/sea-research/la.md). 414 km of the China–Laos railway are named
    # ທາງລົດໄຟ ລາວ-ຈີນ on the track (2026-10-18 extract), a few hundred metres
    # ທາງລົດໄຟ ລາວ-ຈີນ 磨万铁路, and the route=railway relation r10168930 ລົດໄຟລາວ-ຈີນ.
    "la": dict(
        name="老挝", elsewhere="老挝其他", cities=[],
        local_fallback_en=True,
        FAST={"ທາງລົດໄຟ ລາວ-ຈີນ": ("fast", 160, False,
              # 《铁道货运》2024年第42卷第6期, by the 万象运营管理中心 of 中国铁路昆明局集团: "中老铁路磨万段自磨丁口岸站至万象南站,
              # 全长422 km,是设计速度160 km/h的客货共线单线电气化标准轨距铁路"; Xinhua 2020-07-31 "设计时速160公里"
              "https://search.napstic.cn/literature/periodical/010tdhy202406004 ; https://www.xinhuanet.com/world/2020-07/31/c_1126306778.htm")},
        # The metre-gauge line over the Friendship Bridge to Thanaleng and Khamsavath is the end of
        # Thailand's Northeastern Line (r17458406, "Thanon Chira Junction – Khamsavath railway line"),
        # about 12 km in Laos: a branch here, whatever its usage=main says.
        KIND={"สายตะวันออกเฉียงเหนือ": "branch"},
        SAME_LINE={"ລົດໄຟລາວ-ຈີນ": "ທາງລົດໄຟ ລາວ-ຈີນ"},
    ),
    # Thailand (th.md), not run yet: SRT's four trunk lines main, the rest branch; the Airport
    # Rail Link and the Red Lines are urban lines by their route relations; the China–Thailand
    # high-speed railway is built, 250 marked as a top speed (e).
    "th": dict(name="泰国", elsewhere="泰国其他", cities=[("曼谷", 100.52, 13.75, 0.6)], local_fallback_en=True,
               FAST={},
               # SRT's four trunk lines, their shared stem from Bangkok to Ban Phachi and the bypasses
               # of their junctions are main lines; every other line is a branch (th.md, owner's
               # decisions of 2026-10-19), whatever usage=main says on most of the network.
               DEFAULT_KIND="branch",
               KIND={name: "main" for name in ("สายเหนือ", "สายตะวันออกเฉียงเหนือ", "สายตะวันออก", "สายใต้", "สายเหนือ/ตะวันออกเฉียงเหนือ",
                                               "สายเลี่ยงเมืองลพบุรี", "ทางคู่เลี่ยงเมืองชุมทางแก่งคอย", "เลี่ยงเมืองชุมทางบ้านภาชี")},
               NAME_PREFIX=re.compile(r"^ทางรถไฟ(?=สาย|เลี่ยง)"),        # "railway": ทางรถไฟสายใต้ is สายใต้, the Southern Line
               SAME_LINE={"สายเหนือ/ตะวันออกฉียงเหนือ": "สายเหนือ/ตะวันออกเฉียงเหนือ", "สายเหนือ-ตะวันออกเฉียงเหนือ": "สายเหนือ/ตะวันออกเฉียงเหนือ",
                          "สายเด่นชัย-เชียงราย-เชียงของ": "สายเด่นชัย–เชียงราย–เชียงของ",
                          "สายชุมทางทุ่งสง - กันตัง": "สายทางแยกกันตัง",                     # the Kantang branch: its relation and its track
                          "สายแม่กลอง ช่วงบ้านแหลม - แม่กลอง": "สายแม่กลอง", "สายแม่กลอง ช่วงวงเวียนใหญ่ - มหาชัย": "สายแม่กลอง",
                          "สายมหาชัย": "สายแม่กลอง",                                           # (the Maeklong Railway's Maha Chai section)
                          "สายอีสานใต้": "สายตะวันออกเฉียงเหนือ",                              # (Lower Isan: the Northeastern Line to Ubon)
                          # Cambodia's relation over the border bridge at Aranyaprathet; on this side, the Eastern Line's track
                          "ផ្លូវរថភ្លើងកម្ពុជាភាគខាងជើង": "สายตะวันออก",
                          "รถไฟความเร็วสายอีสาน": "รถไฟความเร็วสูง สายกรุงเทพฯ-นครราชสีมา",
                          "รถไฟฟ้าแอร์พอร์ต เรล ลิงก์": "รถไฟฟ้าเอราวัน"},                    # (the Airport Rail Link's track, by its two names)
               # Track OSM has as railway=rail on a line that is not open: Den Chai–Chiang Rai–Chiang Khong
               # (188 of its 323 km in the 2026-10-18 extract), to open in 2571 BE / 2028 (Bank of
               # Thailand, 2024-07-18, in th.md). It is drawn as a line being built.
               NOT_OPEN={"ทางรถไฟสายเด่นชัย–เชียงราย–เชียงของ", "รถไฟความเร็วสูง สายกรุงเทพฯ-นครราชสีมา"},     # (and 36 km of the high-speed line)
               # route=railway relations that name no running track: the high-speed line's (r17456762)
               # also holds 20 km of the SRT's unnamed metre-gauge track at Kaeng Khoi, which took its name
               NOT_NAMING={"รถไฟความเร็วสูง สายกรุงเทพฯ-นครราชสีมา", "รถไฟความเร็วสูงเชื่อม 3 สนามบิน"},
               # The Airport Rail Link and the SRT Red Lines (route=train) are Bangkok's metro lines;
               # the Gold Line is a people mover (Innovia APM 300, th.md), with the monorails; the
               # Pink Line's Muang Thong Thani branch is the Pink Line (owner's decisions).
               URBAN_TRAINS=re.compile(r"^(ARL|รถไฟฟ้าชานเมือง สายสีแดง) \|"),
               URBAN_SKIP=re.compile(r"ระบบขนส่งผู้โดยสารอัตโนมัติ|People Mov"),       # Suvarnabhumi's people mover, inside the airport
               URBAN_SAME={"สายเมืองทองธานี": "รถไฟฟ้ามหานคร สายสีชมพู"},
               URBAN_COLOUR={"รถไฟฟ้ามหานคร สายสีชมพู": "#E76589"},
               URBAN_LIGHT=re.compile(r"^รถไฟฟ้าสายสีทอง"),
               URBAN_SHORT={"รถไฟฟ้าสายสีทอง"},          # the Gold Line is 1.8 km: a line of the city, not a ride (as Nagoya's 0.8 km 上飯田線)
               BUILD_FAST={"รถไฟความเร็วสูง สายกรุงเทพฯ-นครราชสีมา": ("hs", 250, True,
                           # the project's site: "Top speed: 250 kilometers/hour" (a top speed: no design speed found, th.md)
                           "https://www.highspeedrail-thai-china.com/en/")},
               # stubs of high-speed lines not begun (th.md: the Three Airports line has not started;
               # the Northern and Southern lines are plans), at Krung Thep Aphiwat
               BUILD_SKIP={"รถไฟความเร็วสูงสายใต้", "รถไฟความเร็วสายเหนือ", "รถไฟความเร็วสูงเชื่อม 3 สนามบิน"}),
    # Malaysia (my.md; malaysia-singapore-brunei of 2026-10-18 clipped to relation 2108121).
    # The West Coast Line is main and neutral (owner: upgraded old line, as Britain's 125 mph
    # lines); the ECRL, 160 km/h by design, is being built and in the layer of lines being built.
    # KTM Komuter and the two KLIA lines are metro lines over the railway (URBAN_TRAINS), in their
    # OSM colours (the operators publish no colour values); the Skypark Link is out of service
    # since 2023-02-15 (my.md) and the KLIA Aerotrain is inside the airport: neither is drawn.
    "my": dict(name="马来西亚", elsewhere="马来西亚其他",
               cities=[("吉隆坡", 101.69, 3.14, 0.6), ("槟城", 100.33, 5.40, 0.3), ("新山", 103.76, 1.49, 0.3)],
               local_fallback_en=False, FAST={},
               KIND={"KTM Pasir Gudang branch": "branch"},
               # The SRT's relation of its Hat Yai–Padang Besar line reaches over the border to Padang
               # Besar station, which is in Malaysia: on this side that track is the West Coast Line's.
               # "ECRL (Kuantan Port Spurline)" is the ECRL's branch to Kuantan Port.
               SAME_LINE={"สายชุมทางหาดใหญ่–ปาดังเบซาร์": "KTM Laluan kereta api Pantai Barat", "ECRL": "East Coast Rail Link"},
               GENERIC={"KTM"}, GENERIC_EN={"KTM"},          # (and name:en "KTM" is no line's English name)
               SERVICE_RAILWAY=re.compile(r"^KTM (Intercity|Komuter)$"),
               URBAN_TRAINS=re.compile(r"^(KTM Komuter|ERL) \|"),
               URBAN_SKIP=re.compile(r"Aerotrain|Skypark"),
               URBAN_SAME={"Laluan Seremban": "Seremban Line"},
               # Komuter Utara (Butterworth–Ipoh, Butterworth–Padang Besar) is Penang's
               URBAN_CITY=[(re.compile(r"^KTM Komuter \| Butterworth"), "槟城")],
               BUILD_FAST={"East Coast Rail Link": ("fast", 160, False,
                           # NST 2026-09-18, the MRL project director: "10 per cent above the ECRL's 160km/h design speed"
                           "https://www.nst.com.my/amp/business/corporate/2026/09/1535452/phase-2-testing-track-ecrl-opening-mid-december-mrl-chief")},
               STATION_CODE=re.compile(r"^(?:(?:[A-Z]{1,3}\d{1,3}[A-Z]?|KA\d+)\s+)+(?=\S)")),      # (AG9 SP9 Hang Tuah)
    # Singapore (sg.md): metro and light rail, and the KTM track over the Causeway to Woodlands
    # (Malaysia's West Coast Line, cut at the border: Singapore's 1 km of it is drawn here). The
    # Changi Airport Skytrain is inside the airport and not drawn (owner's decision of 2026-10-19).
    "sg": dict(name="新加坡", elsewhere="新加坡其他", cities=[("新加坡", 103.82, 1.35, 0.4)],
               local_fallback_en=False, FAST={}, KIND={},
               # (the tracks of Woodlands Train Checkpoint carry what they are: Down Main Up, Down Loop Up, Siding)
               SAME_LINE={name: "KTM Laluan kereta api Pantai Barat" for name in ("KTM", "Down Main Up", "Down Loop Up", "Siding")},
               GENERIC_EN={"KTM"},
               URBAN_SKIP=re.compile(r"Skytrain|Changi Airport Group"),
               URBAN_SHORT={"Sentosa Express"}),          # 2.1 km (sg.md), drawn by the owner's decision of 2026-10-19
    # Indonesia (id.md), not run yet: Whoosh in the 350 band (chinadaily "最高设计时速350公里");
    # KRL commuter lines as a class of their own over the KAI lines.
    # Indonesia (id.md; indonesia of 2026-10-18, read without a node index, extract_osm.lean_railway).
    # Whoosh, the Jakarta–Bandung high-speed railway, in the 350 band by its design speed; KAI's
    # lines main or branch by usage. Jakarta's KRL lines and the airport trains are a class of
    # their own, 通勤铁路 (owner's decisions of 2026-10-19), by their route relations over the KAI
    # track; KAI Commuter's diesel "Commuter Line" services elsewhere in Java are not KRL and are
    # not drawn as lines. The Kalayang people mover inside Soekarno–Hatta airport is not drawn.
    "id": dict(name="印度尼西亚", elsewhere="印度尼西亚其他",
               cities=[("雅加达", 106.85, -6.21, 0.6), ("巨港", 104.76, -2.98, 0.3), ("日惹", 110.37, -7.80, 0.35),
                       ("梭罗", 110.82, -7.57, 0.35), ("棉兰", 98.67, 3.59, 0.6), ("巴东", 100.35, -0.95, 0.5)],
               local_fallback_en=False,
               FAST={"Jalur Kereta Cepat Jakarta–Bandung": ("hs", 350, False,
                     # China Daily 2022-01-14 "最高设计时速350公里"; China News Service 2023-06-23 (joint testing "达到设计时速350公里")
                     "https://cn.chinadaily.com.cn/a/202201/14/WS61e13b96a3107be497a0245d.html ; https://www.chinanews.com.cn/shipin/cns-d/2023/06-23/news962701.shtml")},
               KIND={}, SAME_LINE={},
               NAME_NORMAL=lambda name: re.sub(r"(?<=\w)-(?=\w)", "–", re.sub(r"^Jalur (?:KA|kereta api)\b", "Jalur Kereta Api", name)),
               URBAN_TRAINS=re.compile(r"^KAI (?:Commuter|Bandara) \| (?:[^|]*\| )?(?:Lin |Bogor Line|Tanjung Priuk Line|Kereta Api Bandara)|Kereta Api BIAS|Minangkabau Ekspres"),
               URBAN_TRAIN_KIND="commuter",
               URBAN_SKIP=re.compile(r"Kalayang|Aeromovel"),          # (Aeromovel: the people mover of the Taman Mini park)
               URBAN_NETWORK={"Kereta Api BIAS": "KAI"},                # (one of its six routes has no network)
               URBAN_SAME={"Bogor Line": "Lin Bogor", "Tanjung Priuk Line": "Lin Tanjung Priuk", "Yogyakarta Line": "Lin Yogyakarta",
                           "North-South Line": "MRT North-South Line"},
               URBAN_CITY=[(re.compile(r"Lin Yogyakarta|Bandara YIA"), "日惹"), (re.compile(r"BIAS"), "梭罗"),
                           (re.compile(r"Srilelawangsa"), "棉兰"), (re.compile(r"Minangkabau"), "巴东")],
               STATION_CODE=re.compile(r"^Stasiun\s+")),
}
# A tunnel or a bridge named for itself is part of the line on either side of it: in English and
# Chinese the word comes last, in Thai, Lao, Malay and Indonesian first (Terowong Serendah 2).
STRUCTURE = re.compile(r"(Tunnel|Bridge|Viaduct|อุโมงค์|สะพาน|ຂົວ|ອຸໂມງ|Terowongan|Jembatan|隧道|大桥|特大桥)$"
                       r"|^(?:Terowong|Terowongan|Jambatan|Jembatan)\b|^(?:อุโมงค์|สะพาน)", re.I)
DIRECTION = re.compile(r"\s*[(（][^()（）]*(?:→|->|-->|=>|↔|<->|↺|↻|bound\b|Loop)[^()（）]*[)）]?\s*$", re.I)


def urban_line(conf):
    """(network, line name, colour) of a metro route relation: the route_master's name, else the
    route's without its direction; None for a route that is not a line of the city."""
    from country import line_of_route
    skip, same = conf.get("URBAN_SKIP"), conf.get("URBAN_SAME", {})

    def line_of(tags, master):
        network, name, colour = line_of_route(tags, master)
        if not master.get("name"):
            name = DIRECTION.sub("", name).strip() or name
        name = same.get(name, name)
        colour = conf.get("URBAN_COLOUR", {}).get(name, colour)
        network = conf.get("URBAN_NETWORK", {}).get(name, network)
        text = " | ".join(filter(None, (network, name, tags.get("operator") or master.get("operator"), tags.get("ref"), tags.get("name"))))
        return (network, "", colour) if skip and skip.search(text) else (network, name, colour)
    return line_of


def light_routes(conf, relations):
    """Route relations of metro lines that are light rail whatever their route= says (URBAN_LIGHT:
    Bangkok's Gold Line, an automated people mover, is route=subway in OSM): taken as monorail."""
    light = conf.get("URBAN_LIGHT")
    if not light:
        return relations
    return [(rid, dict(t, route="monorail") if t.get("type") == "route" and t.get("route") == "subway" and light.search(t.get("name") or "") else t, m)
            for rid, t, m in relations]


def construction(code, conf, plain_name):
    """The layer of lines being built, as process_jp.being_built draws it (track being built under
    one name is one line, drawn once, dashed), with three things of South-East Asia's own:
    - construction track with no name of its own, or a structure's (Terowong Serendah 2, 9.9 km
      of the ECRL), takes the name of the one route=railway relation it is in, as running track does;
    - a line of under 2 km is left out, unless it reaches the border: the Singapore end of the RTS
      Link is 1.5 km, the rest of it Malaysia's;
    - a fast line has its design speed and source (BUILD_FAST)."""
    from process_jp import CURVE, TOL, geometry, km, rounded, runs_of
    from single_track import one_track, stitch
    fast = conf.get("BUILD_FAST", {})

    def built(cfg, ways, namer):
        of_relation = defaultdict(set)
        for rid, tags, members in RELATIONS.get(code, []):
            if tags.get("type") == "route" and tags.get("route") == "railway" and plain_name(tags.get("name")):
                for kind, ref in members:
                    if kind == "w":
                        of_relation[ref].add(plain_name(tags.get("name")))
        edge = land_of(TERRITORY[code]).boundary
        building = defaultdict(list)
        for wid, (t, co) in ways.items():
            if t.get("railway") == "construction" and (t.get("construction") or t.get("construction:railway")) in ("rail", "light_rail", "tram", "subway", None):
                name = cfg.build_name(plain_name(t.get("name")))
                if not name and len(of_relation.get(wid, ())) == 1:
                    name = cfg.build_name(next(iter(of_relation[wid])))
                if name and name not in conf.get("BUILD_SKIP", ()):
                    building[name].append(wid)
        feats = []
        for name, wids in sorted(building.items()):
            drawn = stitch(one_track(runs_of([ways[w][1] for w in wids])))
            simp = rounded(drawn, TOL["rail"], CURVE["rail"], places=5)
            at_border = any(edge.distance(Point(co[k])) < 1e-6 for w in wids for co in [ways[w][1]] for k in (0, -1))
            if not simp or sum(km(co) for co in simp) < 2 and not at_border:
                continue
            props = {"c": "build", "n": name, "g": cfg.code}
            if name in fast:
                jk, speed, estimate, source = fast[name]
                props.update({"h": 1, "jk": jk, "d": speed, "ref": source, **({"e": 1} if estimate else {})})
            for w in wids:
                namer.add(name, ways[w][0], km(ways[w][1]))
            namer.line(props)
            feats.append({"type": "Feature", "properties": props, "geometry": geometry(simp)})
        return feats
    return built


def configure(code):
    conf = SEA[code]
    generic = conf.get("GENERIC", set())

    prefix = conf.get("NAME_PREFIX")

    def plain_name(name):
        name = without_han(re.sub(r"\s*[（(].*?[)）]", "", name or ""))
        if prefix:
            name = prefix.sub("", name)
        if conf.get("NAME_NORMAL"):
            name = conf["NAME_NORMAL"](name)
        name = re.sub(r"\s+", " ", re.split(r"[;；]", name)[0]).strip()
        name = re.split(r"\s+/\s+", name)[0]                 # (the RTS Link: "Johor Bahru–Singapore Rapid Transit System / Sistem ...")
        name = conf["SAME_LINE"].get(name, name)
        return "" if STRUCTURE.search(name) or name in generic else name

    def kind_of(name, tags_km):
        if name in conf["FAST"]:
            return conf["FAST"][name][0]
        if name in conf["KIND"]:
            return conf["KIND"][name]
        total = sum(tags_km.values()) or 1
        share = lambda test: sum(v for k, v in tags_km.items() if test(dict(k))) / total
        if conf.get("DEFAULT_KIND"):
            return conf["DEFAULT_KIND"]
        return "main" if share(lambda t: t.get("usage") == "main") >= 0.5 else "branch"

    def speed_of(name, jk, tags_km):
        fast = conf["FAST"].get(name)
        return (fast[1], fast[2], fast[3]) if fast else None

    trains = conf.get("URBAN_TRAINS")
    by_city = conf.get("URBAN_CITY", [])
    return Country(
        **LIKE_EUROPE,                        # drawn as Europe is (scripts/country.py); Singapore's three LRT lines share one grey and one network: each is a line
        rail_capsules=True,                   # Bangkok's Red Lines, KTM Komuter and Jakarta's KRL are drawn as city lines over the railway
        urban_service_way=platform_siding,    # the Dark Red Line's platform tracks at Don Mueang are tagged service=siding
        code=code, plain_name=plain_name, kind_of=kind_of, speed_of=speed_of,
        cities=conf["cities"], elsewhere=conf["elsewhere"],
        fast_kinds=("hs", "fast"), main_kinds=("main",),
        rail=frozenset({"rail"}), urban=frozenset({"subway", "light_rail", "monorail", "tram"}),
        skip_usage=frozenset({"industrial", "military", "test", "freight", "tourism"}),
        skip_stations=("funicular", "miniature"),
        tag_keys=("railway", "usage", "gauge"),
        railway_relation_names=True,          # unnamed track may take its unique route=railway name (the Lao end of the Northeastern Line)
        keep_unnamed_rail=True,               # track that no name reaches is drawn without one (the Vientiane South–Thanaleng freight spur)
        prepare=lambda ex: clip(ex, code, JOINS),
        urban_line_of=urban_line(conf),
        urban_trains=(lambda tags, master: bool(trains.search(" | ".join([tags.get("network") or master.get("network") or "",
                                                                           master.get("name") or "", tags.get("name") or ""])))) if trains else None,
        urban_train_kind=conf.get("URBAN_TRAIN_KIND", "subway"),
        # no railway line here has a line colour of its own: the colours of KAI's and KTM's route
        # relations are those of named trains and of the commuter lines drawn over the railway
        many_colours=None,
        urban_city_of=(lambda network, name, mid, city: next((c for pattern, c in by_city if pattern.search(f"{network} | {name}")), city)) if by_city else None,
        construction_of=construction(code, conf, plain_name),
        urban_minimum=(lambda network, name, rids, default: 1.0 if name in conf["URBAN_SHORT"] else default) if conf.get("URBAN_SHORT") else None,
        build_fast=lambda name: name in conf.get("BUILD_FAST", {}),
    )


JOINS = []
RELATIONS, TERRITORY = {}, {}       # by country, as clip() leaves them: for the layer of lines being built

if __name__ == "__main__":
    codes = sys.argv[1:]
    if not codes or any(c not in SEA for c in codes):
        sys.exit("usage: python3 scripts/process_sea.py la|th|my|sg|id ...")
    import pickle
    for code in codes:
        JOINS.clear()
        cfg = configure(code)
        run(cfg)
        met = meet_neighbours(code, TERRITORY[code])
        with (OUT / "raw" / f"extract_{code}.pkl").open("rb") as stream:     # written locally by scripts/extract_osm.py
            write_view(pickle.load(stream), code)
        audit = OUT / "audit"
        audit.mkdir(exist_ok=True)
        (audit / f"{code}_border_joins.json").write_text(json.dumps(JOINS + [{"drawn_on": row} for row in met], ensure_ascii=False, indent=1) + "\n")
