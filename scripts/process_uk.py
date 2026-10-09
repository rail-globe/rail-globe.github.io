"""United Kingdom: railways, heritage lines, metros, light rail and trams, written as layers of
their own by the shared pipeline (scripts/country.py), which holds the colour rule and the method.

    python3 scripts/extract_osm.py uk     united-kingdom.osm.pbf -> data/raw/extract_uk.pkl
    python3 scripts/process_uk.py         -> data/uk_rail.geojson, uk_metro.geojson, uk_build.geojson,
                                             uk_stations.geojson, uk_lines.json, uk_metro_cities.json,
                                             uk_facts.json, uk_yards.geojson, uk_depots.geojson

What is the United Kingdom's own is here: how its track is named, its classes of line, its
high-speed line and the networks whose lines have official colours.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from country import Country, line_colours, line_of_route, run     # line_colours, line_of_route: for the tests

# A tunnel, viaduct or bridge named for itself is part of the line on either side of it.
STRUCTURE = re.compile(r"(Tunnels?|Viaduct|Bridge|Flyover|Underpass|Dive-?under|Portal)$", re.I)
# A name that says which track, not which line ("Down Fast", "Up Goods Loop", "CTRL Relief"): that
# track belongs to the line it lies on, so it is treated as unnamed and joins its neighbour.
TRACK = re.compile(r"^(Up|Down)\b|\b(Up|Down) (&|and) (Up|Down)\b|\b(Up|Down) (Goods )?Loop$|\bGoods( Loop)?$|\b(Fast|Slow|Relief|Sidings?)$")
# Names that are one line under several spellings.
SAME_LINE = {"Channel Tunnel Rail Link": "High Speed 1", "Elizabeth Line": "Elizabeth line"}
# High-speed lines: (design speed in km/h, whether that is only the line's top speed, source).
# High Speed 1: "Operating speed 300 km/h", "a maximum speed of 300 km/h" on Section 1
# (https://en.wikipedia.org/wiki/High_Speed_1, read 2026-10-08). The page gives no design speed,
# so the figure is marked as an estimate (property e), as the Chinese map marks a band taken from
# the track's speed.
# The main lines run at 125 mph (West Coast, East Coast, Great Western) are existing lines made
# faster, like the conventional trunk lines raised to 200 km/h in China: conventional here too.
HIGH_SPEED = {"High Speed 1": (300, True, "https://en.wikipedia.org/wiki/High_Speed_1")}
# Networks of a few lines with official colours of their own, however few colours that makes.
LINE_COLOURS = re.compile(r"London Overground|Overground|Elizabeth line|Merseyrail", re.I)
# Metro and tram lines are listed by city: (name shown, lon, lat, reach in degrees).
CITIES = [("伦敦", -0.12, 51.51, 0.7), ("曼彻斯特", -2.24, 53.48, 0.45), ("纽卡斯尔", -1.61, 54.97, 0.45), ("格拉斯哥", -4.25, 55.86, 0.3),
          ("伯明翰", -1.90, 52.48, 0.4), ("诺丁汉", -1.15, 52.95, 0.25), ("谢菲尔德", -1.47, 53.38, 0.35), ("爱丁堡", -3.19, 55.95, 0.3),
          ("布莱克浦", -3.05, 53.82, 0.25)]


def plain_name(name):
    """A track's name as the name of its line: without what is added in brackets (a branch, a
    direction) or after a dash, and for a structure on a line, or a name that only says which
    track it is, nothing at all."""
    name = re.sub(r"\s*\(.*?\)", "", name or "")
    name = re.split(r"\s+[-‒–]\s+|;", name)[0]
    name = re.sub(r"\s+", " ", name).strip()
    if "Channel Tunnel" in name and "Rail Link" not in name:
        return "Channel Tunnel"
    name = SAME_LINE.get(name, name)
    return "" if STRUCTURE.search(name) or TRACK.search(name) else name


def kind_of(name, tags_km):
    """A railway line's class: the high-speed line by name; heritage where most of its track is a
    preserved or narrow-gauge line or run for tourists; else a main line or a branch."""
    if name in HIGH_SPEED:
        return "hs"
    total = sum(tags_km.values()) or 1
    share = lambda test: sum(v for k, v in tags_km.items() if test(dict(k))) / total
    if share(lambda t: t.get("railway") == "narrow_gauge" or t.get("railway:preserved") == "yes" or t.get("usage") == "tourism") >= 0.5:
        return "heritage"
    return "main" if share(lambda t: t.get("usage") == "main") >= 0.5 else "branch"


UK = Country(
    code="uk", plain_name=plain_name, kind_of=kind_of, speed_of=lambda name, jk, tags_km: HIGH_SPEED.get(name),
    cities=CITIES, elsewhere="英国其他", colour_networks=LINE_COLOURS,
    build_name=lambda name: "High Speed 2" if re.match(r"HS2|High Speed 2", name) else name,
    build_fast=lambda name: name == "High Speed 2",        # drawn in the colour of high-speed lines being built
)

if __name__ == "__main__":
    run(UK)
