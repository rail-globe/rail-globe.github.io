"""The names on the yards and depots layer: which named thing in OSM labels which depot, for every
country (scripts/process_osm.py for China, scripts/yards.py for the others).

A depot on the map is a fan of yard track: four or more tracks side by side, a kilometre and a
half of them or more. Its name can be on several kinds of object, and the object is seldom on
the tracks themselves:
- railway ground, landuse=railway, as an area or as a multipolygon relation (台北捷運土城機廠);
- other ground that holds the fan: landuse=industrial (广清城际龙塘动车运用所), depot,
  construction, commercial, garages;
- an object tagged for what it is: railway=yard, depot, workshop, engine_shed, roundhouse;
- nothing in OSM at all: then data/depot_names.json, a table with a source for every row.

The rules, each the answer to a fault that was on the map:
- A name has to name a depot, a yard or a works, whatever the object is tagged as: a shed, a
  building site or an office inside a depot is not the depot (联合检修库, 施工廠區一區, 仕佳興業辦公室).
- Ground that is not railway ground has to hold the tracks: a third of a fan inside its outline.
  Then any depot word in its name counts. Elsewhere only the words that can mean nothing else
  count, since a bare 停车场, 工場 or Works on such ground is a car park or a factory.
- The label stands on the yard track inside the area, not at the middle of the area, which for a
  large one is hundreds of metres from any track; a point object has to be within REACH of yard
  track. A metro depot whose own tracks are not drawn as yard track (they are not in OSM, or not
  tagged as yard: 济南's 唐冶北车辆段, 西灣河車廠) is within REACH of its line's drawn track instead,
  and keeps its name; a railway's siding on undrawn spur track does not.
- One depot, one label. A named area that holds yard track is a depot's own ground, and its name
  stands once on its tracks: an area mostly inside the ground of another, next to that one's
  label, is the same depot, and so is a point object on a ground or within REACH of a ground's
  label. Otherwise one point object names a fan: a yard or depot object first, then the rest. A
  large fan can hold several depots (上海南: 梅陇基地, 上海南车辆段 and 石龙路停车场 are one fan of
  track; 昆明机务段 lies inside the ground of 昆明东编组站), and each keeps its name.
- A name that says only what the thing is (Railway Yard, TMD, 上行调车场) names a fan only where
  nothing more particular does.
- Whether a depot has a name at all is asked of the fans within 250 m of each other together:
  a depot's sheds and its stabling yard.
- A name that OSM carries wins over the table, which is only for what OSM lacks.
"""
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPoint, Polygon
from shapely.ops import polygonize, unary_union

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "data" / "depot_names.json"
YARD_KINDS = ("yard", "depot", "workshop", "engine_shed", "roundhouse")
SHEDS = ("railway=workshop", "railway=engine_shed", "railway=roundhouse")     # a building, not the depot's ground
AREA_USES = ("railway", "industrial", "depot", "construction", "commercial", "garages")
# The first of these an object has is its name. China's objects are named in Chinese first: in Hong
# Kong, Macao and Taiwan the name tag is often both languages at once (屯門車廠 Tuen Mun Depot).
NAME_KEYS = {"cn": ("name:zh", "name", "name:en", "official_name", "alt_name")}
NAME_KEYS_ABROAD = ("name", "name:zh", "name:en", "official_name", "alt_name")
METRO_TRACK = {"subway", "light_rail", "tram", "monorail", "maglev"}
LAT0 = {"cn": 35.0, "jp": 36.0, "kr": 36.5, "uk": 54.0}      # where a cell of the grid is 50 m across
R = 6378137.0
CELL_M = 50.0         # the grid the track is counted on
TRACKS = 3.5          # a 150 m window with this many tracks side by side is in a fan
FAN_KM = 1.5          # a fan has at least this much track
SAME_DEPOT_M = 250    # fans this close to each other are one depot
REACH = 300           # metres: a label is within this of yard track, and of the fan it names
REVIEW_KM = 5.0       # unnamed railway depots this large are listed for a look (most are freight yards)
STATION_YARD_M = 150  # a fan this close to a station is the station's yard, and not listed for a look
HOLDS = 0.3           # the share of a fan inside an area's outline from which the area is the depot's ground
TABLE_REACH = 150     # metres: a row of the table is this close to the fan it names

# Words that name a depot, a yard or a works on railway ground, per country.
MORE = {
    "cn": re.compile(r"车辆段|車輛段|车辆基地|車輛基地|停车场|停車場|动车所|動車所|动车段|动车运用|動車|机务|機務|车库|車庫|检修|檢修|整备|整備|车厂|車廠|机厂|機廠"
                     r"|存车|存車|编组|編組|折返段|折返所|客技|客整|运用所|运用段|运用车间|车辆厂|車輛廠|机车厂|机辆|機輛|综合基地|綜合基地|维修基地|維修基地|维修中心|維修中心"
                     r"|车辆维修|車輛維修|定修段|调车场|調車場|基地$|综合车场|綜合車場|车场$|車場$|维保中心|維保中心|[Dd]epot|\bYard|Workshop|Maintenance|Stabling"),
    "jp": re.compile(r"車両基地|車両センター|総合車両|車両所|車両区|車両管理|車両工場|車両検修|車両支所|車両事業|運転所|運転区|運輸区|運輸所|運転センター|運輸センター|機関区|機関庫|電車区|気動車区"
                     r"|検車|険車|検修|車庫|電車庫|操車場|貨物ターミナル|貨物駅|電留線|留置線|総合基地|保守基地|基地$|工場$|[Dd]epot|\bYard"),
    "kr": re.compile(r"차량기지|차량사업소|차량정비|차량분소|차량관리|차량사무소|차량센터|정비단|정비창|기지|조차장|기관차|검수|주박|화물|컨테이너|[Dd]epot|\bYard"),
    "uk": re.compile(r"Depot|Sidings?\b|Yard\b|Works\b|TMD|T&RSMD|\bMPD\b|Traincare|Train Care|Maintenance|Carriage|Stabling|Freight ?liner|Terminal\b|\bShed\b|Roundhouse|Wagon|Loco", re.I),
}
_CN_RAIL = r"(?:地铁|地鐵|轨道交通|軌道交通|号线|號線|[线線]|轻轨|輕軌|有轨电车|有軌電車|捷運|云轨|云巴|磁浮|磁悬浮|城际|城軌|城轨|市域|铁路|鐵路|高铁|高鐵|APM|单轨|單軌)"
# Words that name a railway depot even on ground whose tags say nothing about railways.
STRICT = {
    "cn": re.compile(r"车辆段|車輛段|车辆基地|車輛基地|动车所|動車所|动车段|動車段|动车运用所|動車運用所|动车(组)?存车场|机务段|機務段|折返段|客技站|客车技术整备所|客整所"
                     r"|机车车辆厂|機廠$|機廠[（(]|車廠|车辆运用段|机辆段|定修段|综合维修基地|綜合維修基地|综合基地$|车辆维修基地|車輛維修基地"
                     r"|" + _CN_RAIL + r".{0,14}(?:停车场|停車場|车场|車場|存车场|存車場|车库|車庫|维修基地|維修基地|维修中心|維修中心|基地)$"
                     r"|(?:Metro|MTR|Railway|Rail|Tram|LRT|Light Rail|Subway).{0,20}Depot|Depot.{0,20}(?:Metro|MTR|Railway|Line)"),
    "jp": re.compile(r"車両基地|車両センター|総合車両所|総合車両センター|車両所|車両区|車両管理所|車両工場|車両検修場|車両支所|運転所|運転区|運輸区|機関区|電車区|気動車区|客車区|貨車区"
                     r"|検車区|険車区|検車場|検車支区|検修場|検修区|検修庫|電車庫|電留線|留置線|操車場|貨物ターミナル|総合基地|新幹線.{0,8}基地|保線基地|保守基地"
                     r"|(?:電車|鉄道|電鉄|線|地下鉄|モノレール|市電|都電|軌道).{0,8}車庫"),
    "kr": re.compile(r"차량기지|차량사업소|차량정비단|철도차량정비|차량분소|차량관리단|차량사무소|정비창|주박기지|조차장|기관차사업소|기관차승무|검수고|검수기지|보수기지|차량검수|차량센터"
                     r"|(?:경전철|도시철도|지하철|전철|철도|호선|[가-힣]선).{0,8}기지"),
    "uk": re.compile(r"\bTMD\b|T&RSMD|TRSMD|Traincare|Train Care|Traction Maintenance|Train Maintenance|Rolling Stock|Carriage (?:Sidings|Works|Shed|Depot)"
                     r"|Locomotive (?:Works|Depot|Shed)|Loco Shed|Engine Shed|Wagon Works|Railway Works|Rail Depot|Railway Depot|Train Depot|Tram Depot|Tramway Depot|Metro Depot"
                     r"|Underground Depot|Light Maintenance Depot|Stabling|\bSidings\b|Marshalling Yard|Freightliner|Rail(?:way)? (?:Freight )?Terminal"
                     r"|(?:Line|Railway|Underground|Metrolink|Tramlink|Supertram|DLR|Metro|Rail|Train|Tram|Subway|Elizabeth|Overground|Thameslink|Eurostar|LNER|GWR|ScotRail|Northern)\b.{0,25}\bDepot"
                     r"|\bDepot\b.{0,25}(?:Line|Railway|Underground|Metrolink|Tramlink|DLR|Metro\b)", re.I),
}
# Never a depot, whatever else the name says: buildings, building sites, offices, car parks, bus garages, streets.
NEVER = {
    "cn": re.compile(r"施工|工地|项目部|項目部|铺轨|鋪軌|长轨|焊轨|制梁|梁场|预制|預鑄|预铸|办公|辦公|公司$|宿舍|公寓|食堂|公交|巴士|九巴|城巴|新巴|龍運|嶼巴|客[運运](?!整备|整備|车场|車場)|公車|貨櫃|拖車"
                     r"|物流|培训|培訓|职教|職教|P\+R|换乘|轉乘|公共停车|社会停车|地下停车|立體停車|立体停车|机动车|非机动|自行车|收费|收費"
                     r"|派出所|加油|消防|变电|變電|污水|垃圾|洗车|洗車|驾校|駕訓|检测站|检查站|收费站|服务区|機車停|机车停|停車場[（(]|YouBike|共享|出口|入口"
                     r"|里$|村$|楼$|樓$|(?<!扇形[车車])(?<!分)[库庫]\d*$|棚$|门$|門$|(?<!编组)(?<!編組)(?<!客技)站$|路$|街$|[东西南北]区$|[一二三四]区$|[一二三四]區$|用地$|规划|規劃|预留|預留|旧址|舊址|遗址|遺址"),
    "jp": re.compile(r"バス|自動車|タクシー|トラック|駐車場|駐輪|工事|事務所|営業所|寮$|社宅|消防|清掃|自衛隊|倉庫|物流|団地|公園|小学校|中学校|高校|病院|跡$|跡地|入口$|前$|の碑|碑$|記念|移転予定|予定地|踏切|交差点|社員|詰所|変電"),
    "kr": re.compile(r"버스|자동차|택시|주차(?!량)|공사$|사무소$|아파트|물류|소방|학교|병원|공원|마을|주유|차고지|공영|운송|택배|냉면|체육관|채육관|미군"),
    "uk": re.compile(r"\bBus\b|\bCoach\b|Lorry|Car Park|Parking|Council|Highways|Builders|Self Storage|\bFire\b|Ambulance|Police|School"
                     r"|Tesco|Asda|Sainsbury|Morrisons|Aldi|Lidl|Retail|Shopping|Business Park|Industrial Estate|Trading Estate"
                     r"|\bCourt$|\bClose$|\bHouse$|\bCottages?$|\bRoad$|\bLane$|\bStreet$|\bWay$|\bMotor\b|Tyre|Garage|\bVent\b|\bShaft\b|\(disused\)|\(former\)|\bformer\b|\bsite of\b", re.I),
}
# A depot is named after the place it is at or the company that runs it, and the place can be a
# park, a hospital or a steelworks (南京地铁二桥公园车辆段, 阪急電鉄株式会社 正雀工場, Barton Mill
# Carriage Servicing Depot, Wolverhampton Steel Terminal); a wagon depot is a 货车车辆段. Such words
# bar a name only where it does not end as a railway depot or yard does, or name a railway's own
# depot (STRICT: 坪山云巴中心公园停车场). A bare 停车场 is not among those endings: a park's is a car park.
PLACE_WORD = {
    "cn": re.compile(r"小区|社區|花园|花園|酒店|宾馆|学校|小学|中学|医院|市场|市場|广场|廣場|商场|公园|公園|汽车|汽車|货车|貨車"),
    "jp": re.compile(r"株式会社|\(株\)|（株）|㈱|有限会社"),
    "uk": re.compile(r"Royal Mail|Post Office|Recycling|Waste|Scrap|Timber|\bWater\b|Sewage|Gas ?works|\bBrick\b|\bSteel\b|Cement|Quarry|Brewery|Dairy|\bMill\b|\bFarm\b", re.I),
}
DEPOT_END = {
    "cn": re.compile(r"(车辆段|車輛段|车辆基地|車輛基地|动车所|動車所|动车段|動車段|运用所|機務段|机务段|折返段|車廠|车厂|機廠|机厂)$"),
    "jp": re.compile(r"(車両基地|車両センター|車両所|車両区|車両工場|工場|検車区|検車場|検修場|車庫|運転所|運転区|総合基地)$"),
    "uk": re.compile(r"(Depot|TMD|Sidings?|Yard|Terminal)$", re.I),
}
# A railway's own depots, not a metro's: they keep their label only by drawn yard track (a metro
# line drawn past 昆明北折返段 does not make it a metro depot).
RAILWAY_ONLY = {
    "cn": re.compile(r"折返|机务|機務|动车|動車|客技|客整|编组|編組|调车|調車|货|貨|工务|工務|电务|電務|供电|供電|车务|車務|机车|機車|铁路局|鐵路局|国铁|國鐵|集团|集團"),
    "jp": re.compile(r"JR|貨物|新幹線|機関区|機関庫"),
    "kr": re.compile(r"고속철도|화물|기관차|조차장|철도차량정비단"),
    "uk": re.compile(r"Freight|Freightliner|Network Rail|Carriage|Wagon|Loco|Sidings|TMD|Traincare|Train Care|Yard", re.I),
}
# A name that says only what the thing is (Railway Yard, TMD, Engine Shed, 上行调车场, SL第2検修庫)
# names no depot in particular. It labels a fan only where nothing more particular does.
GENERIC = {
    "cn": re.compile(r"车辆段|車輛段|车辆基地|車輛基地|停车场|停車場|动车运用所|動車運用所|动车所|動車所|动车段|動車段|运用所|運用所|机务段|機務段|折返段|检修库|整备场|整備場|整备所"
                     r"|车库|車庫|车厂|車廠|机厂|機廠|存车场|存車場|编组场|編組場|调车场|調車場|到达场|到发场|到發場|出发场|编发场|驼峰|货场|车场|車場|基地|综合|綜合"
                     r"|上行|下行|高速|普速|存车|存車|整备|整備|机务|機務|客整|到达|出发|到发|到發|编发|分解|调车|編組|编组|驼峰|运转|交接|装卸|[所段上下东西南北中場场号號第]|[IVXⅠⅡⅢⅣⅤⅥⅦⅧ]+|[一二三四五六七八九十]|[0-9]+|[()（）\-\s]|Rail(?:way)?|Depot|[Yy]ard"),
    "jp": re.compile(r"車両基地|車両センター|総合車両所|車両所|車両区|検車区|検車場|検修場|検修庫|電車庫|車庫|運転所|運転区|機関区|操車場|貨物ターミナル|貨物駅|留置線|電留線|総合基地|保守基地|工場|基地"
                     r"|上り|下り|SL|第|号|[0-9０-９]+|[一二三四五六七八九十]|[東西南北・\s]"),
    "kr": re.compile(r"차량기지|차량사업소|차량정비단|차량분소|차량관리단|차량사무소|기지사업소|기지|정비단|정비창|조차장|검수고|주박|화물|[0-9]+|\s"),
    "uk": re.compile(r"\b(?:the|and|of|up|down|north|south|east|west|new|old|main|rail(?:way)?s?|train|traction|rolling|stock|maintenance|light|heavy|service|servicing|locomotive|loco|engine"
                     r"|diesel|electric|emu|dmu|hst|carriage|wagon|freight(?:liner)?|stabling|sidings?|yard|depot|works|workshops?|shed|tmd|t&rsmd|trsmd|lmd|mpd|traincare|care|centre|center"
                     r"|terminal|goods|marshalling|exchange|reception|loop|c&w)\b|[&()/'’.,\-\s]", re.I),
}


def not_a_depot(g, name):
    """Is this the name of something that is never a depot?"""
    if NEVER[g].search(name):
        return True
    return bool(g in PLACE_WORD and PLACE_WORD[g].search(name) and not DEPOT_END[g].search(name) and not STRICT[g].search(name))


def generic(g, name):
    """Does the name say only what the thing is, and not which one?"""
    return not GENERIC[g].sub("", name).strip()


def form_of(tags):
    """What kind of thing a named object is, as far as a depot's name goes: 'railway=depot',
    'landuse=railway', 'landuse=industrial', ... or None for anything else."""
    if tags.get("railway") in YARD_KINDS:
        return "railway=" + tags["railway"]
    use = tags.get("landuse")
    if use == "railway":
        return "landuse=railway"
    if use == "industrial" or "industrial" in tags:
        return "landuse=industrial"
    return "landuse=" + use if use in AREA_USES else None


def name_of(tags, form, g):
    """(name, the tag it is read from) of an object. Railway ground with no name at all is known by
    its operator where that is given (the operator of a depot's ground is often written as the depot)."""
    for key in NAME_KEYS.get(g, NAME_KEYS_ABROAD):
        if tags.get(key):
            return re.sub(r"\s+", " ", tags[key]).strip(), key
    if form in ("landuse=railway",) + tuple("railway=" + k for k in YARD_KINDS) and tags.get("operator"):
        return re.sub(r"\s+", " ", tags["operator"]).strip(), "operator"
    return "", ""


def worth_keeping(g, name, form, key="name"):
    """At extraction: is this named object worth carrying to the label step? Railway ground and
    yard objects always (the label step tests them), other ground only with a depot word in its
    name, and ground known by its operator only where that names a depot."""
    if not name:
        return False
    if form.startswith("landuse=") and form != "landuse=railway" or key == "operator":
        return bool(MORE[g].search(name)) and not not_a_depot(g, name)
    return True


def names_a_depot(g, name, form, share=0.0):
    """Does this name, on an object of this kind, name a depot, a yard or a works? share: how
    much of a fan of yard track lies inside the object's outline."""
    if not name or not_a_depot(g, name):
        return False
    if form in ("railway=yard", "railway=depot"):
        return True                                     # tagged as a yard or a depot itself
    if form in SHEDS:
        return bool(MORE[g].search(name))               # a shed is named for the depot, or for a company, or for what it holds
    if form == "landuse=railway":
        return bool(MORE[g].search(name))
    return bool(share >= HOLDS and MORE[g].search(name)) or bool(STRICT[g].search(name))


def mercator(lon, lat):
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    return R * np.radians(lon), R * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def lonlat(x, y):
    return np.degrees(np.asarray(x) / R), np.degrees(2 * np.arctan(np.exp(np.asarray(y) / R)) - np.pi / 2)


def polygon_of(rings):
    """The area a way's or a multipolygon's outline encloses, or None."""
    try:
        if len(rings) == 1 and len(rings[0]) >= 4:
            p = Polygon(rings[0])
        else:
            lines = [LineString(r) for r in rings if len(r) > 1]
            polys = list(polygonize(unary_union(lines)))
            p = unary_union(polys) if polys else MultiPoint([pt for r in rings for pt in r]).convex_hull
        if not p.is_valid:
            p = p.buffer(0)
        return p if not p.is_empty and p.area > 0 else None
    except Exception:
        return None


class Fans:
    """The fans of a country's yard track, found on a grid of 50 m cells.

    lines: the yard track as drawn, coordinate lists. A cell is in a fan when the 150 m window
    round it holds TRACKS tracks or more side by side; cells of fans within two cells of each
    other are one fan; a fan has FAN_KM of track or more, counted with the ring of cells round
    it. Fans within SAME_DEPOT_M of each other are one depot (self.depot: fan -> depot)."""

    def __init__(self, lines, g):
        self.cell = CELL_M / math.cos(math.radians(LAT0[g]))        # Mercator metres
        xs, ys, ws = [], [], []
        for co in lines:
            co = np.asarray(co, float)
            if len(co) < 2:
                continue
            x, y = mercator(co[:, 0], co[:, 1])
            dx, dy = np.diff(x), np.diff(y)
            real = np.hypot(dx, dy) * np.cos(np.radians((co[:-1, 1] + co[1:, 1]) / 2))
            k = np.maximum(1, np.ceil(real / 10.0)).astype(int)     # a sample every 10 m
            seg = np.repeat(np.arange(len(k)), k)
            frac = (np.arange(k.sum()) - (np.cumsum(k) - k)[seg] + 0.5) / k[seg]
            xs.append(x[:-1][seg] + dx[seg] * frac)
            ys.append(y[:-1][seg] + dy[seg] * frac)
            ws.append((real / k)[seg])
        xs, ys, ws = (np.concatenate(v) if v else np.zeros(0) for v in (xs, ys, ws))
        ix, iy = np.floor(xs / self.cell).astype(np.int64), np.floor(ys / self.cell).astype(np.int64)
        cells, inv = np.unique(np.c_[ix, iy], axis=0, return_inverse=True) if len(xs) else (np.zeros((0, 2), np.int64), np.zeros(0, np.int64))
        inv = inv.ravel()
        metres = np.bincount(inv, weights=ws, minlength=len(cells))
        # where the track of a cell lies: the middle of its samples, which is on or between its tracks
        tx = np.bincount(inv, weights=ws * xs, minlength=len(cells)) / np.maximum(metres, 1e-9)
        ty = np.bincount(inv, weights=ws * ys, minlength=len(cells)) / np.maximum(metres, 1e-9)
        self.track = {(int(a), int(b)): (float(m), float(x), float(y)) for (a, b), m, x, y in zip(cells, metres, tx, ty)}
        _, lat = lonlat((cells[:, 0] + 0.5) * self.cell, (cells[:, 1] + 0.5) * self.cell) if len(cells) else (0, np.zeros(0))
        side = self.cell * np.cos(np.radians(lat))                  # a cell's side on the ground
        dense = set()
        for (a, b), s in zip(cells, side):
            a, b = int(a), int(b)
            window = sum(self.track.get((a + i, b + j), (0.0,))[0] for i in (-1, 0, 1) for j in (-1, 0, 1))
            if window / (3 * s) >= TRACKS:
                dense.add((a, b))
        # dense cells within two cells of each other are one fan
        fan, groups = {}, []
        for start in sorted(dense):
            if start in fan:
                continue
            fan[start], todo, mine = len(groups), [start], [start]
            while todo:
                a, b = todo.pop()
                for i in range(-2, 3):
                    for j in range(-2, 3):
                        c = (a + i, b + j)
                        if c in dense and c not in fan:
                            fan[c] = len(groups)
                            todo.append(c)
                            mine.append(c)
            groups.append(mine)
        # a fan's track: its cells and the ring round them, each cell counted for one fan
        foot = dict(fan)
        for (a, b), f in sorted(fan.items()):
            for i in (-1, 0, 1):
                for j in (-1, 0, 1):
                    foot.setdefault((a + i, b + j), f)
        km, sx, sy = Counter(), Counter(), Counter()
        for c, f in foot.items():
            if c in self.track:
                m, x, y = self.track[c]
                km[f] += m / 1000
                sx[f] += m * x
                sy[f] += m * y
        keep = [f for f in range(len(groups)) if km[f] >= FAN_KM]
        self.cells = {f: groups[f] for f in keep}                   # fan -> its dense cells
        self.km = {f: km[f] for f in keep}
        self.centre = {f: tuple(float(v) for v in lonlat(sx[f] / (km[f] * 1000), sy[f] / (km[f] * 1000))) for f in keep}
        self.fan = {c: f for f in keep for c in groups[f]}          # dense cell -> fan
        self.foot = {c: f for c, f in foot.items() if f in self.cells}
        # fans within SAME_DEPOT_M of each other are one depot
        depot = {f: f for f in keep}

        def root(f):
            while depot[f] != f:
                depot[f] = depot[depot[f]]
                f = depot[f]
            return f
        span = int(math.ceil(SAME_DEPOT_M / CELL_M))
        for (a, b), f in sorted(self.fan.items()):
            for i in range(-span, span + 1):
                for j in range(-span, span + 1):
                    other = self.fan.get((a + i, b + j))
                    if other is not None and root(other) != root(f) and math.hypot(i, j) * CELL_M <= SAME_DEPOT_M:
                        depot[max(root(other), root(f))] = min(root(other), root(f))
        self.depot = {f: root(f) for f in keep}

    def _cell(self, lon, lat):
        x, y = mercator(lon, lat)
        return float(x), float(y), int(math.floor(float(x) / self.cell)), int(math.floor(float(y) / self.cell))

    def to_track(self, lon, lat, reach=REACH):
        """Metres from a point to the nearest yard track within reach, or None."""
        x, y, a, b = self._cell(lon, lat)
        s = math.cos(math.radians(lat))
        span = int(math.ceil(reach / CELL_M)) + 1
        best = None
        for i in range(-span, span + 1):
            for j in range(-span, span + 1):
                t = self.track.get((a + i, b + j))
                if t:
                    d = math.hypot(t[1] - x, t[2] - y) * s
                    if d <= reach and (best is None or d < best):
                        best = d
        return best

    def near(self, lon, lat, reach=REACH):
        """{fan: metres} for the fans with a cell within reach of a point."""
        x, y, a, b = self._cell(lon, lat)
        s = math.cos(math.radians(lat))
        span = int(math.ceil(reach / CELL_M)) + 1
        out = {}
        for i in range(-span, span + 1):
            for j in range(-span, span + 1):
                f = self.fan.get((a + i, b + j))
                if f is not None:
                    d = math.hypot((a + i + 0.5) * self.cell - x, (b + j + 0.5) * self.cell - y) * s
                    if d <= reach and d < out.get(f, 1e18):
                        out[f] = d
        return out

    def inside(self, poly):
        """What of the yard track lies inside an area: ({fan: share of its cells}, a point on the
        track inside the area or None, the cells of track inside it)."""
        w, s, e, n = poly.bounds
        (x0, x1), (y0, y1) = mercator([w, e], [s, n])
        a0, a1, b0, b1 = (int(math.floor(v / self.cell)) for v in (x0, x1, y0, y1))
        if (a1 - a0 + 1) * (b1 - b0 + 1) > 4_000_000:               # larger than any depot: a mapping slip
            return {}, None, set()
        cells = [(a, b) for a in range(a0, a1 + 1) for b in range(b0, b1 + 1) if (a, b) in self.track]
        if not cells:
            return {}, None, set()
        tx, ty = np.array([self.track[c][1] for c in cells]), np.array([self.track[c][2] for c in cells])
        lon, lat = lonlat(tx, ty)
        held = shapely.contains_xy(poly, lon, lat)
        if not held.any():
            return {}, None, set()
        count = Counter(self.fan[c] for c, h in zip(cells, held) if h and c in self.fan)
        shares = {f: n / len(self.cells[f]) for f, n in count.items()}
        # Stand on the track inside the area: on the fan it holds the most track of, among those it
        # holds, and there at the track nearest the middle of what is inside.
        main = max(shares, key=lambda f: (shares[f] >= HOLDS, count[f], -f)) if shares else None
        mine = held & np.array([self.fan.get(c) == main for c in cells]) if main is not None else held
        m = np.array([self.track[c][0] for c in cells]) * mine
        cx, cy = (m * tx).sum() / m.sum(), (m * ty).sum() / m.sum()
        k = int(np.argmin(np.where(mine, np.hypot(tx - cx, ty - cy), np.inf)))
        return shares, (float(lon[k]), float(lat[k])), {c for c, h in zip(cells, held) if h}

    def cell_at(self, lon, lat):
        """The cell of yard track nearest a point, within a cell's width of it, or None."""
        x, y, a, b = self._cell(lon, lat)
        near = [(math.hypot(self.track[c][1] - x, self.track[c][2] - y), c) for c in ((a + i, b + j) for i in (-1, 0, 1) for j in (-1, 0, 1)) if c in self.track]
        return min(near)[1] if near else None


def table_rows(g, path=TABLE):
    """The rows of the names table for one country: {"g", "at": [lon, lat], "n", "source", ...}."""
    rows = json.loads(path.read_text()) if path.exists() else []
    return [row for row in rows if row["g"] == g]


def labels(g, lines, named, table=(), running=()):
    """The labels of a country's yards and depots layer.

    lines: its yard track as drawn (coordinate lists). named: the named objects of the extract,
    each {"form", "name", "at": (lon, lat), "ring": outline as coordinate lists or None, "osm"}.
    table: the rows of data/depot_names.json for the country; running: the country's metro, light
    rail and tram lines as drawn (a metro depot whose own tracks are not drawn stands by them).
    Returns (labels, notes): labels are
    (name, lon, lat, where the name is from: "ground", a named area with yard track inside,
    "object", a point, or "table"); notes is what to print and to check: table rows that found
    no depot, rows on a depot that has a row already, and rows whose depot OSM names otherwise."""
    yards = Fans(lines, g)
    metro = Fans(running, g) if len(running) else None          # only its track is used: where the lines run
    grounds, points = [], []
    for order, o in enumerate(named):
        name, form = o["name"], o["form"]
        if not name or not_a_depot(g, name):
            continue
        poly = polygon_of(o["ring"]) if o.get("ring") else None
        shares, spot, cells = yards.inside(poly) if poly is not None else ({}, None, set())
        if not names_a_depot(g, name, form, max(shares.values(), default=0.0)):
            continue
        plain = generic(g, name)
        if spot is not None and form not in SHEDS and not plain:     # an area with yard track inside: a depot's ground
            grounds.append((-max(shares.values(), default=0.0), -len(cells), order, name, spot, cells, {f for f, s in shares.items() if s >= HOLDS}))
            continue
        if spot is None and form.startswith("landuse=") and form != "landuse=railway":
            continue                     # ground that is not railway ground holds no yard track: not the depot's
        at = spot or tuple(o["at"])      # a shed or a plainly named area stands as a point on its tracks
        by_line = metro and not plain and MORE[g].search(name) and not RAILWAY_ONLY[g].search(name)
        if yards.to_track(*at) is not None or (by_line and metro.to_track(*at) is not None):
            points.append(((plain, 0 if form in ("railway=yard", "railway=depot") else 1), order, name, at))
    def metres(a, b):
        return math.hypot((a[0] - b[0]) * math.cos(math.radians(a[1])), a[1] - b[1]) * 111320

    def by_a_ground(at):
        return any(metres(at, (x, y)) <= REACH for _, _, x, y, origin in out if origin == "ground")
    out, claimed, named_fan = [], set(), {}      # claimed: the track of the grounds that have their label; named_fan: fan -> the name on it
    for _, _, order, name, spot, cells, holds in sorted(grounds, key=lambda t: t[:3]):
        if 2 * len(cells & claimed) >= len(cells) and by_a_ground(spot):
            continue                     # mostly inside the ground of a depot that has its name, and next to that name
        claimed |= cells
        for f in holds:
            named_fan.setdefault(f, name)
        out.append((order, name, *spot, "ground"))
    at_fan, loose = defaultdict(list), []
    for rank, order, name, (lon, lat) in points:
        cell = yards.cell_at(lon, lat)
        if cell is not None and any((cell[0] + i, cell[1] + j) in claimed for i in (-2, -1, 0, 1, 2) for j in (-2, -1, 0, 1, 2)):
            continue                     # on a named ground, or at its edge: the same depot
        near = yards.near(lon, lat)
        if not near:
            loose.append((rank, order, name, lon, lat))
            continue
        f = min(near, key=lambda f: (near[f], f))
        if f not in named_fan or not rank[0] and not by_a_ground((lon, lat)):
            at_fan[f].append((rank, near[f], order, name, lon, lat))       # a large fan holds more than one depot
    for f in sorted(at_fan):
        _, _, order, name, lon, lat = min(at_fan[f])
        named_fan[f] = name
        out.append((order, name, lon, lat, "object"))
    taken = defaultdict(list)            # a name -> where it stands already
    for _, name, lon, lat, _ in out:
        taken[name].append((lon, lat))
    for rank, order, name, lon, lat in sorted(loose):
        if any(math.hypot(lon - x, lat - y) < 0.01 for x, y in taken[name]):
            continue                     # the same name again a few hundred metres on
        if rank[0] and any(metres((lon, lat), (x, y)) <= REACH for _, _, x, y, _ in out):
            continue                     # a plain name beside a particular one
        taken[name].append((lon, lat))
        out.append((order, name, lon, lat, "object"))
    out.sort()
    result = [(name, lon, lat, origin) for _, name, lon, lat, origin in out]
    notes = {"fans": len(yards.cells), "depots": len(set(yards.depot.values())), "no_depot": [], "second_row": [], "osm_differs": []}
    # The table, last: a row names the depot at its point where OSM has given that depot no name.
    rows = []
    for row in table:
        lon, lat = row["at"]
        near = yards.near(lon, lat, TABLE_REACH)
        if not near:
            notes["no_depot"].append(row["n"])
            continue
        f = min(near, key=lambda f: (near[f], f))
        cell = yards.cell_at(lon, lat)
        there = [name for name, x, y, _ in result if metres((lon, lat), (x, y)) <= REACH]
        if cell in claimed or f in named_fan or there:
            other = (there or [named_fan.get(f)])[0]
            if other and other != row["n"]:
                notes["osm_differs"].append((row["n"], other))
        elif any(yards.depot[f] == yards.depot[h] for h, _ in rows):
            notes["second_row"].append((row["n"], next(n for h, n in rows if yards.depot[f] == yards.depot[h])))
        else:
            rows.append((f, row["n"]))
            result.append((row["n"], float(lon), float(lat), "table"))
    return result, notes


def features(g, found, abroad=True, named=()):
    """The labels as the features of a depots file. named: the named objects they are read from,
    for a label's names beside n (scripts/names.py): nz from the country's names table, ne from
    the object's name:en."""
    from names import Names                  # here, as names.py is not needed to choose the labels
    names, english = Names(g), defaultdict(list)
    for o in named:
        if o.get("en"):
            english[o["name"]].append(o)
    out = []
    for name, lon, lat, origin in found:
        props = {"n": name, **({"g": g} if abroad else {}), "from": origin}
        objects = sorted(english.get(name, []), key=lambda o: (o["at"][0] - lon) ** 2 + (o["at"][1] - lat) ** 2)
        names.depot(props, (lon, lat), objects[0]["en"] if objects else None)
        out.append({"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}})
    return out


def audit(g, lines, depots, table=(), metro_lines=(), named=(), stations=(), running=()):
    """What a check asks of a written depots file. lines: the yard track as written; depots: the
    features of the depots file; metro_lines: the yard track of metros, light rail and trams (to
    tell their fans); named: the named objects of the extract (for the grounds that hold two
    depots of fans); stations: (lon, lat) of the stations (to leave station yards off the list to
    look at); running: the metro lines as drawn. Returns counts and lists:
      unnamed_metro  metro, light-rail or tram fans with no label within REACH
      held           of those, the ones a ground holds whose label stands on another of its fans:
                     named, and not counted in unnamed_metro
      unnamed_rail   the other depots of REVIEW_KM or more of track with no label and no station
                     within STATION_YARD_M: to look at
      far            labels further than REACH from yard track and from a drawn metro line
      doubled        fans with two differently named labels that are not each a named ground of
                     its own (a label is the name of the fan nearest to it)
      never          labels whose name is on the never list
      rows_lost      table rows at no fan; rows_doubled: two rows at one depot
      origin         labels by where the name is from"""
    yards = Fans(lines, g)
    along = Fans(running, g) if len(running) else None
    labelled, on_fan = defaultdict(set), defaultdict(set)          # depot -> names; fan -> names
    far, never = [], []
    for f in depots:
        name, (lon, lat) = f["properties"]["n"], f["geometry"]["coordinates"]
        if not_a_depot(g, name):
            never.append(name)
        if yards.to_track(lon, lat, REACH + 25) is None and (along is None or along.to_track(lon, lat, REACH + 25) is None):
            far.append(name)                 # (a label is written to a metre; the grid is 50 m)
        near = yards.near(lon, lat, REACH)
        if near:                         # a label is the name of the fan nearest to it
            fan = min(near, key=lambda f: (near[f], f))
            if f["properties"].get("from") != "ground":
                on_fan[fan].add(name)
            labelled[yards.depot[fan]].add(name)
    metro = Fans(metro_lines, g) if len(metro_lines) else None
    unnamed, unnamed_rail = [], []
    at_station = {f for lon, lat in stations for f in yards.near(lon, lat, STATION_YARD_M)}
    for depot in sorted(set(yards.depot.values())):
        fans = [f for f in yards.cells if yards.depot[f] == depot]
        cells = [c for f in fans for c in yards.cells[f]]
        if depot in labelled:
            continue
        biggest = max(fans, key=lambda f: yards.km[f])
        row = (round(sum(yards.km[f] for f in fans), 1), *(round(v, 5) for v in yards.centre[biggest]), fans)
        if metro is not None and sum(1 for c in cells if c in metro.track) >= 0.5 * len(cells):
            unnamed.append(row)
        elif row[0] >= REVIEW_KM and not at_station & set(fans):
            unnamed_rail.append(row[:3])
    # A ground can hold two depots of fans more than SAME_DEPOT_M apart (a depot's sheds and its
    # stabling yard); its label stands on one of them, and the other is named by it as well.
    held = []
    shown = {f["properties"]["n"] for f in depots if f["properties"].get("from") == "ground"}
    for row in list(unnamed):
        _, lon, lat, fans = row
        for o in named:
            poly = polygon_of(o["ring"]) if o["name"] in shown and o.get("ring") and abs(o["at"][0] - lon) < 0.03 and abs(o["at"][1] - lat) < 0.03 else None
            if poly is not None:
                shares = yards.inside(poly)[0]
                if any(shares.get(f, 0) >= HOLDS for f in fans):
                    held.append((row[0], lon, lat, o["name"]))
                    unnamed.remove(row)
                    break
    unnamed = [row[:3] for row in unnamed]
    lost, doubled_rows, seen = [], [], {}
    for row in table:
        near = yards.near(*row["at"], TABLE_REACH)
        if not near:
            lost.append(row["n"])
            continue
        d = yards.depot[min(near, key=lambda f: (near[f], f))]
        if d in seen:
            doubled_rows.append((row["n"], seen[d]))
        seen[d] = row["n"]
    return {"fans": len(yards.cells), "depots": len(set(yards.depot.values())), "labels": len(depots),
            "origin": dict(Counter(f["properties"].get("from", "?") for f in depots)),
            "unnamed_metro": sorted(unnamed, reverse=True), "held": held, "unnamed_rail": sorted(unnamed_rail, reverse=True), "far": far, "never": never,
            "doubled": sorted(sorted(names) for names in on_fan.values() if len(names) > 1),
            "rows_lost": lost, "rows_doubled": doubled_rows}


# What the labels must hold to, read off the files as written (scripts/check_layers.py for China,
# scripts/check_country.py for the others).
FIXED = {      # names that were missing or wrong on the map once: (must be there, must not be there)
    "cn": (("台北捷運土城機廠", "广清城际龙塘动车运用所"), ("施工廠區一區", "施工廠區二區", "施工廠區三區", "仕佳興業辦公室", "联合检修库")),
}
# Metro, light-rail and tram depots that may stand without a name: OSM has none for them that
# names a depot (a ground can carry only the company's name: （株）横浜シーサイドライン, whose own
# name no source gives) and the table has no source yet. The count
# as it is on 2026-10-10;
# one above it is a name lost.
UNNAMED_CEILING = {"cn": 17, "jp": 7, "kr": 1, "uk": 4}


def running_lines(g, data):
    """The country's metro, light-rail and tram lines as drawn, from its metro file."""
    path = data / f"{'' if g == 'cn' else g + '_'}metro.geojson"
    feats = json.loads(path.read_text())["features"] if path.exists() else []
    return [co for f in feats for co in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]])]


def check(g, data, extract):
    """The checks on a country's depot labels: [(needs a look?, text)] and the audit they rest on.
    data: the folder of the map's files; extract: the country's extract (for which yard track is
    a metro's)."""
    pre = "" if g == "cn" else g + "_"
    parts = lambda f: f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]]
    lines = [co for f in json.loads((data / f"{pre}yards.geojson").read_text())["features"] for co in parts(f)]
    depots = json.loads((data / f"{pre}depots.geojson").read_text())["features"]
    metro = [co for _, t, co in extract["ways"] if t.get("railway") in METRO_TRACK and t.get("service") in ("yard", "siding", "crossover")]
    a = audit(g, lines, depots, table_rows(g), metro, extract.get("named", ()), [(lon, lat) for _, lon, lat in extract.get("stations", ())],
              running_lines(g, data))
    names = {f["properties"]["n"] for f in depots}
    there, gone = FIXED.get(g, ((), ()))
    missing, back = [n for n in there if n not in names], [n for n in gone if n in names]
    by = a["origin"]
    out = [(False, f"depot labels: {a['labels']} at {a['depots']} depots (fans of yard track); from named ground with its tracks {by.get('ground', 0)}, "
                   f"from a yard or depot object {by.get('object', 0)}, from the names table {by.get('table', 0)}"),
           (len(a["unnamed_metro"]) > UNNAMED_CEILING[g], f"metro, light-rail and tram depots with no name within {REACH} m: {len(a['unnamed_metro'])} "
            f"(ceiling {UNNAMED_CEILING[g]}) " + str([f"{km} km at {lat},{lon}" for km, lon, lat in a["unnamed_metro"][:6]])
            + f"; {len(a['held'])} more named by a ground whose label stands on its other fans"),
           (False, f"to look at, not a fault: railway depots of {REVIEW_KM:.0f} km of track or more, no station within {STATION_YARD_M} m, with no name: {len(a['unnamed_rail'])} "
                   + str([f"{km} km at {lat},{lon}" for km, lon, lat in a["unnamed_rail"][:10]])),
           (bool(a["far"]), f"labels more than {REACH} m from yard track and from the metro lines as drawn: {len(a['far'])} {a['far'][:8]}"),
           (bool(a["doubled"]), f"fans of yard track with two differently named labels that are not each a ground of its own: {len(a['doubled'])} {a['doubled'][:6]}"),
           (bool(a["never"]), f"labels that name a building, a building site or an office: {len(a['never'])} {a['never'][:8]}"),
           (bool(a["rows_lost"] or a["rows_doubled"]), f"names table: {len(a['rows_lost'])} rows at no depot {a['rows_lost'][:8]}, "
            f"{len(a['rows_doubled'])} depots with two rows {a['rows_doubled'][:6]}")]
    if there or gone:
        out.append((bool(missing or back), f"the names once missing are there ({len(there) - len(missing)} of {len(there)}) and the ones once wrong are not "
                    f"({len(gone) - len(back)} of {len(gone)})" + (f": missing {missing}, back {back}" if missing or back else "")))
    return out, a
