"""Japan: railways and metros from data/raw/extract_jp.pkl, written as layers of their own.

    python3 scripts/extract_osm.py jp     japan-latest.osm.pbf -> data/raw/extract_jp.pkl
    python3 scripts/process_jp.py         -> data/jp_rail.geojson, jp_metro.geojson, jp_stations.geojson,
                                             jp_lines.json, jp_metro_cities.json

The page adds these to the layers it already has (site.json: {"jp": true}), so the features carry
the same properties as the Chinese ones: c (class), n (line), o (operator), plus lc, the line's
own colour. Nothing here touches the Chinese data or scripts/process_osm.py.

How Japan draws its railways, and so how they are coloured here (user, 2026-10-08):
- a line has a colour of its own (ラインカラー, set per line or service and used on route maps and
  station signs): a line that has one is drawn in it;
- a line without one is drawn in one neutral colour. It does not take the colour of its company
  (the user dropped company colours the same day, after seeing whole regions in one colour);
- the Shinkansen follow the same rule. The source gives 東海道, 山陽 and the JR West part of 北陸
  blue, 東北, 上越 and the JR East part of 北陸 green, 山形 orange and 秋田 pink, and says that
  九州, 西九州 and 北海道 have no line colour (特にラインカラーは定められていない): those are neutral.
Source for the conventions: https://ja.wikipedia.org/wiki/日本の鉄道ラインカラー一覧 (read 2026-10-08).

A line is the track that carries its name in OSM (99% of running track is named, 98% has an
operator), drawn once (scripts/single_track.py). Its colour comes from the route relations that
run on it: one that covers most of the line and lies mostly on that line (a through service or a
long-distance express does neither).
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

from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge

sys.path.insert(0, str(Path(__file__).resolve().parent))
from side_by_side import abreast, side_by_side
from single_track import curved, join_up, one_track, smooth, stitch

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data"
SKIP_USAGE = {"industrial", "military", "tourism", "test", "freight", "yard"}
METRO_RAIL = {"subway", "light_rail", "monorail"}
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
# A line's name mistyped on some of its track.
NAME_TYPOS = {"R久留里線": "久留里線"}
# The line colours of the Shinkansen, as the source in the module docstring gives them, in shades
# that read on dark imagery: 東海道・山陽・北陸（西日本管轄区間）：青, 東北・上越・北陸（東日本管轄区間）：緑,
# 山形新幹線：橙, 秋田新幹線：桃. 北陸 changes colour where it changes company, so it is listed by
# company. 九州, 西九州 and 北海道 have no line colour there and are left out on purpose.
BLUE, GREEN = "#3d9bff", "#2fbf5f"
KNOWN_COLOUR = {"東海道新幹線": BLUE, "山陽新幹線": BLUE, ("北陸新幹線", "JR西日本"): BLUE,
                "東北新幹線": GREEN, "上越新幹線": GREEN, ("北陸新幹線", "JR東日本"): GREEN,
                "山形新幹線": "#ff9a3d", "秋田新幹線": "#ff8fb3"}
METRO_MIN_KM = 2.0         # shorter "lines" on metro-type track are rides in parks
OTHER = "#c3ccd6"          # a line with no colour of its own
# Japan rail kind (jk): a Japan-only taxonomy by operator + infrastructure, NOT China's 高铁/普速/地铁
# and NOT any speed design. Authoritative lists in data/jp_operator_classification_list.json:
#   shinkansen    route name is a Shinkansen (山形/秋田 excluded, they run on 1066mm conventional track)
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
          ("北九州", 130.875, 33.883, 0.25), ("东京", 139.767, 35.681, 0.9), ("大阪", 135.502, 34.694, 0.7), ("名古屋", 136.907, 35.170, 0.6),
          ("札幌", 141.351, 43.062, 0.6), ("仙台", 140.882, 38.260, 0.6), ("福冈", 130.401, 33.590, 0.5), ("广岛", 132.459, 34.396, 0.5),
          ("那霸", 127.681, 26.212, 0.5), ("福井", 136.223, 36.062, 0.4), ("富山", 137.213, 36.701, 0.4)]


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


def known_colour(name, firm):
    """The colour the source gives a line by name, or None: by company where the line changes colour with it."""
    return KNOWN_COLOUR.get((name, firm)) or KNOWN_COLOUR.get(name)


def jkind(name, firm):
    """Japan-only rail bucket for a line (operator-based, authoritative lists):
    shinkansen / jr / private_big / third_sector / private_local / unknown.
    The line's `firm` is its grouped company (operator-less ways already merged into a same-named
    line). No operator -> unknown (counted in the audit, never dumped, never hidden)."""
    sh = "新幹線" in (name or "") and name not in {"山形新幹線", "秋田新幹線"}
    if sh:
        return "shinkansen"
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
    return "subway" if kinds["subway"] >= kinds["monorail"] + kinds["light_rail"] else "urban"


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


def main():
    # written locally by scripts/extract_osm.py, so loading it is safe here
    ex = pickle.load(open(RAW / "extract_jp.pkl", "rb"))
    ways = {wid: (t, co) for wid, t, co in ex["ways"]}
    length = {wid: km(co) for wid, (t, co) in ways.items()}

    # ---------------------------------------------------------------- which line every track belongs to
    line_of = {}                                   # way -> (layer, company, line name)
    unnamed, bare = [], defaultdict(set)           # bare: a line's name without its company -> the lines so named
    says_jr = set()                                # track whose own name begins with JR
    for wid, (t, co) in ways.items():
        kind = t.get("railway")
        if t.get("service") or t.get("usage") in SKIP_USAGE or kind not in METRO_RAIL | {"rail"}:
            continue
        firm, short = company(t.get("operator"))
        metro = kind in METRO_RAIL
        name = plain_name(t.get("name"), None if metro else firm)
        name = NAME_TYPOS.get(name, name)
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
    at = defaultdict(set)
    for wid, key in line_of.items():
        co = ways[wid][1]
        at[co[0]].add(key)
        at[co[-1]].add(key)
    for _ in range(6):
        left = []
        for wid in unnamed:
            co = ways[wid][1]
            both = at[co[0]] & at[co[-1]]
            pick = next(iter(both)) if len(both) == 1 else None
            if pick is None and len(at[co[0]] | at[co[-1]]) == 1 and at[co[0]] and at[co[-1]]:
                pick = next(iter(at[co[0]]))
            if pick is None:
                left.append(wid)
                continue
            line_of[wid] = pick
            at[co[0]].add(pick)
            at[co[-1]].add(pick)
        if len(left) == len(unnamed):
            break
        unnamed = left
    print(f"japan: {len(line_of)} ways on named lines, {sum(length[w] for w in line_of):.0f} km of track; "
          f"{sum(length[w] for w in unnamed):.0f} km of running track left without a line", flush=True)

    tracks = defaultdict(list)                     # (layer, company, name) -> ways
    for wid, key in line_of.items():
        tracks[key].append(wid)

    # A short piece named slightly differently from the line it bridges (千駄ケ谷) is folded into
    # that parent, not drawn on its own. See merge_short_connectors for the strict topology rule.
    merge_short_connectors(tracks, ways, length, line_of=line_of)

    # ---------------------------------------------------------------- the colour of a line
    services = defaultdict(set)                    # (name without its direction, colour, kind of relation) -> ways on a line here
    for rid, t, members in ex["relations"]:
        col = colour_of(t.get("colour"))
        if t.get("type") != "route" or not col:
            continue
        name = key_of(re.sub(r"\s*[（(\[].*?[)）\]]", "", t.get("name") or ""))
        services[(name, col, t.get("route") == "railway")].update(ref for kind, ref in members if kind == "w" and ref in line_of)
    votes = defaultdict(Counter)                   # line -> colour -> score
    for (name, col, infrastructure), ws in services.items():
        total = sum(length[w] for w in ws)
        on = Counter()
        for w in ws:
            on[line_of[w]] += length[w]
        for key, part in on.items():
            cover = part / sum(length[w] for w in tracks[key])
            mostly = part / total
            if "新幹線" in key[2] or cover < 0.25 or mostly < 0.25:
                continue                            # passes through, or runs mostly somewhere else; the Shinkansen go by the list above
            bare_name = key_of(re.sub(r"^JR", "", key[2]))
            score = cover * mostly + (0.6 if bare_name in name else 0) + (0.2 if infrastructure else 0)
            if EXPRESS.search(name):
                score -= 0.6
            if cover < 0.5 or mostly < 0.5:
                score -= 1.0                        # a weak match: only where nothing better says what colour the line has
            votes[key][col] = max(votes[key].get(col, -9), score)
    line_colour = {}
    for key in tracks:
        if known_colour(key[2], key[1]):
            line_colour[key] = known_colour(key[2], key[1])
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
        # Japan kind is operator + name (jk), never speed. Shinkansen identity is the route name.
        # 山形/秋田 run on converted 1066mm track: explicit exceptions, not a speed guess.
        jk = jkind(name, firm)
        # c is only the internal line width (main/branch); the UI never shows a speed class for Japan.
        cls = "main" if sum(length[w] for w, t in zip(tracks[key], tags) if t.get("usage") == "main") >= 0.5 * total else "branch"
        shown = name
        simp = rounded(stitch(runs_of([list(g.coords) for g in drawn])), TOL["rail"], CURVE["rail"], places=5)
        if not simp:
            continue
        props = {"c": cls, "n": shown, "g": "jp", "jk": jk}
        if firm:
            props["o"] = firm
        # Japan's only colour: the line's own colour, else neutral OTHER. Never the company's.
        col = line_colour.get(key) or OTHER
        if key not in line_colour:
            plain_km[jk] += total
        if col:
            props["lc"] = col
        for seg_co in simp:
            rail_feats.append({"type": "Feature", "properties": dict(props), "geometry": geometry([seg_co])})
        row = lines_json.setdefault(shown, {"n": shown, "g": "jp", "jk": jk, "bbox": bbox_of(simp), "tk": 0, "c": cls, "_firms": Counter()})
        box = bbox_of(simp)
        row["bbox"] = [min(row["bbox"][0], box[0]), min(row["bbox"][1], box[1]), max(row["bbox"][2], box[2]), max(row["bbox"][3], box[3])]
        row["tk"] += total
        row["_firms"][firm] += total
        if col and (not row.get("lc") or row["_firms"].most_common(1)[0][0] == firm):
            row["lc"] = col
    # The lines of one corridor each lie on their own track, a few metres apart: drawn as they are,
    # they cover each other at any scale that shows a city. Each gets its place in the corridor
    # (property off), which the map turns into a shift to the side that fades out as one zooms in
    # to where the tracks themselves are apart on screen.
    whole = len(rail_feats)
    rail_feats = side_by_side(rail_feats, skip=lambda props: False, slots_of=abreast, min_run=0.006)
    print(f"japan rail side by side: {whole} features written as {len(rail_feats)}, "
          f"{sum(1 for f in rail_feats if f['properties'].get('off'))} of them moved to a side", flush=True)
    for row in lines_json.values():
        row.pop("_sec_seen", None)
        firm = row.pop("_firms").most_common(1)[0][0]
        if firm:
            row["o"] = firm
        row["tk"] = round(row["tk"])

    # ---------------------------------------------------------------- metros
    metro_feats, metro_rows = [], []
    for key in [k for k in tracks if k[0] == "metro"]:
        _, firm, name = key
        kinds = Counter(ways[w][0].get("railway") for w in tracks[key])
        light = kinds["light_rail"] > kinds["subway"] + kinds["monorail"]
        # Metro infrastructure bucket: underground / monorail / light-rail(tram). AGT can't be told
        # from the tag alone (no operator on the metro feature), so light_rail stays the tram bucket.
        jk = metro_jk(kinds)
        runs = runs_of([ways[w][1] for w in tracks[key]])
        drawn = stitch(one_track(runs), bends=True)
        tol = TOL["light" if light else "metro"]
        simp = rounded(drawn, tol, (6, 6, 0.00004) if light else (5, 4, 0.0003), adaptive=True)
        if not simp or sum(km(co) for co in simp) < METRO_MIN_KM:
            continue
        col = line_colour.get(key) or "#5cc8ff"
        mid = LineString(max(simp, key=len)).interpolate(0.5, normalized=True)
        city = next((c[0] for c in CITIES if math.hypot((c[1] - mid.x) * math.cos(math.radians(mid.y)), c[2] - mid.y) < c[3]), "日本其他")
        metro_feats.append({"type": "Feature", "properties": {"r": "JP", "g": "jp", "col": col, "n": name, "ct": city, "jk": jk}, "geometry": geometry(simp)})
        metro_rows.append((city, {"n": name, "col": col, "jk": jk, "km": round(sum(km(co) for co in simp)), "bbox": bbox_of(simp)}))
    metro_feats = side_by_side(metro_feats)
    cities = {}
    for city, row in metro_rows:
        c = cities.setdefault(city, {"n": city, "km": 0, "bbox": list(row["bbox"]), "lines": []})
        c["km"] += row["km"]
        c["bbox"] = [min(c["bbox"][0], row["bbox"][0]), min(c["bbox"][1], row["bbox"][1]), max(c["bbox"][2], row["bbox"][2]), max(c["bbox"][3], row["bbox"][3])]
        c["lines"].append(row)
    for c in cities.values():
        c["lines"].sort(key=lambda r: r["n"])

    # ---------------------------------------------------------------- stations
    seen, stations = set(), []
    for t, lon, lat in ex["stations"]:
        name = unicodedata.normalize("NFKC", t.get("name") or "").strip()
        kind = t.get("station") or ("subway" if t.get("subway") == "yes" else "light_rail" if t.get("light_rail") == "yes" else "")
        if not name or kind in ("funicular", "preserved", "miniature"):
            continue
        metro = kind in METRO_RAIL
        spot = (name, metro, round(lon * 300), round(lat * 300))          # one dot for the platforms of one station
        if spot in seen:
            continue
        seen.add(spot)
        props = {"n": name, "g": "jp"}
        if metro:
            props["m"] = 1
        stations.append({"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}})

    # ---------------------------------------------------------------- write
    def write(name, obj):
        p = OUT / name
        p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        print(f"{name}: {p.stat().st_size / 1e6:.2f} MB", flush=True)
    write("jp_rail.geojson", {"type": "FeatureCollection", "features": rail_feats})
    write("jp_metro.geojson", {"type": "FeatureCollection", "features": metro_feats})
    write("jp_stations.geojson", {"type": "FeatureCollection", "features": stations})
    write("jp_lines.json", sorted(lines_json.values(), key=lambda r: -r["tk"]))
    write("jp_metro_cities.json", sorted(cities.values(), key=lambda c: -c["km"]))
    print("japan rail without a colour of its own, track km by kind:", {k: round(v) for k, v in plain_km.most_common()}, flush=True)
    def feat_km(f):
        return sum(km(co) for co in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]]))
    fast_km = sum(feat_km(f) for f in rail_feats if f["properties"].get("jk") == "shinkansen")
    all_km = sum(feat_km(f) for f in rail_feats)
    write("jp_facts.json", {"km": round(all_km), "fast_km": round(fast_km)})
    # Japan taxonomy audit: per-bucket line + km counts. Operator-less fragments land in "unknown"
    # on purpose (not noise-deleted, not dumped into private); see data/jp_taxonomy_audit.json.
    rail_keys = ("shinkansen", "jr", "private_big", "third_sector", "private_local", "unknown")
    jk_lines = Counter(r["jk"] for r in lines_json.values())
    jk_km = defaultdict(float)
    for r in lines_json.values():
        jk_km[r["jk"]] += r["tk"]
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


if __name__ == "__main__":
    main()
