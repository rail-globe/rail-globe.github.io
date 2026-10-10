"""A feature's names beside its own, for the page's two languages: nz, its name in simplified
Chinese, and ne, its name in English. The page puts them together by the reader's language
(서울(首尔) for a Chinese reader, 서울(Seoul) for an English one); nothing combined is written here.

n stays what it is everywhere: the name on the spot, in the country's own writing, and the key
that lines, stations and cities are selected, joined and searched by (ct points at a city's n).
nz and ne are written only where they are known and differ from n, and never with brackets in
them (the page adds its own).

Where they come from:
- nz in Korea and the United Kingdom: a table per country, data/kr_names.tsv and data/uk_names.tsv,
  one row per name with its source. A station's or a depot's row names the one of that name at
  its point; a line's row the line of that name. A country without a table gets no nz from one.
- nz in Japan: OSM's name:zh, where it is sound: Chinese characters only (no kana, no Latin, no
  brackets), and not the Japanese name itself. Most of Japan's stations have none.
- ne: OSM's name:en, in China, Japan and Korea (the United Kingdom's names are English). A line's
  is the one most of its track carries; a station's drops a trailing "Station", as n has no 站 or 駅.
- The metro cities: nl, the city's own name where n is its Chinese one (東京, 서울, London), and ne,
  from data/cities.json, which has them with their sources, and from CITY_NAMES below for the few
  metro cities that are not among its places.
Nothing is made up: no pinyin, no romanisation; a feature with no source for a name has none.
"""
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BRACKETS = re.compile(r"[()（）\[\]【】{}「」]")
STATION_NEAR_M = 50       # a station's row names the station of that name this close to its point
DEPOT_NEAR_M = 1000       # a depot's label stands on its tracks, which can be this far from where its row was read
# The columns of a country's table: (its own name, the Chinese name).
TABLES = {"kr": ("ko", "zh"), "uk": ("name_en", "name_zh")}
KINDS = {"station": "station", "depot": "depot", "rail line": "line", "metro line": "line",
         "metro or tram line": "line", "line being built": "line"}
# Rows of the UK table that are off until the owner has seen samples of them, one switch each:
# tier B, a Wikidata label with no article behind it; and a name whose only source writes it
# the Hong Kong or Taiwan way, with no mainland form on the page.
UK_TIER_B = False
UK_FLAGGED_WORDING = False
ENGLISH = {"cn", "jp", "kr"}          # the countries whose features get ne from name:en
# Metro cities that data/cities.json does not have among its places: (own name, English name),
# each read off the place node of the city in the country's extract.
CITY_NAMES = {
    "jp": {"北九州": ("北九州", "Kitakyushu"),      # node 5410283420 place=city name=北九州市 name:en=Kitakyushu
           "函馆": ("函館", "Hakodate"),           # node 3229063363 place=city name=函館市 name:en=Hakodate
           "丰桥": ("豊橋", "Toyohashi")},         # node 569005441 place=city name=豊橋市 name:en=Toyohashi
}


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def english(tags, station=False):
    """The English name of an OSM object, or None. A station's drops its trailing "Station"."""
    name = clean(tags.get("name:en"))
    if station:
        name = re.sub(r"\s+(Railway |Train |Subway |Metro |MTR |LRT |Light Rail )?(Station|Stop)$", "", name, flags=re.I).strip()
    return name or None


def sound_zh(value, n=None):
    """OSM's name:zh of a Japanese object where it can stand as the Chinese name: Chinese
    characters only, with a trailing 站 or 駅 taken off as n has none; None otherwise."""
    name = re.sub(r"(车站|車站|站|駅)$", "", clean(value))
    if not name or not re.fullmatch(r"[㐀-鿿豈-﫿々〇0-9]+", name) or name == n:
        return None
    return name


def put(props, nz=None, ne=None):
    """Writes nz and ne into a feature's properties, where they are known and differ from n."""
    for key, value in (("nz", nz), ("ne", ne)):
        if value and value != props.get("n") and not BRACKETS.search(value):
            props[key] = value
    return props


def metres(a, b):
    return math.hypot((a[0] - b[0]) * math.cos(math.radians((a[1] + b[1]) / 2)), a[1] - b[1]) * 111320


class Table:
    """A country's table of Chinese names (data/<g>_names.tsv), the rows that are in use."""

    def __init__(self, g, data=DATA):
        self.g, self.rows = g, []
        path = data / f"{g}_names.tsv"
        if g not in TABLES or not path.exists():
            return
        own, zh = TABLES[g]
        for row in csv.DictReader(path.read_text(encoding="utf-8").splitlines(), delimiter="\t"):
            kind = KINDS.get(row["kind"])
            if not kind or g == "uk" and not self.in_use(row):
                continue
            name = row[zh].strip()
            if BRACKETS.search(name):
                # a name with brackets of its own (金泉(龟尾)): the form without them that the row gives
                plain = re.search(r"without inner (?:parentheses|brackets): ([^\s;,(（]+)", row["note"])
                if not plain:
                    continue
                name = plain.group(1)
            at = (float(row["lon"]), float(row["lat"])) if row["lon"] else None
            self.rows.append({"kind": kind, "own": row[own].strip(), "zh": name, "at": at, "source": row["source"]})
        self.by = defaultdict(list)
        for row in self.rows:
            self.by[(row["kind"], row["own"])].append(row)

    @staticmethod
    def in_use(row):
        if row["tier"] == "B" and not UK_TIER_B:
            return False
        return UK_FLAGGED_WORDING or "FLAG wording" not in row["note"]

    def zh(self, kind, name, at=None):
        """The Chinese name of a station, a depot (by its name and where it is) or a line (by its name)."""
        rows = self.by.get((kind, name), [])
        if kind == "line":
            names = {row["zh"] for row in rows}
            return rows[0]["zh"] if len(names) == 1 else None
        reach = STATION_NEAR_M if kind == "station" else DEPOT_NEAR_M
        near = sorted((metres(at, row["at"]), row["zh"]) for row in rows if row["at"])
        return near[0][1] if near and near[0][0] <= reach else None


class Names:
    """The names of a country's features beside n. Lines: add() the OSM objects behind each drawn
    name as the line is made, then line() gives a feature its names. Stations and depots: the
    object's own tags and place."""

    def __init__(self, g, data=DATA):
        self.g, self.table = g, Table(g, data)
        self.en, self.zh = defaultdict(Counter), defaultdict(Counter)

    def add(self, n, tags, weight=1.0):
        """An OSM object behind the line named n, with as much weight as it has track."""
        if self.g in ENGLISH:
            en = english(tags)
            if en:
                self.en[n][en] += weight
        if self.g == "jp":
            zh = sound_zh(tags.get("name:zh"), n)
            if zh:
                self.zh[n][zh] += weight

    @staticmethod
    def top(votes):
        return max(votes.items(), key=lambda kv: (kv[1], kv[0]))[0] if votes else None

    def line(self, props):
        n = props.get("n")
        if not n:
            return props
        nz = self.table.zh("line", n) if self.table.rows else self.top(self.zh.get(n))
        return put(props, nz, self.top(self.en.get(n)))

    def station(self, props, tags, at):
        nz = self.table.zh("station", props["n"], at) if self.table.rows else (sound_zh(tags.get("name:zh"), props["n"]) if self.g == "jp" else None)
        return put(props, nz, english(tags, station=True) if self.g in ENGLISH else None)

    def depot(self, props, at, en=None):
        nz = self.table.zh("depot", props["n"], at) if self.table.rows else None
        return put(props, nz, clean(en) if self.g in ENGLISH else None)

    def copy(self, row, props):
        """The names of a line's features onto its row in a list (lines.json, a metro city's lines)."""
        for key in ("nz", "ne"):
            if key in props:
                row[key] = props[key]
        return row


def city_names(g, data=DATA):
    """{the Chinese name of a metro city: (its own name, its English name)} from data/cities.json
    (an entry of the country whose m, the name the metro list has for it, is that name; in China
    the entry of that name) and CITY_NAMES."""
    path = data / "cities.json"
    out = {}
    for c in json.loads(path.read_text()) if path.exists() else []:
        if c.get("g", "cn") != g:
            continue
        key = c["n"] if g == "cn" else c.get("m")
        if key and key not in out:
            out[key] = (c["n"], c.get("ne"))
    out.update(CITY_NAMES.get(g, {}))
    # the table's rows for the metro cities: the city's own name beside the Chinese one (London 伦敦)
    table = data / f"{g}_names.tsv"
    if g in TABLES and table.exists():
        own, zh = TABLES[g]
        for row in csv.DictReader(table.read_text(encoding="utf-8").splitlines(), delimiter="\t"):
            if row["kind"] == "metro system or city" and row[zh] not in out:
                out[row[zh]] = (row[own], None)
    return out


def name_city(props, names, g):
    """nl and ne of a metro city's entry."""
    own, en = names.get(props["n"], (None, None))
    if own and own != props["n"] and not BRACKETS.search(own):
        props["nl"] = own
    if en and en != props["n"] and en != own and g in ENGLISH and not BRACKETS.search(en):
        props["ne"] = en
    return props


# ---- the check, on the files as written ----

# Rows of a table that name nothing on the map, as many as there are on 2026-10-10; one more is
# a name lost. Korea 18: 6 stations the map no longer draws, as no drawn line passes them (연무대,
# 송학, 해월전망대, 미포, 구덕포, 동백 of the 용인 line), and 12 depot rows whose label the depot rules
# replaced with the name OSM gives the same depot's ground (지축기지 -> 지축차량사업소), or dropped
# as no drawn yard track is near it (북철송장, 창동기지), until rows for the new names come.
# The United Kingdom 1: Middleton Road, a stop the map no longer draws.
UNMATCHED = {"kr": 18, "uk": 1}

def check(g, data=DATA):
    """What the names of a country's files hold to: [(needs a look?, text)] and the counts.
    Counts per kind of feature how many have nz and ne; finds nz or ne equal to n, or with
    brackets; and the rows of the country's table that name nothing on the map."""
    pre = "" if g == "cn" else g + "_"
    load = lambda name: json.loads((data / name).read_text()) if (data / name).exists() else None
    files = {"station": [f"{pre}stations.geojson"] + (["metro_stations.geojson"] if g == "cn" else []),
             "line": ([f"rail_{k}.geojson" for k in ("hsr", "conv", "shared", "build")] if g == "cn" else [f"{g}_rail.geojson", f"{g}_build.geojson"]) + [f"{pre}metro.geojson"],
             "depot": [f"{pre}depots.geojson"]}
    counts, wrong, there = {}, [], defaultdict(list)
    for kind, names in files.items():
        feats = [f for name in names for f in (load(name) or {"features": []})["features"]]
        counts[kind] = {"features": len(feats), "nz": sum(1 for f in feats if "nz" in f["properties"]),
                        "ne": sum(1 for f in feats if "ne" in f["properties"])}
        for f in feats:
            p = f["properties"]
            there[(kind, p.get("n"))].append(f["geometry"]["coordinates"] if f["geometry"]["type"] == "Point" else None)
            for key in ("nz", "ne"):
                if key in p and (p[key] == p.get("n") or BRACKETS.search(p[key])):
                    wrong.append((p.get("n"), key, p[key]))
    rows = [load(f"{pre}lines.json") or [], [ln for c in load(f"{pre}metro_cities.json") or [] for ln in c["lines"]]]
    for name, lst in (("lines list", rows[0]), ("metro city lines", rows[1])):
        counts[name] = {"features": len(lst), "nz": sum(1 for r in lst if "nz" in r), "ne": sum(1 for r in lst if "ne" in r)}
        wrong += [(r["n"], k, r[k]) for r in lst for k in ("nz", "ne") if k in r and (r[k] == r["n"] or BRACKETS.search(r[k]))]
    cities = load(f"{pre}metro_cities.json") or []
    counts["metro cities"] = {"features": len(cities), "nl": sum(1 for c in cities if "nl" in c), "ne": sum(1 for c in cities if "ne" in c)}
    table = Table(g, data)
    lost = []
    for row in table.rows:
        spots = there.get((row["kind"], row["own"]), [])
        if row["kind"] == "line":
            ok = bool(spots)
        else:
            reach = STATION_NEAR_M if row["kind"] == "station" else DEPOT_NEAR_M
            ok = any(at and metres(at, row["at"]) <= reach for at in spots)
        if not ok:
            lost.append((row["kind"], row["own"], row["zh"]))
    out = [(False, f"names beside n, per kind: " + "; ".join(f"{k} {v}" for k, v in counts.items())),
           (bool(wrong), f"nz or ne equal to n, or with brackets: {len(wrong)} {wrong[:6]}")]
    if table.rows:
        out.append((len(lost) > UNMATCHED.get(g, 0), f"rows of the names table that name nothing on the map (not drawn, or a depot's label replaced): "
                    f"{len(lost)} (fixed count {UNMATCHED.get(g, 0)}) {lost[:20]}"))
        out.append((False, f"rows of the names table in use: {len(table.rows)}; " + ", ".join(
            f"{kind}s without nz {counts[kind]['features'] - counts[kind]['nz']} of {counts[kind]['features']}" for kind in ("station", "line", "depot"))))
    return out, {"counts": counts, "wrong": wrong, "lost": lost}
