"""How the rows of data/<g>_names.tsv for Thailand, Malaysia, Singapore and Indonesia were found
(South-East Asia, 2026-10-19). This reads Wikipedia over the network, so it is not part of the
offline run: its output, the table, is the pipeline's input, each row with its source.

    python3 scripts/sea_names_lookup.py sg|my|th|id [--lines]   (after process_sea.py, which writes data/<g>_stations.geojson;
                                                                 --lines: the station rows kept, the rest looked up again)

Tiers (scripts/names.py): O the operator's or the government's own Chinese name, A the title of a
zh.wikipedia article in mainland usage (its zh-cn title), C a sourced city name with a fixed word.
- Stations, tier O: Singapore's LTA, "Train Station Chinese Names" (data.gov.sg, open data, read
  2026-10-19, data/raw/sg-lta/train_station_chinese_names.json), by the station's English name;
  "站" and the spaces in four of its rows (EW30-EW33) are taken off.
- Stations, tier A: the en.wikipedia article of the station (a page within 800 m of the drawn
  station whose title is its English name followed by a word for a station), and that article's
  zh.wikipedia counterpart, by its zh-cn title, without 站 / 车站 and without a bracket that tells
  two articles apart. A station with no such pair has no row (no transliteration is made up).
- Lines and cities: the en.wikipedia article named in LINES / CITIES and its zh counterpart, or
  the operator's name for Singapore's lines.
"""
import csv
import io
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
UA = {"User-Agent": "RailGlobe-names/0.2 (https://rail-globe.github.io; one-off lookup of article titles)"}
LTA_URL = "https://data.gov.sg/datasets/d_d312a5b127e1ae74299b8ae664cedd4e/view"
STATION_WORD = re.compile(r"^(?P<name>.+?)\s+(?:(?:LRT|MRT|BTS|ARL|SRT|KTM|KRL|Komuter|Monorail|monorail|railway|train|Skytrain|Airport Rail Link|MRT/LRT|LRT/MRT|light rail|commuter)\s+)*(?:station|halt|stop)\b", re.I)
STATION_SUFFIX = re.compile(r"(火车站|车站|站)$")
# en.wikipedia articles of lines, by the line's name on the map (n): metro and rail lines of each country
LINES = {
    "my": {"rail line": {"KTM Laluan kereta api Pantai Barat": "KTM West Coast Line", "KTM Laluan kereta api Pantai Timur": "KTM East Coast Line",
                         "Laluan Keretapi Barat Sabah": "Western Sabah Railway Line", "ERL": "Express Rail Link"},
           "line being built": {"East Coast Rail Link": "MRL East Coast Rail Link", "LRT Laluan Mutiara": "Mutiara Line",
                                "Johor Bahru–Singapore Rapid Transit System": "Johor Bahru–Singapore Rapid Transit System"},
           "metro line": {"Kelana Jaya Line": "Kelana Jaya Line",
                          "Shah Alam Line": "Shah Alam Line", "KL Monorail": "KL Monorail", "Laluan Kajang": "MRT Kajang Line",
                          "Laluan Putrajaya": "MRT Putrajaya Line", "KLIA Ekspres": "KLIA Ekspres", "KLIA Transit": "KLIA Transit",
                          "Seremban Line": "KTM Batu Caves–Pulau Sebang Line", "Port Klang Line": "KTM Tanjung Malim–Port Klang Line"}},
    "th": {"rail line": {"สายเหนือ": "Northern Line (Thailand)", "สายตะวันออกเฉียงเหนือ": "Northeastern Line (Thailand)",
                         "สายตะวันออก": "Eastern Line (Thailand)", "สายใต้": "Southern Line (Thailand)", "สายแม่กลอง": "Maeklong Railway",
                         "รถไฟฟ้าเอราวัน": "Airport Rail Link (Bangkok)", "รถไฟฟ้าชานเมืองสายสีแดงเข้ม": "SRT Dark Red Line",
                         "รถไฟฟ้าชานเมืองสายสีแดงอ่อน": "SRT Light Red Line"},
           "line being built": {"รถไฟความเร็วสูง สายกรุงเทพฯ-นครราชสีมา": "Bangkok–Nong Khai high-speed railway",
                                "รถไฟฟ้ามหานคร สายสีส้ม": "MRT Orange Line"},
           "metro line": {"รถไฟฟ้าบีทีเอส สายสุขุมวิท": "Sukhumvit Line", "รถไฟฟ้าบีทีเอส สายสีลม": "Silom Line",
                          "รถไฟฟ้ามหานคร สายสีน้ำเงิน": "MRT Blue Line", "รถไฟฟ้ามหานคร สายสีม่วง": "MRT Purple Line",
                          "รถไฟฟ้าสายสีเหลือง": "MRT Yellow Line", "รถไฟฟ้ามหานคร สายสีชมพู": "MRT Pink Line", "รถไฟฟ้าสายสีทอง": "Gold Line (Bangkok)",
                          "รถไฟฟ้าเชื่อมท่าอากาศยานสุวรรณภูมิ": "Airport Rail Link (Bangkok)", "สายสีแดงเข้ม": "SRT Dark Red Line",
                          "สายสีแดงอ่อน": "SRT Light Red Line"}},
    "id": {"rail line": {"Jalur Kereta Cepat Jakarta–Bandung": "Jakarta–Bandung high-speed railway"},
           "line being built": {"MRT Jakarta Jalur Utara–Selatan": "North–South Line (Jakarta MRT)"},
           "metro line": {"MRT North-South Line": "North–South Line (Jakarta MRT)", "LRT Jakarta": "Jakarta LRT",
                          "LRT Palembang": "Palembang LRT", "Jabodebek LRT Bekasi Line": "Jabodebek LRT", "Jabodebek LRT Cibubur Line": "Jabodebek LRT",
                          "Lin Soekarno Hatta": "Soekarno–Hatta Airport Rail Link", "Kereta Api Bandara YIA": "Yogyakarta International Airport Rail Link",
                          "Lin Srilelawangsa": "Kualanamu Airport Rail Link", "Minangkabau Ekspres": "Minangkabau International Airport Rail Link",
                          "Kereta Api BIAS": "Adi Soemarmo Airport Rail Link"}},
    "sg": {"line being built": {"Cross Island Line": "Cross Island MRT line", "Jurong Region Line": "Jurong Region MRT line",
                                "Johor Bahru–Singapore Rapid Transit System": "Johor Bahru–Singapore Rapid Transit System"},
           "metro line": {"MRT Thomson–East Coast Line": "Thomson–East Coast MRT line", "Sentosa Express": "Sentosa Express"},
           "rail line": {"KTM Laluan kereta api Pantai Barat": "KTM West Coast Line"}},
}
# Words that make a station's name another station's (see station_rows)
OTHER_STATION = {"rts", "mrt", "lrt", "bts", "ktm", "komuter", "monorail", "brt", "ets", "ii", "iii"}
# zh.wikipedia articles whose en.wikipedia counterpart is another station's: 曼谷阿皮瓦中央站 (Krung
# Thep Aphiwat Central Terminal) is linked from en.wikipedia "Bang Sue Junction railway station",
# the old station beside it (read 2026-10-19)
WRONG_LINK = {"th": {"曼谷阿皮瓦中央站"}}
# Station rows written as they are: (n, lon, lat, Chinese name, source, note)
MANUAL_STATIONS = {"th": [("กรุงเทพอภิวัฒน์", 100.54171, 13.80403, "曼谷阿皮瓦中央",
                           "https://zh.wikipedia.org/zh-cn/%E6%9B%BC%E8%B0%B7%E9%98%BF%E7%9A%AE%E7%93%A6%E4%B8%AD%E5%A4%AE%E7%AB%99",
                           "the zh.wikipedia article of Krung Thep Aphiwat Central Terminal, zh-cn title 曼谷阿皮瓦中央站")]}
# Rows written as they are: (kind, n, Chinese name, source, note)
MANUAL = {"my": [("metro line", "Ampang Line", "安邦线", "https://zh.wikipedia.org/zh-cn/%E5%AE%89%E9%82%A6%E7%BA%BF%E5%92%8C%E5%A4%A7%E5%9F%8E%E5%A0%A1%E7%BA%BF",
                  "the zh-cn title of the article of both lines (en.wikipedia Ampang and Sri Petaling lines) is 安邦线和大城堡线"),
                 ("metro line", "Sri Petaling Line", "大城堡线", "https://zh.wikipedia.org/zh-cn/%E5%AE%89%E9%82%A6%E7%BA%BF%E5%92%8C%E5%A4%A7%E5%9F%8E%E5%A0%A1%E7%BA%BF",
                  "the zh-cn title of the article of both lines (en.wikipedia Ampang and Sri Petaling lines) is 安邦线和大城堡线"),
                 # the metro city of Komuter Utara (槟城, the state): its own name beside the Chinese one
                 ("metro system or city", "Penang", "槟城", "https://zh.wikipedia.org/zh-cn/%E6%A7%9F%E5%9F%8E", "en.wikipedia Penang; zh-cn title 槟城")],
          # the metro city of the Adi Soemarmo airport trains (Solo), not a provincial capital
          "id": [("metro system or city", "Surakarta", "梭罗", "https://zh.wikipedia.org/zh-cn/%E6%A2%AD%E7%BD%97_(%E5%8D%B0%E5%B0%BC)",
                  "en.wikipedia Surakarta; zh-cn title 梭罗 (印尼), without the bracket")]}
# Singapore's lines by the operator's English name (LTA), for the map's names of them
LTA_LINES = {"MRT North-South Line": "North South Line", "MRT East-West Line": "East West Line", "MRT North East Line": "North East Line",
             "MRT Circle Line": "Circle Line", "MRT Downtown Line": "Downtown Line", "LRT Bukit Panjang Line": "Bukit Panjang LRT",
             "LRT Sengkang Line": "Sengkang LRT", "LRT Punggol Line": "Punggol LRT", "Downtown Line": "Downtown Line"}


def get(url, params, tries=3):
    q = url + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(q, headers=UA), timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as error:          # a slow answer: wait and ask again
            if k == tries - 1:
                raise
            time.sleep(2 + 3 * k)


def metres(a, b):
    return math.hypot((a[0] - b[0]) * math.cos(math.radians((a[1] + b[1]) / 2)), a[1] - b[1]) * 111320


def plain(text):
    text = re.sub(r"^kl\b", "kuala lumpur", (text or "").lower().strip())        # (KL Sentral, Kuala Lumpur Sentral station)
    return re.sub(r"[\s\-–—'’.()]+", " ", text).strip()


def zh_cn(titles):
    """{zh title: its zh-cn variant title} (redirects followed)."""
    out = {}
    titles = sorted(set(titles))
    for i in range(0, len(titles), 40):
        part = titles[i:i + 40]
        r = get("https://zh.wikipedia.org/w/api.php", {"action": "query", "titles": "|".join(part), "prop": "info", "inprop": "varianttitles", "redirects": 1})
        q = r.get("query", {})
        moved = {x["from"]: x["to"] for x in q.get("redirects", []) + q.get("normalized", [])}
        pages = {p["title"]: p for p in q.get("pages", []) if not p.get("missing")}
        for t in part:
            target = moved.get(moved.get(t, t), moved.get(t, t))
            page = pages.get(target)
            if page:
                out[t] = page.get("varianttitles", {}).get("zh-cn") or page["title"]
        time.sleep(0.2)
    return out


def zh_of_en(titles):
    """{en title: (zh title, en title after redirects)} for the en.wikipedia articles that have a zh one."""
    out = {}
    titles = sorted(set(titles))
    for i in range(0, len(titles), 40):
        part = titles[i:i + 40]
        r = get("https://en.wikipedia.org/w/api.php", {"action": "query", "titles": "|".join(part), "prop": "langlinks", "lllang": "zh", "lllimit": "max", "redirects": 1})
        q = r.get("query", {})
        moved = {x["from"]: x["to"] for x in q.get("normalized", []) + q.get("redirects", [])}
        pages = {p["title"]: p for p in q.get("pages", []) if not p.get("missing")}
        for t in part:
            target = moved.get(moved.get(t, t), moved.get(t, t))
            page = pages.get(target)
            if page and page.get("langlinks"):
                out[t] = (page["langlinks"][0]["title"], page["title"])
        time.sleep(0.2)
    return out


def shown(zh_title):
    """A zh-cn article title as the Chinese name beside n: without the bracket that tells two
    articles apart and without 站 / 车站."""
    name = re.sub(r"\s*[(（][^()（）]*[)）]\s*$", "", zh_title).strip()
    return STATION_SUFFIX.sub("", name).strip()


def station_rows(g):
    feats = json.loads((DATA / f"{g}_stations.geojson").read_text())["features"]
    rows, wanted = [], []
    lta = {}
    if g == "sg":
        for r in json.loads((DATA / "raw" / "sg-lta" / "train_station_chinese_names.json").read_text())["result"]["records"]:
            zh = re.sub(r"\s+", "", r["mrt_station_chinese"])
            zh = re.sub(r"站$", "", zh)
            lta.setdefault(plain(r["mrt_station_english"]), (zh, r["stn_code"], r["mrt_station_chinese"]))
    for f in feats:
        p, (lon, lat) = f["properties"], f["geometry"]["coordinates"]
        en = p.get("ne") or p["n"]
        if plain(en) in lta:
            zh, code, raw = lta[plain(en)]
            note = f"LTA {code} {en}" + (f"; the dataset writes {raw!r}" if raw != zh else "")
            rows.append(("station", p["n"], lon, lat, zh, "O", LTA_URL, note))
        else:
            wanted.append((p["n"], en, lon, lat))
    def look(item):
        n, en, lon, lat = item
        r = get("https://en.wikipedia.org/w/api.php", {"action": "query", "generator": "geosearch", "ggscoord": f"{lat}|{lon}",
                                                       "ggsradius": 800, "ggslimit": 30, "prop": "coordinates|langlinks", "lllang": "zh",
                                                       "lllimit": "max", "colimit": "max"})
        best, loose = None, None
        mine = plain(en).split()
        for page in r.get("query", {}).get("pages", []):
            if not page.get("langlinks") or not page.get("coordinates"):
                continue
            c = page["coordinates"][0]
            d = metres((lon, lat), (c["lon"], c["lat"]))
            m = STATION_WORD.match(page["title"])
            theirs = plain(m.group("name") if m else re.sub(r"\s*\([^()]*\)$", "", page["title"])).split()
            if m and theirs == mine:
                if best is None or d < best[0]:
                    best = (d, page["title"], page["langlinks"][0]["title"])
            # a second choice, within 400 m: the article's name and the station's share their first
            # word and one holds all the other's words ("Tegalluar railway station" for Tegalluar
            # Summarecon; "Woodlands Train Checkpoint"), the station's own article
            # (but not where the words one has more of name another station: Woodlands North RTS is
            # not Woodlands North, Glenmarie 2 not Glenmarie, KL Sentral's monorail station not KL Sentral)
            elif (d <= 400 and theirs and mine and theirs[0] == mine[0] and (set(theirs) <= set(mine) or set(mine) <= set(theirs))
                  and not any(w in OTHER_STATION or w.isdigit() for w in set(theirs) ^ set(mine))
                  and (m or theirs == mine) and (loose is None or d < loose[0])):
                loose = (d, page["title"], page["langlinks"][0]["title"], "; matched by its first words")
        best = best or loose
        return (n, en, lon, lat, *best) if best else None
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as pool:              # (four questions at a time)
        found = [f for f in pool.map(look, wanted) if f]
    variants = zh_cn([f[6] for f in found])
    for n, en, lon, lat, d, en_title, zh_title, *how in found:
        cn = variants.get(zh_title)
        if not cn or cn in WRONG_LINK.get(g, {}):
            continue
        name = shown(cn)
        if not name or re.search(r"[A-Za-z]", name) and plain(name) == plain(n):
            continue
        url = "https://zh.wikipedia.org/zh-cn/" + urllib.parse.quote(cn.replace(" ", "_"))
        rows.append(("station", n, lon, lat, name, "A", url, f"en.wikipedia {en_title} ({d:.0f} m from the station); zh-cn title {cn}{''.join(how)}"))
    # one Chinese name for two stations of different names is a mistake of one of them: neither keeps it
    names_of = {}
    for r in rows:                     # ("KL Sentral (Monorail", the name of KL Sentral's monorail station, is KL Sentral's)
        names_of.setdefault(r[4], set()).add(re.sub(r"\s*\(.*$", "", r[1]))
    twice = {zh for zh, ns in names_of.items() if len(ns) > 1}
    if twice:
        print(f"{g}: Chinese names given to stations of different names, left out: {sorted(twice)}", flush=True)
    rows = [r for r in rows if r[4] not in twice]
    rows += [("station", n, lon, lat, zh, "A", url, note) for n, lon, lat, zh, url, note in MANUAL_STATIONS.get(g, [])]
    return rows, len(feats)


def line_rows(g):
    rows = []
    if g == "sg":
        lta = {r["mrt_line_english"]: r["mrt_line_chinese"] for r in json.loads((DATA / "raw" / "sg-lta" / "train_station_chinese_names.json").read_text())["result"]["records"]}
        for n, en in LTA_LINES.items():
            kind = "line being built" if n == "Downtown Line" else "metro line"
            rows.append((kind, n, "", "", lta[en], "O", LTA_URL, f"LTA line name {en}"))
    table = LINES.get(g, {})
    pairs = zh_of_en([t for kinds in table.values() for t in kinds.values()])
    variants = zh_cn([z for z, _ in pairs.values()])
    for kind, names in table.items():
        for n, en in names.items():
            if en in pairs and variants.get(pairs[en][0]):
                cn = variants[pairs[en][0]]
                name = re.sub(r"\s*[(（][^()（）]*[)）]\s*$", "", cn).strip()
                url = "https://zh.wikipedia.org/zh-cn/" + urllib.parse.quote(cn.replace(" ", "_"))
                rows.append((kind, n, "", "", name, "A", url, f"en.wikipedia {pairs[en][1]}; zh-cn title {cn}"))
    return rows


def kept_station_rows(g):
    """The station rows of the table as it is (--lines: only the rows of lines are looked up again)."""
    rows = list(csv.reader((DATA / f"{g}_names.tsv").read_text(encoding="utf-8").splitlines(), delimiter="\t"))[1:]
    total = len(json.loads((DATA / f"{g}_stations.geojson").read_text())["features"])
    return [tuple(r) for r in rows if r[0] == "station"], total


def main(g, lines_only=False):
    rows, total = kept_station_rows(g) if lines_only else station_rows(g)
    rows += line_rows(g)
    rows += [(kind, n, "", "", zh, "A", url, note) for kind, n, zh, url, note in MANUAL.get(g, [])]
    out = io.StringIO()
    w = csv.writer(out, delimiter="\t", lineterminator="\n")
    w.writerow(["kind", "name", "lon", "lat", "name_zh", "tier", "source", "note"])
    for row in rows:
        w.writerow(row)
    (DATA / f"{g}_names.tsv").write_text(out.getvalue(), encoding="utf-8")
    st = [r for r in rows if r[0] == "station"]
    print(f"{g}_names.tsv: {len(rows)} rows; stations {len(st)} of {total} drawn "
          f"(O {sum(r[5] == 'O' for r in st)}, A {sum(r[5] == 'A' for r in st)}); lines {len(rows) - len(st)}")


if __name__ == "__main__":
    main(sys.argv[1], "--lines" in sys.argv[2:])


def city_names(seats, radius=4000):
    """For the cities of a label table: [(place node name, English name, lon, lat)] -> {place node
    name: (zh-cn title, en.wikipedia title, metres)}, by the en.wikipedia article of the city within
    `radius` of its place node whose title is its English name (or that name and a qualifier,
    "Nonthaburi (city)", "Victoria, Labuan"), and that article's zh.wikipedia counterpart."""
    def look(item):
        local, en, lon, lat = item
        r = get("https://en.wikipedia.org/w/api.php", {"action": "query", "generator": "geosearch", "ggscoord": f"{lat}|{lon}",
                                                       "ggsradius": radius, "ggslimit": 50, "prop": "coordinates|langlinks", "lllang": "zh",
                                                       "lllimit": "max", "colimit": "max"})
        best = None
        for page in r.get("query", {}).get("pages", []):
            title = page["title"]
            base = re.split(r",| \(", title)[0]
            if plain(base) not in (plain(en), plain("Mueang " + en)) or not page.get("langlinks") or re.search(r"province|district|station|airport|university|hospital|river|temple|wat ", title, re.I):
                continue
            c = (page.get("coordinates") or [{}])[0]
            d = metres((lon, lat), (c.get("lon", lon), c.get("lat", lat)))
            if best is None or (title != base, d) < (best[1] != re.split(r",| \(", best[1])[0], best[2]):
                best = (page["langlinks"][0]["title"], title, d)
        return local, best
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as pool:
        found = {local: best for local, best in pool.map(look, seats) if best}
    variants = zh_cn([b[0] for b in found.values()])
    return {local: (variants[b[0]], b[1], round(b[2])) for local, b in found.items() if variants.get(b[0])}
