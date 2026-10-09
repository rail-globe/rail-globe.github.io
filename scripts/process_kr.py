"""South Korea: railways, metros and light rail, written as layers of their own by the shared
pipeline (scripts/country.py), which holds the colour rule and the method.

    python3 scripts/extract_osm.py kr     south-korea-latest.osm.pbf -> data/raw/extract_kr.pkl
    python3 scripts/process_kr.py         -> data/kr_rail.geojson, kr_metro.geojson, kr_build.geojson,
                                             kr_stations.geojson, kr_lines.json, kr_metro_cities.json,
                                             kr_facts.json, kr_yards.geojson, kr_depots.geojson

What is Korea's own is here: how its track is named, its classes of line and the speeds of its
fast lines. Names stay in Korean, as Japan's stay in Japanese.
"""
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from country import Country, run

# A tunnel or a bridge named for itself is part of the line on either side of it.
STRUCTURE = re.compile(r"(터널|교량|철교|대교|고가|고가교|교)$")
# The three dedicated high-speed lines (고속선): (design speed in km/h, only a top speed?, source).
# - 경부고속선: "a design speed of 350 km/h" and the infobox entry 350 km/h "design"
#   (https://en.wikipedia.org/wiki/Gyeongbu_high-speed_railway, read 2026-10-08). The Korean
#   Wikipedia infobox says 430 km/h (동대구~부산 350); the two disagree and 350 is the one that the
#   text of a page states, so 350 is used.
# - 수서평택고속선: infobox "설계 최고 속도 350km/h" (https://ko.wikipedia.org/wiki/수서평택고속선,
#   read 2026-10-08).
# - 호남고속선: no design speed that two sources agree on (the Korean infobox says 430 km/h, the
#   English page gives none). Its "Operating speed 305 km/h"
#   (https://en.wikipedia.org/wiki/Honam_high-speed_railway, read 2026-10-08) is used and marked as
#   a top speed, to be replaced when the design speed is confirmed.
HIGH_SPEED = {"경부고속선": (350, False, "https://en.wikipedia.org/wiki/Gyeongbu_high-speed_railway"),
              "수서평택고속선": (350, False, "https://ko.wikipedia.org/wiki/수서평택고속선"),
              "호남고속선": (305, True, "https://en.wikipedia.org/wiki/Honam_high-speed_railway")}
# Metro lines are listed by city: (name shown, lon, lat, reach in degrees). Incheon comes before
# Seoul and reaches less far, so that only its own lines are its own.
CITIES = [("仁川", 126.65, 37.47, 0.14), ("首尔", 126.98, 37.56, 0.9), ("釜山", 129.06, 35.17, 0.45), ("大邱", 128.60, 35.87, 0.4),
          ("大田", 127.38, 36.35, 0.3), ("光州", 126.85, 35.16, 0.3)]


def plain_name(name):
    """A track's name as the name of its line: without what is added in brackets, and for a
    structure on a line nothing at all."""
    name = re.sub(r"\s*[（(].*?[)）]", "", name or "")
    name = re.sub(r"\s+", " ", re.split(r"[;；]", name)[0]).strip()
    return "" if STRUCTURE.search(name) else name


def top_speed(tags_km):
    """The speed most of a line's fast track is signed for (km/h), or None."""
    by = Counter()
    for key, length in tags_km.items():
        t = dict(key)
        m = re.match(r"\d+", t.get("maxspeed") or "")
        if t.get("highspeed") == "yes" and m:
            by[int(m.group())] += length
    return by.most_common(1)[0][0] if by else None


def kind_of(name, tags_km):
    """A railway line's class: a dedicated high-speed line (고속선) by name, and its connecting
    lines by their speed (시흥연결선, signed for 305 km/h); a semi-high-speed line (준고속) where
    most of its track is tagged as high-speed for 200 km/h or more; else a main line or a branch."""
    if name in HIGH_SPEED:
        return "hs"
    total = sum(tags_km.values()) or 1
    share = lambda test: sum(v for k, v in tags_km.items() if test(dict(k))) / total
    if share(lambda t: t.get("highspeed") == "yes") >= 0.5 and (top_speed(tags_km) or 0) >= 200:
        return "hs" if top_speed(tags_km) >= 300 else "semi"
    return "main" if share(lambda t: t.get("usage") == "main") >= 0.5 else "branch"


def speed_of(name, jk, tags_km):
    """The speed that bands a fast line. A line with no design speed on record here (every
    semi-high-speed line so far) takes the speed its track is signed for, marked as a top speed."""
    if jk in ("hs", "semi"):
        return HIGH_SPEED.get(name) or (top_speed(tags_km), True, None)
    return None


KR = Country(
    code="kr", plain_name=plain_name, kind_of=kind_of, speed_of=speed_of, cities=CITIES, elsewhere="韩国其他",
    fast_kinds=("hs", "semi"), main_kinds=("main",),
    rail=frozenset({"rail"}), urban=frozenset({"subway", "light_rail", "monorail", "tram"}),
    skip_usage=frozenset({"industrial", "military", "test", "freight", "tourism"}),
    skip_stations=("funicular", "miniature"),
    tag_keys=("railway", "usage", "highspeed", "maxspeed"),
    build_fast=lambda name: name.endswith("고속선") or "고속철도" in name,
)

if __name__ == "__main__":
    run(KR)
