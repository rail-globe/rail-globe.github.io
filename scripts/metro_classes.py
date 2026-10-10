"""The class of an urban line of China (property jk, as the lines abroad have it), and how a tram
line is named.

Three classes, the two the countries abroad have and the suburban trains:
  subway    地铁: metro lines, and with them monorail and maglev lines, which carry a metro's loads
            on a metro's own right of way (重庆 2、3 号线, 芜湖 1、2 号线, 上海磁浮, 长沙磁浮, 北京 S1 线);
  urban     轻轨: a line most of whose track is light rail or tram (长春 3、4、8 号线, 香港輕鐵, 澳門輕軌,
            the tram systems), and the small guided people-movers named in PEOPLE_MOVER;
  suburban  市郊 / 城际: trains on railway track, not a metro's: the suburban trains of the railway
            bureaus (北京市郊铁路S2线, 金山铁路, 青平快线; drawn beside the railway they run on, k = "s"),
            and the intercity lines a metro company runs on railway track (广清城际线, 西户线, moved
            here from the railways, k = "m") (the owner's page, 2026-10-10).
The class is read off the track: OSM tags track as subway, light_rail, tram or monorail, and a
line is of the kind most of its track is; a line on railway track is suburban.
"""
import re
from collections import Counter

LIGHT_TRACK = {"light_rail", "tram"}
# People-movers of the 云巴 kind are light rail whatever their track is tagged as (the owner's
# decision, 2026-10-09): small driverless rubber-tyred cars on a narrow guideway. Tags cannot tell
# one from a monorail proper, so they are known by name: 云巴 is the product's own name (BYD
# SkyShuttle) and every line of the kind carries it. The five on the map, each checked on
# zh.wikipedia.org (2026-10-09: all five are described there as 云巴 lines, rubber-tyred and
# guided, and as open), with what OSM tags its track as:
#   坪山云巴1号线 (深圳)     /wiki/坪山云巴1号线   open since 2022-12-28   light_rail
#   璧山云巴1号线 (重庆)     /wiki/重庆云巴        open since 2021-04-16   light_rail
#   西安高新云巴线           /wiki/西安云巴        open since 2024-08-12   light_rail
#   济南轨道交通云巴线       /wiki/济南云巴1号线   open since 2025-12-06   light_rail
#   大王山云巴 (长沙)        /wiki/大王山旅游线    fares since 2023-05-15  monorail
# Only the last needs the name: the other four are light rail by their track already.
PEOPLE_MOVER = re.compile(r"云巴")
# A tram line named after the bus company that runs it (大连公交201路) is shown as a tram line.
TRAM_OPERATOR = {"大连公交": "大连有轨电车"}
TRAM_WORD = re.compile(r"有轨|电车|電車")
SYSTEM_CITY = re.compile(r"(.{2,3}?)市?(?:地铁|轨道交通|现代有轨电车|有轨电车)")


def light(track_km):
    """Is most of this track light rail or tram? track_km: {railway tag: km}."""
    on = sum(v for k, v in track_km.items() if k in LIGHT_TRACK)
    return on > sum(track_km.values()) - on


# k of the lines that are trains on railway track: "s", a railway bureau's suburban train,
# "m", an intercity line a metro company runs (scripts/process_osm.py)
ON_RAILWAY = {"s", "m"}


def kind_of(name, track_km, k=None):
    """The class of a line: its name, the km of its track by railway tag, and k where it is a
    train on railway track."""
    if k in ON_RAILWAY:
        return "suburban"
    return "urban" if PEOPLE_MOVER.search(name or "") or light(track_km) else "subway"


def is_tram(name, track_km):
    """Is this a tram line? Most of its track is tram track, or its name says so: several of the
    newer systems are mapped as light_rail (广州黄埔, 南京河西, 淮安), and they are trams all the same."""
    return track_km.get("tram", 0) > sum(track_km.values()) / 2 or bool(TRAM_WORD.search(name or ""))


def numbered(ref):
    """A route's number as the end of a line's name: T1 -> T1线, 1 -> 1号线, and 54 -> 54路, as
    tram routes are numbered where they are numbered like the buses."""
    if not ref:
        return ""
    if ref.isdigit():
        return ref + ("路" if len(ref) > 1 else "号线")
    return ref if ref.endswith(("线", "路")) else ref + "线"


def tram_key(name):
    """What two spellings of one tram line have in common: 嘉兴有轨电车T1线 is 嘉兴有轨电车1号线."""
    return re.sub(r"T?(\d+)号?线$", r"\1", name)


def tram_name(name, ref="", track_km=None, network="", operator=""):
    """The name of a tram line. name: what the route relation gives, read as a metro line's name
    is ("" where it gives none in Chinese: 长春's is "Line 54"); ref: the route's number;
    track_km: {name on the track: km} of the route's track; network, operator: the route's.

    - A route with no name of its own is named after its system and its number: the system is its
      network where that is a tram system (深圳有轨电车 + T1), otherwise the name its track carries
      (长春有轨电车 + 54 -> 长春有轨电车54路). A track that already names the line needs no number
      (红河有轨电车一号线).
    - A system known by a district takes its city in front where the route's operator or network
      says it: 高新有轨电车1号线 of 苏州高新有轨电车 is 苏州高新有轨电车1号线, 黄埔有轨电车1号线 of the
      network 广州地铁 is 广州黄埔有轨电车1号线, 三亚轨道交通's "有轨电车T1线" is 三亚有轨电车T1线.
    """
    network, operator = network or "", operator or ""
    if not name and TRAM_WORD.search(network):
        name = network + numbered(ref)
    if not name:
        named = Counter({k: v for k, v in (track_km or {}).items() if k})
        name = named.most_common(1)[0][0] if named else ""
        if name and not re.search(r"\d|[一二三四五六七八九十]号?线$", name):
            name += numbered(ref)
    for firm, system in TRAM_OPERATOR.items():
        if name.startswith(firm):
            name = system + name[len(firm):]
    for source in (operator, network):         # 苏州高新有轨电车 + 高新有轨电车1号线
        k = next((k for k in range(min(len(source), len(name)), 3, -1) if source.endswith(name[:k])), 0)
        if k and len(source) > k:
            return source + name[k:]
    city = next((c.group(1) for c in map(SYSTEM_CITY.match, (network, operator)) if c), "")
    if name and city and not name.startswith(city):
        name = city + name
    return name
