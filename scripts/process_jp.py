"""Japan: railways and metros from data/raw/extract_jp.pkl, written as layers of their own.

    python3 scripts/extract_osm.py jp     japan-latest.osm.pbf -> data/raw/extract_jp.pkl (with trams and tram stops)
    python3 scripts/process_jp.py         -> data/jp_rail.geojson, jp_metro.geojson, jp_stations.geojson,
                                             jp_lines.json, jp_metro_cities.json, jp_build.geojson,
                                             jp_yards.geojson, jp_depots.geojson

The page adds these to the layers it already has (site.json: {"jp": true}), so the features carry
the same properties as the Chinese ones: c (class), n (line), o (operator), plus lc, the line's
own colour. Nothing here touches the Chinese data or scripts/process_osm.py.

Colours follow the one rule for every country (user, 2026-10-08, after trying company colours and
line colours for the Shinkansen and dropping both):
- a high-speed line is drawn in the band of its design speed, the same seven bands as in China
  (property c = the band, d = the speed): here the Shinkansen, all built for 260 km/h;
- any other railway is drawn in its own line colour where it has one (ラインカラー, set per line or
  service and used on route maps and station signs; property lc), otherwise in the neutral colour
  of conventional lines (no lc). Never in the colour of its company;
- metros, monorails and trams are drawn in their official line colour.
Source for line colours as a convention: https://ja.wikipedia.org/wiki/日本の鉄道ラインカラー一覧
(read 2026-10-08).

A line is the track that carries its name in OSM (99% of running track is named, 98% has an
operator), drawn once (scripts/single_track.py). Its colour comes from the route relations that
run on it: one that covers most of the line and lies mostly on that line (a through service or a
long-distance express does neither).

The street tramways (路面電車: 都電荒川線, 広島電鉄, 長崎電気軌道, ...) are lines of the urban class
like the light rail, each under the name its track carries (広島電鉄本線, 広島電鉄宇品線: the lines a
system is made of, not the numbered routes run over them). A station or a stop is drawn only
where a drawn line passes it (with_a_line).
"""
import colorsys
import json
import math
import pickle
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from shapely import STRtree
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge

sys.path.insert(0, str(Path(__file__).resolve().parent))
from design_speeds import grade
from names import Names, city_names, name_city
from side_by_side import abreast, side_by_side
from yards import write_yards
from single_track import curved, join_up, one_track, smooth, stitch

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data"
SKIP_USAGE = {"industrial", "military", "tourism", "test", "freight", "yard"}
METRO_RAIL = {"subway", "light_rail", "monorail", "tram"}
TOL = {"fast": 0.00008, "rail": 0.00012, "metro": 0.00006, "light": 0.00002}
CURVE = {"fast": (4, 5, 0.0003), "rail": (5, 4, 0.0003)}
# The six JR passenger companies and JR Freight: (pattern on the operator tag, name).
JR = [
    (r"北海道旅客鉄道|JR北海道|JR Hokkaido", "JR北海道"),
    (r"東日本旅客鉄道|JR東日本|JR East|East Japan Railway", "JR東日本"),
    (r"東海旅客鉄道|JR東海|JR Central", "JR東海"),
    (r"西日本旅客鉄道|JR西日本|JR West", "JR西日本"),
    (r"四国旅客鉄道|JR四国|JR Shikoku", "JR四国"),
    (r"九州旅客鉄道|JR九州|JR Kyushu", "JR九州"),
    (r"日本貨物鉄道|JR貨物|JR Freight", "JR貨物"),
]
# Companies known by a short name, which their lines are called by (近鉄大阪線, 名鉄名古屋本線).
SHORT = {"近畿日本鉄道": "近鉄", "名古屋鉄道": "名鉄", "京浜急行電鉄": "京急", "西日本鉄道": "西鉄", "南海電気鉄道": "南海",
         "京阪電気鉄道": "京阪", "阪急電鉄": "阪急", "阪神電気鉄道": "阪神", "小田急電鉄": "小田急", "京成電鉄": "京成",
         "京王電鉄": "京王", "東急電鉄": "東急", "東武鉄道": "東武", "西武鉄道": "西武", "相模鉄道": "相鉄",
         "山陽電気鉄道": "山陽電鉄", "神戸電鉄": "神鉄", "東京地下鉄": "東京メトロ", "大阪市高速電気軌道": "Osaka Metro"}
OPERATOR_ALIASES = {"東京急行電鉄": "東急電鉄"}
# OSM can put an infrastructure owner on a short station approach instead of the passenger
# railway that the named line belongs to. Keep narrowly verified whole-line identities here.
# 久留里線 carries no operator on any of its track in OSM; it is a JR East line
# (https://ja.wikipedia.org/wiki/久留里線: 東日本旅客鉄道（JR東日本）の鉄道路線, read 2026-10-08).
KNOWN_LINE_FIRM = {"山田線": "JR東日本", "久留里線": "JR東日本"}
# A line's name mistyped on some of its track, or written another way on a few metres of it.
NAME_TYPOS = {"R久留里線": "久留里線", "熊本市営田崎線": "熊本市電田崎線", "鹿児島市営谷山線": "鹿児島市電谷山線", "鹿児島市営第一期線": "鹿児島市電第一期線"}
# A tramway's name says whose it is (広島電鉄本線, 函館市電本線, 都電荒川線). One that does not
# (岡山電気軌道's 東山本線 and 清輝橋線, とさでん交通's 桟橋線) takes its company in front, as the
# other lines of とさでん交通 have it in OSM.
SAYS_WHOSE = re.compile(r"電|鉄|軌道|交通|ライトレール")
# The design speed of the Shinkansen: 「ミニ新幹線を除いて、1964年（昭和39年）に開業した東海道新幹線から
# 全て設計最高速度260 km/hで建設されている」 (https://ja.wikipedia.org/wiki/新幹線, read 2026-10-08).
# What each line runs at today (285 to 320 km/h on the older ones) is a running speed, not this.
SHINKANSEN_DESIGN = (260, "https://ja.wikipedia.org/wiki/新幹線")
# The two "mini-Shinkansen" run on conventional lines converted to standard gauge: they are of the
# Shinkansen class (jk shinkansen, as the owner lists them, 2026-10-10) but not in its speed band,
# since they were not built to its design speed, and no source gives them one. They are marked mini,
# keep the line colours the source in the module docstring gives them (山形新幹線：橙, 秋田新幹線：桃),
# count in no band figure, and carry their top speed as a top speed (d with e, as every speed that
# is not a design speed): the infobox of each (read 2026-10-10) gives 最高速度
# 「130 km/h（東京駅 - 大宮駅間・福島駅 - 新庄駅間）」 and 「130 km/h（盛岡駅 - 秋田駅間）」.
# The termini are the line's two ends, which a check holds the drawing to.
# 秋田新幹線 reverses at 大曲 (盛岡 - 大曲 on the 田沢湖線, 大曲 - 秋田 on the 奥羽本線): a drawn end there is no fault.
MINI = {"山形新幹線": dict(top=130, ref="https://ja.wikipedia.org/wiki/山形新幹線", ends=("福島", "新庄"), via=()),
        "秋田新幹線": dict(top=130, ref="https://ja.wikipedia.org/wiki/秋田新幹線", ends=("盛岡", "秋田"), via=("大曲",))}
KNOWN_COLOUR = {"山形新幹線": "#ff9a3d", "秋田新幹線": "#ff8fb3"}
# Two lines on one track, where OSM names the track for only one of them: each is drawn there, side
# by side, as lines that share track are everywhere on the map. The track is the running track of
# the line's route relation (route=railway) that either line has; the line keeps the English name
# of its relation.
# - 山形新幹線 runs on the 奥羽本線 from 福島 to 新庄, converted to standard gauge for it, and the
#   奥羽本線's own trains still run there (its local trains are called 山形線): 「奥羽本線の福島駅 -
#   新庄駅間の軌間（線路幅）を1435 mmの標準軌に改軌して」, 148.6 km (https://ja.wikipedia.org/wiki/山形新幹線,
#   read 2026-10-10). OSM names that track 奥羽本線; relation 5361845 is the line.
# - 田沢湖線 is the track of the 秋田新幹線 from 盛岡 to 大曲, and its own trains run there; OSM names
#   that track 秋田新幹線 (JR田沢湖線;秋田新幹線); relation 1934364 is the line.
# - 秋田新幹線 runs on the 奥羽本線 from 大曲 to 秋田 (「大曲駅から秋田駅までは奥羽本線を走行する」,
#   盛岡 - 秋田 127.3 km: https://ja.wikipedia.org/wiki/秋田新幹線, read 2026-10-10). Most of its
#   track there OSM names 秋田新幹線, but 4 km by 四ツ小屋 it names 奥羽本線, and the line had a gap
#   there; relation 5361971 is the line, and also has the 東北新幹線's track into 盛岡, its terminus.
#
# The line takes the relation's track that OSM puts on the lines the rule names, or on any other
# line that is not a Shinkansen and joins that track (山形新幹線 by 羽前千歳 runs on track OSM gives
# the 仙山線; the relation's piece of the 東北新幹線 by 那須塩原 joins nothing of it). A
# mini-Shinkansen is its relation's track and what joins it: a piece OSM names for it that touches
# none of that goes to the line the rule names first (山形's 3 km of narrow-gauge track beside its
# own between 山形 and 羽前千歳, "JR奥羽本線・山形新幹線", is the 奥羽本線's).
SHARED_LINE = {"山形新幹線": dict(relation=5361845, on=("JR奥羽本線",)),
               "JR田沢湖線": dict(relation=1934364, on=("秋田新幹線",)),
               "秋田新幹線": dict(relation=5361971, on=("JR奥羽本線", "東北新幹線"))}


def parts_of(f):
    g = f["geometry"]
    return g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]


def english_part(english, name):
    """A track's English name where it names two lines ("JR Tazawako Line; Akita Shinkansen"): the
    part for this line, the Shinkansen's for a Shinkansen, the other for the other."""
    parts = [p.strip() for p in re.split(r"[;；]", english or "") if p.strip()]
    if len(parts) < 2:
        return english
    return next((p for p in parts if ("Shinkansen" in p) == ("新幹線" in name)), parts[0])
METRO_MIN_KM = 2.0         # shorter "lines" on metro-type track are rides in parks
TRAM_GAP = 0.00025         # ~27 m: a tramway's own track within this is its second track (a metro's two tubes: single_track.GAP, 66 m)
# A station is drawn only where a drawn line passes it. One on a line that is not drawn (closed,
# replaced by buses, a ride, a tramway left out) is a dot in the middle of nothing: the owner saw
# Tokyo's 都電 stops so, before the tramways were drawn.
STATION_REACH = 0.006      # ~600 m: a railway station this far from every drawn line is on none of them (as in China)
STOP_REACH = 0.0025        # ~275 m: a metro station or a tram stop needs a line of the metro layer this near (as in China)
ON_LINE = 0.001            # ~110 m: ... or a railway right at it (京急蒲田 is tagged as a subway station; 鞍馬's dot is 75 m past the end of its line)
# Japan rail kind (jk): a Japan-only taxonomy by operator + infrastructure, NOT China's 高铁/普速/地铁
# and NOT any speed design. Authoritative lists in data/jp_operator_classification_list.json:
#   shinkansen    route name is a Shinkansen, 山形 and 秋田 too (MINI: marked mini, not in the speed band)
#   jr            the six JR passenger companies + JR Freight (JR グループ在来線)
#   private_big   大手民鉄 16 社 (minority: 東京地下鉄 is on the metro layer)
#   private_local 地方中小民鉄 + 第三セクター (41 社)
#   unknown       operator-less fragments: counted in the audit, NOT dumped, NOT hidden
# Metro (separate layer): subway (地下鉄) / urban (路面電車·モノレール·AGT 新交通)
JR_FIRMS = {"JR北海道", "JR東日本", "JR東海", "JR西日本", "JR四国", "JR九州", "JR貨物"}
BIG16 = {"東武鉄道", "西武鉄道", "京成電鉄", "京王電鉄", "小田急電鉄", "東急電鉄", "京浜急行電鉄",
         "相模鉄道", "名古屋鉄道", "近畿日本鉄道", "南海電気鉄道", "京阪電気鉄道", "阪急電鉄",
         "阪神電気鉄道", "西日本鉄道"}
THIRD_SECTOR = {"道南いさりび鉄道", "三陸鉄道", "アイジーアールいわて銀河鉄道", "阿武隈急行", "秋田内陸縦貫鉄道",
                "由利高原鉄道", "山形鉄道", "会津鉄道", "野岩鉄道", "鹿島臨海鉄道", "真岡鐵道", "わたらせ渓谷鐵道",
                "いすみ鉄道", "北越急行", "えちごトキめき鉄道", "しなの鉄道", "あいの風とやま鉄道", "IRいしかわ鉄道",
                "ハピラインふくい", "のと鉄道", "長良川鉄道", "樽見鉄道", "明知鉄道", "天竜浜名湖鉄道", "愛知環状鉄道",
                "伊勢鉄道", "京都丹後鉄道", "北条鉄道", "智頭急行", "若桜鉄道", "井原鉄道", "錦川鉄道", "阿佐海岸鉄道",
                "土佐くろしお鉄道", "平成筑豊鉄道", "甘木鉄道", "松浦鉄道", "南阿蘇鉄道", "くま川鉄道", "肥薩おれんじ鉄道",
                "青い森鉄道"}
EXPRESS = re.compile(r"特急|急行|快速|快特|準急|ライナー|エクスプレス|Express|Limited|直通|新幹線.*(号|列車)|のぞみ|ひかり|こだま|はやぶさ|はやて|みずほ|さくら|つばめ|かがやき|はくたか|とき")
STRUCTURE = re.compile(r"(トンネル|隧道|橋梁|橋りょう|高架橋|橋)$")
CSS = {"red": "#ff0000", "blue": "#0000ff", "green": "#008000", "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080",
       "pink": "#ffc0cb", "brown": "#a52a2a", "black": "#000000", "white": "#ffffff", "gray": "#808080", "grey": "#808080",
       "cyan": "#00ffff", "magenta": "#ff00ff", "navy": "#000080", "maroon": "#800000", "olive": "#808000", "teal": "#008080",
       "lime": "#00ff00", "gold": "#ffd700", "silver": "#c0c0c0", "skyblue": "#87ceeb"}
# Metro lines are listed by city: (name shown, lon, lat). A line belongs to the nearest one.
# Metro lines are listed by city: (name shown, lon, lat, reach in degrees). The cities beside a
# bigger one come first and reach less far, so that only their own lines are theirs.
CITIES = [("横滨", 139.622, 35.466, 0.12), ("千叶", 140.113, 35.613, 0.2), ("京都", 135.759, 35.012, 0.17), ("神户", 135.195, 34.690, 0.2),
          ("北九州", 130.875, 33.883, 0.25), ("宇都宫", 139.90, 36.56, 0.2), ("丰桥", 137.39, 34.76, 0.15),
          ("东京", 139.767, 35.681, 0.9), ("大阪", 135.502, 34.694, 0.7), ("名古屋", 136.907, 35.170, 0.6),
          ("札幌", 141.351, 43.062, 0.6), ("仙台", 140.882, 38.260, 0.6), ("福冈", 130.401, 33.590, 0.5), ("广岛", 132.459, 34.396, 0.5),
          ("那霸", 127.681, 26.212, 0.5), ("福井", 136.223, 36.062, 0.4), ("富山", 137.213, 36.701, 0.4),
          # the cities of the tramways
          ("函馆", 140.73, 41.77, 0.2), ("冈山", 133.92, 34.66, 0.2), ("松山", 132.77, 33.84, 0.2), ("高知", 133.54, 33.56, 0.3),
          ("熊本", 130.71, 32.80, 0.2), ("长崎", 129.87, 32.75, 0.2), ("鹿儿岛", 130.55, 31.59, 0.25)]


def km(co):
    return sum(math.hypot((x2 - x1) * math.cos(math.radians((y1 + y2) / 2)), y2 - y1) * 111.32 for (x1, y1), (x2, y2) in zip(co, co[1:]))


def runs_of(lines):
    merged = linemerge(MultiLineString(lines))
    return list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]


def colour_of(value):
    c = (value or "").strip().lower()
    c = CSS.get(c, c)
    if re.fullmatch(r"#[0-9a-f]{3}", c):
        c = "#" + "".join(ch * 2 for ch in c[1:])
    return c if re.fullmatch(r"#[0-9a-f]{6}", c) else None


def readable_on_dark(col):
    """Lift a dark colour so that it shows on dark satellite imagery."""
    r, g, b = (int(col[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, l, sat = colorsys.rgb_to_hls(r, g, b)
    while 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.42 and l < 0.8:      # a pure blue is as dark to the eye as a dark grey
        l += 0.04
        r, g, b = colorsys.hls_to_rgb(h, l, sat)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def company(operator):
    """(company name, short name its lines go by) from an operator tag."""
    first = (operator or "").split(";")[0].strip()
    for pattern, name in JR:
        if re.search(pattern, first):
            return name, "JR"
    plain = re.sub(r"\s*[（(].*?[)）]", "", unicodedata.normalize("NFKC", first)).replace("株式会社", "").strip()
    if not plain:
        return None, ""
    plain = OPERATOR_ALIASES.get(plain, plain)
    short = SHORT.get(plain) or re.sub(r"(電気鉄道|電気軌道|高速鉄道|電鉄|鉄道|鐵道)$", "", plain) or plain
    return plain, short


def colouring(name, jk, line_colour):
    """The properties that colour a railway line, by the one rule: a high-speed line by the band of
    its design speed, any other line by its own colour if it has one, and otherwise nothing (the
    page then draws it in the neutral colour of conventional lines)."""
    if jk == "shinkansen" and name not in MINI:
        speed, source = SHINKANSEN_DESIGN
        return {"c": grade(speed), "d": speed, "ref": source}
    how = {"lc": line_colour} if line_colour else {}
    if name in MINI:                                  # a top speed, not a design speed: no band
        how.update(d=MINI[name]["top"], e=1, ref=MINI[name]["ref"])
    return how


def jkind(name, firm):
    """Japan-only rail bucket for a line (operator-based, authoritative lists):
    shinkansen / jr / private_big / third_sector / private_local / unknown.
    The line's `firm` is its grouped company (operator-less ways already merged into a same-named
    line). No operator -> unknown (counted in the audit, never dumped, never hidden)."""
    if "新幹線" in (name or ""):
        return "shinkansen"                          # the mini-Shinkansen too (MINI), outside the speed band
    if firm in JR_FIRMS:
        return "jr"
    if (name or "").startswith("JR"):
        return "jr"
    branded_owner = next((owner for owner, prefix in SHORT.items() if (name or "").startswith(prefix)), None)
    if branded_owner in BIG16:
        return "private_big"
    if branded_owner in THIRD_SECTOR:
        return "third_sector"
    if branded_owner:
        return "private_local"
    if not firm:
        return "unknown"
    if firm in BIG16:
        return "private_big"
    if firm in THIRD_SECTOR:
        return "third_sector"
    return "private_local"     # 地方中小民鉄 (and other small private firms)


def metro_jk(kinds):
    """Metro infrastructure bucket: underground (subway) vs other urban rail (tram/monorail/AGT).
    light_rail mixes tram and AGT and the metro feature carries no operator, so they are combined."""
    return "subway" if kinds["subway"] >= kinds["monorail"] + kinds["light_rail"] + kinds["tram"] else "urban"


def tram_systems(lines, ways, track=()):
    """Which tramway lines hang together as one system: {line: the lines of its system}. lines:
    {line: its ways}; ways: {way: (tags, coordinates)}; track: every way of tram track there is,
    named or not (the lines of a system meet at junctions whose curves carry no name). A system
    is made of several named lines, some of a few hundred metres (広島電鉄白島線, 札幌市電都心線,
    長崎's 支線), which belong on the map with the rest of it; a short line on its own is a ride."""
    every = set(track) | {w for wids in lines.values() for w in wids}
    at = defaultdict(set)                          # a point of track -> the ways through it
    for w in every:
        for pt in ways[w][1]:
            at[pt].add(w)
    group = {w: w for w in every}

    def root(w):
        while group[w] != w:
            group[w] = group[group[w]]
            w = group[w]
        return w
    for here in at.values():
        first, *rest = sorted(here)
        for w in rest:
            group[root(w)] = root(first)
    on = defaultdict(set)                          # a network of track -> the lines on it
    for key, wids in lines.items():
        for w in wids:
            on[root(w)].add(key)
    return {key: set().union(*(on[root(w)] for w in wids)) for key, wids in lines.items()}


def terminus_track(line_of, ways, stations, at_station=0.0006, short=0.001):
    """Siding-tagged track that is a line's way into its terminus: {way: line}. line_of: {way:
    (layer, company, name)} of the running track; ways: {way: (tags, coordinates)}; stations:
    (tags, lon, lat) as extracted. A line is drawn to its terminus, and a train's way into its
    last station is no siding whatever the mappers have tagged it: track of the urban layer that
    carries the line's own name, leads on from where the line's running track stops, and ends at
    a station (within at_station) that the running track stops short of (by more than short).
    北九州高速鉄道小倉線 was drawn 830 m short of 企救丘 without it. A pocket track, a turnback
    beyond a terminus or a depot lead ends at no station, and is left as it is."""
    lines = defaultdict(list)
    for wid, key in line_of.items():
        if key[0] == "metro":
            lines[key[2]].append(wid)
    ends = {name: Counter(pt for w in wids for pt in (ways[w][1][0], ways[w][1][-1])) for name, wids in lines.items()}
    track = {}
    found = {}
    for wid, (t, co) in ways.items():
        if t.get("service") != "siding" or t.get("railway") not in METRO_RAIL or wid in line_of:
            continue
        name = plain_name(t.get("name"), None)
        if name not in lines:
            continue
        for near, far in ((co[0], co[-1]), (co[-1], co[0])):
            if ends[name][near] != 1:
                continue                               # not where the line's running track stops
            if name not in track:
                track[name] = MultiLineString([ways[w][1] for w in lines[name]])
            for _, lon, lat in stations:
                if math.hypot(lon - far[0], lat - far[1]) < at_station and track[name].distance(Point(lon, lat)) > short:
                    found[wid] = ("metro", None, name)
    return found


def with_a_line(stations, rail, metro):
    """The stations that a drawn line passes, of station features (property m: a metro station or
    a tram stop). rail, metro: the drawn lines of the two layers, as coordinate lists. A railway
    station needs a line of either layer within STATION_REACH; a metro station or a tram stop
    needs a line of the metro layer within STOP_REACH, or a railway within ON_LINE."""
    tree = lambda lines: STRtree([LineString(co) for co in lines]) if lines else None
    rail_tree, metro_tree, any_tree = tree(rail), tree(metro), tree(list(rail) + list(metro))
    near = lambda t, pt, reach: t is not None and len(t.query(pt, predicate="dwithin", distance=reach)) > 0
    kept = []
    for f in stations:
        pt = Point(f["geometry"]["coordinates"])
        if f["properties"].get("m"):
            served = near(metro_tree, pt, STOP_REACH) or near(rail_tree, pt, ON_LINE)
        else:
            served = near(any_tree, pt, STATION_REACH)
        if served:
            kept.append(f)
    return kept


def plain_name(name, firm=None):
    """A track's name as the name of its line: without what is added in brackets or after a
    semicolon, without the company's full name in front (京王電鉄相模原線), and for a structure
    on a line (a named tunnel or bridge) nothing at all."""
    name = unicodedata.normalize("NFKC", name or "")
    parts = [re.sub(r"\s*[（(].*?[)）]", "", p).strip() for p in re.split(r"[;；]", name)]
    parts = [p for p in parts if p]
    lines = [p for p in parts if not STRUCTURE.search(p)]
    if not lines:
        return ""
    name = next((p for p in lines if "新幹線" in p), lines[0])
    if "新幹線" in name:                                   # 海峡線・北海道新幹線, 博多南線・九州新幹線: track of the Shinkansen
        name = next(p for p in re.split(r"[・·]", name) if "新幹線" in p)
    name = re.sub(r"^JR\s*", "", name).strip()
    if firm and name.startswith(firm) and len(name) > len(firm) + 1:
        name = name[len(firm):].strip()
    else:
        for owner, short in SHORT.items():
            if name.startswith(owner) and len(name) > len(owner) + 1:
                name = short + name[len(owner):].strip()
                break
    return name


def shown_name(name, firm, short):
    """The line as people call it: JR山手線, 近鉄大阪線, 京急本線. Only the companies whose lines go
    by a short name get it put in front; the Shinkansen need none."""
    if "新幹線" in name or not (short == "JR" or firm in SHORT) or name.startswith(short):
        return name
    return short + name


def key_of(name):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name or ""))


def rounded(geoms, tol, curve=None, adaptive=False, places=6):
    out = []
    for g in geoms:
        co = smooth(list(g.simplify(tol, preserve_topology=False).coords), reverse=181)
        if len(co) > 1 and LineString(co).length > 0:
            if curve:
                co = curved(co, *curve, within=tol, adaptive=adaptive)
            co = [[round(x, places), round(y, places)] for x, y in co]
            out.append([p for i, p in enumerate(co) if not i or p != co[i - 1]])
    return [co for co in out if len(co) > 1]


def geometry(lines):
    return {"type": "LineString", "coordinates": lines[0]} if len(lines) == 1 else {"type": "MultiLineString", "coordinates": lines}


def bbox_of(lines):
    xs, ys = [p[0] for co in lines for p in co], [p[1] for co in lines for p in co]
    return [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]


# Confirmed name-variant merges (piece shown name -> parent shown name). A piece is folded into its
# parent ONLY when it is listed here AND the strict topology holds (short, same company, both free
# ends meet that one parent, parent is a real main line). >=5 km parent length is a safety check,
# not by itself proof that two names are the same line; every other short connector keeps its own
# identity (real branch, freight spur, or just an unverified alias candidate).
CONFIRMED_SHORT_ALIASES = {
    # keys are the production (shown_name) track names, not the raw OSM names.
    "JR中央・総武緩行線": "JR中央緩行線",   # 千駄ケ谷 parallel platform stubs between two points of 中央緩行線
}


def merge_short_connectors(tracks, ways, length, aliases=CONFIRMED_SHORT_ALIASES, max_km=0.6, min_parent_km=5.0, line_of=None):
    """Fold a CONFIRMED short name-variant piece into the line it bridges (千駄ケ谷:
    "中央・総武緩行線" between two points of "中央緩行線"). The whitelist gates which pairs are
    allowed; topology then guards against actually joining a wrong piece:
      * the piece is short (< max_km) on the SAME company;
      * BOTH free ends meet exactly that parent (n >= 2), so a single-end branch survives;
      * the parent is a real main line (>= min_parent_km), so two short yard tracks touching each
        other are never folded into each other.
    Returns the moved map. Geometry is kept, only reclassified."""
    at = defaultdict(set)
    for key, wids in tracks.items():
        if key[0] != "rail":
            continue
        for w in wids:
            for p in (ways[w][1][0], ways[w][1][-1]):
                at[(round(p[0], 4), round(p[1], 4))].add(key)
    moved = {}
    for key, wids in list(tracks.items()):
        if key[0] != "rail" or sum(length[w] for w in wids) >= max_km:
            continue
        parent_name = aliases.get(key[2])
        if parent_name is None:
            continue                                     # not a confirmed alias: keep its own line
        touch = defaultdict(int)
        for w in wids:
            for p in (ways[w][1][0], ways[w][1][-1]):
                for o in at[(round(p[0], 4), round(p[1], 4))]:
                    if o != key:
                        touch[o] += 1
        # the only acceptable parent is the whitelisted one, reached at both ends and long enough
        parents = {o for o, n in touch.items()
                   if n >= 2 and o[0] == "rail" and o[1] == key[1] and o[2] == parent_name
                   and sum(length[w] for w in tracks[o]) >= min_parent_km}
        if len(parents) == 1:
            moved[key] = next(iter(parents))
    for key, parent in moved.items():
        for w in tracks[key]:
            if line_of is not None:
                line_of[w] = parent          # keep line_of in lockstep: the child key is gone
        tracks[parent].extend(tracks.pop(key))
    return moved


def adopt_unnamed(line_of, unnamed, ways):
    """Track that names no line (no name, or a tunnel or bridge named for itself) joins the line
    it connects. It is taken stretch by stretch, a stretch being such track joined end to end,
    however many ways it is drawn as: taken way by way, only a single way between two pieces of a
    line was ever filled in, and a longer unnamed stretch left a gap in the line (Kings Park to
    Burnside on Glasgow's Kirkhill Line, 21 ways). A stretch goes to the line it meets at most of
    the places where it ends: the line on both sides of it, or the one it leads off. Returns
    the track that meets no line at all, which stays undrawn."""
    ends = lambda wid: (ways[wid][1][0], ways[wid][1][-1])
    at = defaultdict(set)                          # a track end -> the lines that end there
    for wid, key in line_of.items():
        for end in ends(wid):
            at[end].add(key)
    group = {wid: wid for wid in unnamed}

    def root(wid):
        while group[wid] != wid:
            group[wid] = group[group[wid]]
            wid = group[wid]
        return wid
    first = {}
    for wid in unnamed:
        for end in ends(wid):
            if end in first:
                group[root(wid)] = root(first[end])
            else:
                first[end] = wid
    stretches = defaultdict(list)
    for wid in unnamed:
        stretches[root(wid)].append(wid)
    left = []
    for wids in stretches.values():
        met = Counter(key for end in sorted({end for wid in wids for end in ends(wid)}) for key in at[end])
        if not met:
            left.extend(wids)
            continue
        line = max(met.items(), key=lambda kv: (kv[1], str(kv[0])))[0]
        for wid in wids:
            line_of[wid] = line
    return left


def being_built(ways, code, name_of, build_name=lambda name: name, build_fast=lambda name: False, names=None):
    """The lines under construction of a country, as features of the layer of lines being built
    (drawn dashed): the track being built under one name is one line, drawn once; a line with
    less than 2 km of it is left out. build_fast says which are high-speed lines (property h);
    names (scripts/names.py) gives a line its names beside n."""
    building = defaultdict(list)
    for wid, (t, co) in ways.items():
        if t.get("railway") == "construction" and (t.get("construction") or t.get("construction:railway")) in ("rail", "light_rail", "tram", "subway", None):
            name = build_name(name_of(t.get("name")))
            if name:
                building[name].append(wid)
    feats = []
    for name, wids in sorted(building.items()):
        drawn = stitch(one_track(runs_of([ways[w][1] for w in wids])))
        simp = rounded(drawn, TOL["rail"], CURVE["rail"], places=5)
        if simp and sum(km(co) for co in simp) >= 2:
            props = {"c": "build", "n": name, "g": code}
            if build_fast(name):
                props["h"] = 1                       # a high-speed line: drawn in the colour of lines being built
            if names:
                for w in wids:
                    names.add(name, ways[w][0], km(ways[w][1]))
                names.line(props)
            feats.append({"type": "Feature", "properties": props, "geometry": geometry(simp)})
    return feats


def main():
    # written locally by scripts/extract_osm.py, so loading it is safe here
    ex = pickle.load(open(RAW / "extract_jp.pkl", "rb"))
    ways = {wid: (t, co) for wid, t, co in ex["ways"]}
    names = Names("jp")                           # names beside n: nz from a sound name:zh, ne from name:en
    length = {wid: km(co) for wid, (t, co) in ways.items()}

    # ---------------------------------------------------------------- which line every track belongs to
    line_of = {}                                   # way -> (layer, company, line name)
    unnamed, bare = [], defaultdict(set)           # bare: a line's name without its company -> the lines so named
    unnamed_tram = []
    says_jr = set()                                # track whose own name begins with JR
    for wid, (t, co) in ways.items():
        kind = t.get("railway")
        if t.get("service") or t.get("usage") in SKIP_USAGE or kind not in METRO_RAIL | {"rail"}:
            continue
        firm, short = company(t.get("operator"))
        metro = kind in METRO_RAIL
        name = plain_name(t.get("name"), None if metro else firm)
        name = NAME_TYPOS.get(name, name)
        if kind == "tram" and name and firm and not SAYS_WHOSE.search(name):
            name = firm + name
        if unicodedata.normalize("NFKC", t.get("name") or "").startswith("JR"):
            says_jr.add(wid)
        if not metro and name in KNOWN_LINE_FIRM:
            firm = KNOWN_LINE_FIRM[name]
            short = "JR"
        if name and metro:                          # a metro line's track carries the line's full name: no company needed to tell two apart
            line_of[wid] = ("metro", None, name)
        elif name:
            line_of[wid] = ("rail", firm, shown_name(name, firm, short))
            bare[name].add(line_of[wid])
        elif kind == "rail":
            unnamed.append(wid)
        elif kind == "tram":
            unnamed_tram.append(wid)
    # track of a line that carries no operator belongs to the one company that has a line of that name
    for wid, key in list(line_of.items()):
        if key[0] == "rail" and key[1] is None:
            owners = {k for k in bare[key[2]] if k[1]}
            if len(owners) == 1:
                line_of[wid] = next(iter(owners))
    # Where several companies have a line of that name, and they are all JR companies (JR東海道本線
    # runs through three), or the track's own name says JR (JR奈良線 beside 近鉄奈良線): to the JR
    # company whose track of that line it joins, and failing that to the one it lies nearest.
    ways_of = defaultdict(list)
    for wid, key in line_of.items():
        ways_of[key].append(wid)
    for key in sorted(k for k in ways_of if k[0] == "rail" and k[1] is None):
        every = sorted(k for k in bare[key[2]] if k[1])
        owners = [k for k in every if k[1].startswith("JR")]
        if not owners:
            continue
        ends = defaultdict(set)                    # track end -> the companies whose track of this line ends there
        for k in owners:
            for w in ways_of[k]:
                co = ways[w][1]
                ends[co[0]].add(k)
                ends[co[-1]].add(k)
        todo = [w for w in ways_of[key] if len(owners) == len(every) or w in says_jr]
        while todo:
            left = []
            for w in todo:
                co = ways[w][1]
                met = ends[co[0]] | ends[co[-1]]
                if len(met) != 1:
                    left.append(w)
                    continue
                line_of[w] = next(iter(met))
                ends[co[0]].add(line_of[w])
                ends[co[-1]].add(line_of[w])
            if len(left) == len(todo):
                break
            todo = left
        if todo:
            track = {k: MultiLineString([ways[w][1] for w in ways_of[k]]) for k in owners}
            for w in todo:
                g = LineString(ways[w][1])
                line_of[w] = min(owners, key=lambda k: (track[k].distance(g), k))
    # A tunnel or a bridge named for itself, and track with no name, between two pieces of one
    # line is that line (榛名トンネル on the 上越新幹線): it would otherwise cut the line in two.
    unnamed = adopt_unnamed(line_of, unnamed, ways)
    into = terminus_track(line_of, ways, ex["stations"])
    line_of.update(into)
    print(f"japan: siding-tagged track taken as a line's way into its terminus: {sorted({key[2] for key in into.values()})}, "
          f"{sum(length[w] for w in into):.1f} km of track", flush=True)
    # The same for a tramway's track with no name, among the tramways: the curves of a junction in
    # the street, where the lines of a system meet.
    tram_of = {wid: key for wid, key in line_of.items() if ways[wid][0].get("railway") == "tram"}
    left = adopt_unnamed(tram_of, unnamed_tram, ways)
    line_of.update(tram_of)
    print(f"japan tramways: {sum(length[w] for w in unnamed_tram) - sum(length[w] for w in left):.1f} km of unnamed track joined to the line it connects, "
          f"{sum(length[w] for w in left):.1f} km left", flush=True)
    print(f"japan: {len(line_of)} ways on named lines, {sum(length[w] for w in line_of):.0f} km of track; "
          f"{sum(length[w] for w in unnamed):.0f} km of running track left without a line", flush=True)

    tracks = defaultdict(list)                     # (layer, company, name) -> ways
    for wid, key in line_of.items():
        tracks[key].append(wid)

    # A short piece named slightly differently from the line it bridges (千駄ケ谷) is folded into
    # that parent, not drawn on its own. See merge_short_connectors for the strict topology rule.
    merge_short_connectors(tracks, ways, length, line_of=line_of)
    # Lines that share their track with another (SHARED_LINE) are on it too. That track is drawn
    # for them once the other lines are drawn and joined up, which it then changes in nothing.
    route = {rid: (t, members) for rid, t, members in ex["relations"]}
    shared_en, shared_track, shared_ways = {}, {}, {}
    for name, rule in SHARED_LINE.items():
        on = [k for o in rule["on"] for k in tracks if k[0] == "rail" and k[2] == o]
        if not on:
            continue
        key = next((k for k in tracks if k[0] == "rail" and k[2] == name), ("rail", on[0][1], name))
        t, members = route.get(rule["relation"], ({}, []))
        member = {ref for kind, ref in members if kind == "w"}
        mine = {ref for ref in member if line_of.get(ref) in on}
        # and the relation's track on any other line that is no Shinkansen, where it joins that
        other = {ref for ref in member if ref in line_of and line_of[ref] not in on and line_of[ref] != key
                 and line_of[ref][0] == "rail" and "新幹線" not in line_of[ref][2]}
        reach = {c for w in mine | {w for w in tracks.get(key, []) if w in member} for c in ways[w][1]}
        while True:
            more = {w for w in other - mine if any(c in reach for c in ways[w][1])}
            if not more:
                break
            mine |= more
            reach.update(c for w in more for c in ways[w][1])
        mine = sorted(mine)
        if name in MINI:                                          # the line is its relation's track and what joins it
            kept = {w for w in tracks.get(key, []) if w in member}
            nodes = {c for w in kept | set(mine) for c in ways[w][1]}
            rest = [w for w in tracks.get(key, []) if w not in kept]
            while True:
                more = [w for w in rest if ways[w][1][0] in nodes or ways[w][1][-1] in nodes]
                if not more:
                    break
                kept.update(more)
                nodes.update(c for w in more for c in ways[w][1])
                rest = [w for w in rest if w not in kept]
            stray = rest
            tracks[key] = [w for w in tracks.get(key, []) if w in kept]
            tracks[on[0]] = list(tracks[on[0]]) + stray
            for w in stray:
                line_of[w] = on[0]
            if stray:
                print(f"japan: {sum(length[w] for w in stray):.1f} km of track named for {name} outside its relation go to {on[0][2]}", flush=True)
        shared_ways[key] = mine                                   # the other line keeps its drawing as it is
        shared_track[name] = sum(length[w] for w in mine)
        if t.get("name:en"):
            shared_en[name] = t["name:en"] if name.startswith("JR") else re.sub(r"^JR\s+", "", t["name:en"])
        print(f"japan: {name} drawn on {shared_track[name]:.1f} km of track it shares with {'、'.join(rule['on'])} (relation {rule['relation']})", flush=True)

    # ---------------------------------------------------------------- the colour of a line
    # The tramways came to the map after everything else, and nothing of theirs recolours what
    # was there: a line that is not a tramway is voted on as it was, by the routes that are not
    # tram routes and over the track that is not tram track (a tram route runs on from
    # 広島電鉄本線 over the light rail of 宮島線). A tramway is voted on by every route over all its track.
    tramway = lambda w: ways[w][0].get("railway") == "tram"
    tram_line = {key for key, wids in tracks.items() if key[0] == "metro" and 2 * sum(length[w] for w in wids if tramway(w)) > sum(length[w] for w in wids)}
    services = defaultdict(set)                    # (name without its direction, colour, kind of relation, a tram route?) -> ways on a line here
    for rid, t, members in ex["relations"]:
        col = colour_of(t.get("colour"))
        if t.get("type") != "route" or not col:
            continue
        name = key_of(re.sub(r"\s*[（(\[].*?[)）\]]", "", t.get("name") or ""))
        services[(name, col, t.get("route") == "railway", t.get("route") == "tram")].update(ref for kind, ref in members if kind == "w" and ref in line_of)
    votes = defaultdict(Counter)                   # line -> colour -> score
    for (name, col, infrastructure, tram_route), ws in services.items():
        for trams in (False, True):                # first the lines that are not tramways, then the tramways
            if tram_route and not trams:
                continue
            mine = [w for w in ws if trams or not tramway(w)]
            total = sum(length[w] for w in mine)
            on = Counter()
            for w in mine:
                if (line_of[w] in tram_line) == trams:
                    on[line_of[w]] += length[w]
            for key, part in on.items():
                cover = part / sum(length[w] for w in tracks[key] if trams or not tramway(w))
                mostly = part / total
                if "新幹線" in key[2] or cover < 0.25 or mostly < 0.25:
                    continue                        # passes through, or runs mostly somewhere else; the Shinkansen go by design speed
                bare_name = key_of(re.sub(r"^JR", "", key[2]))
                score = cover * mostly + (0.6 if bare_name in name else 0) + (0.2 if infrastructure else 0)
                if EXPRESS.search(name):
                    score -= 0.6
                if cover < 0.5 or mostly < 0.5:
                    score -= 1.0                    # a weak match: only where nothing better says what colour the line has
                votes[key][col] = max(votes[key].get(col, -9), score)
    line_colour = {}
    for key in tracks:
        if key[2] in KNOWN_COLOUR:
            line_colour[key] = KNOWN_COLOUR[key[2]]
        elif votes[key] and max(votes[key].values()) > (-0.95 if key[0] == "metro" else 0):
            line_colour[key] = readable_on_dark(max(votes[key].items(), key=lambda kv: (kv[1], kv[0]))[0])
    track_km = sum(length[w] for key, ws in tracks.items() if key[0] == "rail" for w in ws)
    own = sum(length[w] for key, ws in tracks.items() if key[0] == "rail" and key in line_colour for w in ws)
    print(f"japan rail: {sum(1 for k in tracks if k[0] == 'rail')} lines; a colour of their own on {own / track_km:.0%} of the track", flush=True)

    # ---------------------------------------------------------------- railways: each line drawn once
    rail_keys = [k for k in tracks if k[0] == "rail"]
    once = {}
    for key in rail_keys:
        runs = runs_of([ways[w][1] for w in tracks[key]])
        once[key] = [runs, one_track(runs, keep=0.05, apart=0.004, apart_min=0.01)]
    closed = join_up(list(once.values()))
    shared_drawn = 0.0                                 # km drawn for lines on another's track (SHARED_LINE)
    for key, extra in shared_ways.items():
        if key not in once:
            rail_keys.append(key)
            once[key] = [[], []]
        tracks[key] = list(tracks.get(key, [])) + extra
        drawn = one_track(runs_of([ways[w][1] for w in extra]), keep=0.05, apart=0.004, apart_min=0.01)
        once[key][1] = list(once[key][1]) + drawn
        shared_drawn += sum(km(list(g.coords)) for g in drawn)
    print(f"japan rail drawn once: {sum(g.length for r, _ in once.values() for g in r) * 100:.0f} -> "
          f"{sum(g.length for _, d in once.values() for g in d) * 100:.0f} (degrees x 100); gaps closed at junctions: {closed}", flush=True)
    rail_feats, lines_json, plain_km = [], {}, Counter()
    for key in rail_keys:
        _, firm, name = key
        drawn = once[key][1]
        if not drawn:
            continue
        tags = [ways[w][0] for w in tracks[key]]
        total = sum(length[w] for w in tracks[key])
        for w, t in zip(tracks[key], tags):
            names.add(name, {**t, "name:en": english_part(t.get("name:en"), name)}, length[w])
        # Japan kind is operator + name (jk), never speed. Shinkansen identity is the route name.
        # 山形/秋田 run on conventional lines converted to standard gauge: Shinkansen class, no design speed (MINI).
        jk = jkind(name, firm)
        # c is only the internal line width (main/branch); the UI never shows a speed class for Japan.
        cls = "main" if sum(length[w] for w, t in zip(tracks[key], tags) if t.get("usage") == "main") >= 0.5 * total else "branch"
        shown = name
        simp = rounded(stitch(runs_of([list(g.coords) for g in drawn])), TOL["rail"], CURVE["rail"], places=5)
        if not simp:
            continue
        props = {"c": cls, "n": shown, "g": "jp", "jk": jk}
        if name in MINI:
            props["mini"] = 1
        if firm:
            props["o"] = firm
        how = colouring(name, jk, line_colour.get(key))
        props.update(how)
        if not how:
            plain_km[jk] += total
        for seg_co in simp:
            rail_feats.append({"type": "Feature", "properties": dict(props), "geometry": geometry([seg_co])})
        row = lines_json.setdefault(shown, {"n": shown, "g": "jp", "jk": jk, **({"mini": 1} if name in MINI else {}), "bbox": bbox_of(simp), "tk": 0, "c": cls, "_firms": Counter()})
        box = bbox_of(simp)
        row["bbox"] = [min(row["bbox"][0], box[0]), min(row["bbox"][1], box[1]), max(row["bbox"][2], box[2]), max(row["bbox"][3], box[3])]
        row["tk"] += total
        row["_firms"][firm] += total
        if "lc" in how and (not row.get("lc") or row["_firms"].most_common(1)[0][0] == firm):
            row["lc"] = how["lc"]
        if "d" in how:
            row.update(how)
    # The lines of one corridor each lie on their own track, a few metres apart: drawn as they are,
    # they cover each other at any scale that shows a city. Each gets its place in the corridor
    # (property off), which the map turns into a shift to the side that fades out as one zooms in
    # to where the tracks themselves are apart on screen.
    whole = len(rail_feats)
    rail_feats = side_by_side(rail_feats, skip=lambda props: False, slots_of=abreast, min_run=0.006)
    print(f"japan rail side by side: {whole} features written as {len(rail_feats)}, "
          f"{sum(1 for f in rail_feats if f['properties'].get('off'))} of them moved to a side", flush=True)
    for name, english in shared_en.items():         # a line drawn on shared track: its relation's English name
        names.en[name] = Counter({english: 1.0})
    for row in lines_json.values():
        row.pop("_sec_seen", None)
        firm = row.pop("_firms").most_common(1)[0][0]
        if firm:
            row["o"] = firm
        row["tk"] = round(row["tk"])
        names.line(row)
    for f in rail_feats:
        names.line(f["properties"])

    # ---------------------------------------------------------------- metros and tramways
    metro_keys = [k for k in tracks if k[0] == "metro"]
    is_tram = {key: key in tram_line for key in metro_keys}
    drawn_metro = {}
    for key in metro_keys:
        kinds = Counter(ways[w][0].get("railway") for w in tracks[key])
        light = kinds["light_rail"] + kinds["tram"] > kinds["subway"] + kinds["monorail"]
        # Metro infrastructure bucket: underground / monorail / light-rail(tram). AGT can't be told
        # from the tag alone (no operator on the metro feature), so light_rail stays the tram bucket.
        runs = runs_of([ways[w][1] for w in tracks[key]])
        drawn = stitch(one_track(runs, **(dict(gap=TRAM_GAP) if is_tram[key] else {})), bends=True)
        tol = TOL["light" if light else "metro"]
        simp = rounded(drawn, tol, (6, 6, 0.00004) if light else (5, 4, 0.0003), adaptive=True)
        if simp:
            drawn_metro[key] = (simp, metro_jk(kinds), sum(km(co) for co in simp))
            for w in tracks[key]:
                names.add(key[2], ways[w][0], length[w])
    # A line of less than METRO_MIN_KM is a ride and is left out, but not a short line of a
    # tramway system that is longer than that as a whole.
    system = tram_systems({key: tracks[key] for key in drawn_metro if is_tram[key]}, ways,
                          [wid for wid, (t, co) in ways.items() if t.get("railway") == "tram"])
    metro_feats, tram_feats, metro_rows = [], [], []
    for key in sorted(drawn_metro, key=lambda k: is_tram[k]):          # the tramways after the rest, which keep their order
        _, firm, name = key
        simp, jk, line_km = drawn_metro[key]
        if max(line_km, sum(drawn_metro[k][2] for k in system.get(key, ()))) < METRO_MIN_KM:
            continue
        col = line_colour.get(key) or "#5cc8ff"
        mid = LineString(max(simp, key=len)).interpolate(0.5, normalized=True)
        city = next((c[0] for c in CITIES if math.hypot((c[1] - mid.x) * math.cos(math.radians(mid.y)), c[2] - mid.y) < c[3]), "日本其他")
        (tram_feats if is_tram[key] else metro_feats).append({"type": "Feature", "properties": {"r": "JP", "g": "jp", "col": col, "n": name, "ct": city, "jk": jk}, "geometry": geometry(simp)})
        metro_rows.append((city, {"n": name, "col": col, "jk": jk, "km": round(line_km), "bbox": bbox_of(simp)}))
    # A tramway keeps company with tramways only: where one runs in the street over a subway
    # (札幌市電 over 南北線, 都電 over 副都心線) neither is moved aside for the other, as in China.
    metro_feats = side_by_side(metro_feats) + side_by_side(tram_feats)
    for f in metro_feats:
        names.line(f["properties"])
    cities = {}
    for city, row in metro_rows:
        c = cities.setdefault(city, {"n": city, "km": 0, "bbox": list(row["bbox"]), "lines": []})
        c["km"] += row["km"]
        c["bbox"] = [min(c["bbox"][0], row["bbox"][0]), min(c["bbox"][1], row["bbox"][1]), max(c["bbox"][2], row["bbox"][2]), max(c["bbox"][3], row["bbox"][3])]
        c["lines"].append(row)
    known = city_names("jp")
    for c in cities.values():
        c["lines"].sort(key=lambda r: r["n"])
        for row in c["lines"]:
            names.line(row)
        name_city(c, known, "jp")

    # ---------------------------------------------------------------- stations
    seen, stations = set(), []
    for t, lon, lat in ex["stations"]:
        name = unicodedata.normalize("NFKC", t.get("name") or "").strip()
        kind = t.get("station") or ("subway" if t.get("subway") == "yes" else "light_rail" if t.get("light_rail") == "yes" else "")
        if not name or kind in ("funicular", "preserved", "miniature"):
            continue
        if t.get("railway") == "tram_stop":
            continue                                                       # after the stations, below
        metro = kind in METRO_RAIL
        spot = (name, metro, round(lon * 300), round(lat * 300))          # one dot for the platforms of one station
        if spot in seen:
            continue
        seen.add(spot)
        props = {"n": name, "g": "jp"}
        if metro:
            props["m"] = 1
        names.station(props, t, (lon, lat))
        stations.append({"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}})
    # The tram stops, after the stations: a stop that is on the map as a station already (三ノ輪橋 is
    # mapped as both) gets no second dot.
    here = {(spot[0], spot[2], spot[3]) for spot in seen}
    for t, lon, lat in ex["stations"]:
        name = unicodedata.normalize("NFKC", t.get("name") or "").strip()
        spot = (name, round(lon * 300), round(lat * 300))
        if t.get("railway") != "tram_stop" or not name or spot in here:
            continue
        here.add(spot)
        props = names.station({"n": name, "g": "jp", "m": 1, "t": 1}, t, (lon, lat))        # t: a tram stop, hidden with the trams
        stations.append({"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}})
    every = len(stations)
    lines_of = lambda feats: [co for f in feats for co in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]])]
    stations = with_a_line(stations, lines_of(rail_feats), lines_of(metro_feats))
    print(f"japan stations: {len(stations)} of {every} have a drawn line passing them; the other {every - len(stations)} are not drawn", flush=True)

    # ---------------------------------------------------------------- write
    def write(name, obj):
        p = OUT / name
        p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        print(f"{name}: {p.stat().st_size / 1e6:.2f} MB", flush=True)
    write("jp_rail.geojson", {"type": "FeatureCollection", "features": rail_feats})
    write("jp_metro.geojson", {"type": "FeatureCollection", "features": metro_feats})
    write("jp_stations.geojson", {"type": "FeatureCollection", "features": stations})
    build_feats = being_built(ways, "jp", plain_name, build_fast=lambda name: "新幹線" in name, names=names)
    write("jp_build.geojson", {"type": "FeatureCollection", "features": build_feats})
    write("jp_lines.json", sorted(lines_json.values(), key=lambda r: -r["tk"]))
    write("jp_metro_cities.json", sorted(cities.values(), key=lambda c: -c["km"]))
    print("japan rail without a colour of its own, track km by kind:", {k: round(v) for k, v in plain_km.most_common()}, flush=True)
    def feat_km(f):
        return sum(km(co) for co in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]]))
    fast_km = sum(feat_km(f) for f in rail_feats if f["properties"].get("jk") == "shinkansen" and not f["properties"].get("mini"))      # the 250 band
    class_km = sum(feat_km(f) for f in rail_feats if f["properties"].get("jk") == "shinkansen")          # the Shinkansen class, the mini-Shinkansen with it
    # A line drawn on another's track (SHARED_LINE) adds nothing to the country's length there.
    all_km = sum(feat_km(f) for f in rail_feats) - shared_drawn
    write("jp_facts.json", {"km": round(all_km), "fast_km": round(fast_km),
                            "bands": sorted({f["properties"]["c"] for f in rail_feats if "d" in f["properties"] and not f["properties"].get("mini")}),
                            "shinkansen_km": round(class_km)})
    # Japan taxonomy audit: per-bucket line + km counts. Operator-less fragments land in "unknown"
    # on purpose (not noise-deleted, not dumped into private); see data/jp_taxonomy_audit.json.
    rail_keys = ("shinkansen", "jr", "private_big", "third_sector", "private_local", "unknown")
    jk_lines = Counter(r["jk"] for r in lines_json.values())
    jk_km = defaultdict(float)
    for r in lines_json.values():
        jk_km[r["jk"]] += r["tk"] - shared_track.get(r["n"], 0)      # shared track is counted with the line OSM names it for
    metro_feat = Counter(f["properties"].get("jk") for f in metro_feats)
    metro_line = Counter(r["jk"] for _, r in metro_rows)
    rail_line_kinds = defaultdict(set)
    for f in rail_feats:
        rail_line_kinds[f["properties"].get("n")].add(f["properties"].get("jk"))
    metro_line_kinds = defaultdict(set)
    for city, row in metro_rows:
        metro_line_kinds[(city, row["n"])].add(row.get("jk"))
    audit = {"rail": {k: {"lines": jk_lines.get(k, 0), "km": round(jk_km.get(k, 0))} for k in rail_keys},
             "metro": {k: {"features": metro_feat.get(k, 0), "lines": metro_line.get(k, 0)} for k in ("subway", "urban")},
             "metro_lines_total": len(metro_rows),
             "unclassified_lines": {
                 "rail": sum(1 for kinds in rail_line_kinds.values() if not kinds or not kinds <= set(rail_keys)),
                 "metro": sum(1 for kinds in metro_line_kinds.values() if not kinds or not kinds <= {"subway", "urban"}),
             },
             "conflicting_lines": {
                 "rail": sorted(name for name, kinds in rail_line_kinds.items() if len(kinds) > 1),
                 "metro": sorted(f"{city} / {name}" for (city, name), kinds in metro_line_kinds.items() if len(kinds) > 1),
             }}
    write("jp_taxonomy_audit.json", audit)
    print(f"jk buckets: { {k: jk_lines.get(k, 0) for k in rail_keys} } metro: {audit['metro']}", flush=True)
    print(f"japan: {len(lines_json)} railway lines, {all_km:.0f} km drawn ({fast_km:.0f} km Shinkansen); "
          f"{len(metro_rows)} metro lines in {len(cities)} cities, {sum(r['km'] for _, r in metro_rows)} km; {len(stations)} stations")
    write_yards(ex, "jp")



if __name__ == "__main__":
    main()
