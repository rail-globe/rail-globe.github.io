"""data/cities.json, the city labels of the map (scripts/build_cities.py)."""
import json
import re
import subprocess
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CITIES = json.loads((ROOT / "data" / "cities.json").read_text())
# The 70 cities the map began with, placed by hand: whatever is added, these stay as they are.
HAND = [["北京", 116.40, 39.90, 1], ["天津", 117.20, 39.08, 1], ["上海", 121.47, 31.23, 1], ["重庆", 106.55, 29.56, 1],
        ["石家庄", 114.51, 38.04, 1], ["太原", 112.55, 37.87, 1], ["呼和浩特", 111.75, 40.84, 1], ["沈阳", 123.43, 41.80, 1],
        ["长春", 125.32, 43.82, 1], ["哈尔滨", 126.53, 45.80, 1], ["南京", 118.80, 32.06, 1], ["杭州", 120.16, 30.27, 1],
        ["合肥", 117.23, 31.82, 1], ["福州", 119.30, 26.08, 1], ["南昌", 115.86, 28.68, 1], ["济南", 117.00, 36.65, 1],
        ["郑州", 113.63, 34.75, 1], ["武汉", 114.31, 30.59, 1], ["长沙", 112.94, 28.23, 1], ["广州", 113.26, 23.13, 1],
        ["南宁", 108.37, 22.82, 1], ["海口", 110.35, 20.02, 1], ["成都", 104.07, 30.57, 1], ["贵阳", 106.63, 26.65, 1],
        ["昆明", 102.83, 24.88, 1], ["拉萨", 91.13, 29.65, 1], ["西安", 108.94, 34.34, 1], ["兰州", 103.83, 36.06, 1],
        ["西宁", 101.78, 36.62, 1], ["银川", 106.23, 38.49, 1], ["乌鲁木齐", 87.62, 43.83, 1], ["香港", 114.17, 22.32, 1],
        ["澳门", 113.54, 22.19, 2], ["台北", 121.56, 25.04, 1], ["深圳", 114.06, 22.54, 2], ["青岛", 120.38, 36.07, 2],
        ["大连", 121.61, 38.91, 2], ["厦门", 118.09, 24.48, 2], ["宁波", 121.55, 29.87, 2], ["徐州", 117.28, 34.20, 2],
        ["苏州", 120.59, 31.30, 2], ["三亚", 109.51, 18.25, 2], ["喀什", 75.99, 39.47, 2], ["哈密", 93.51, 42.83, 2],
        ["格尔木", 94.90, 36.40, 2], ["包头", 109.84, 40.66, 2], ["赣州", 114.93, 25.83, 2], ["襄阳", 112.14, 32.04, 2],
        ["宜昌", 111.29, 30.69, 2], ["桂林", 110.29, 25.27, 2], ["汕头", 116.68, 23.35, 2], ["温州", 120.70, 28.00, 2],
        ["齐齐哈尔", 123.92, 47.35, 2], ["满洲里", 117.43, 49.59, 2], ["二连浩特", 111.98, 43.65, 2], ["霍尔果斯", 80.42, 44.21, 2],
        ["日喀则", 88.88, 29.27, 2], ["大理", 100.27, 25.61, 2], ["景洪", 100.80, 22.01, 2], ["高雄", 120.30, 22.63, 2],
        ["台中", 120.68, 24.14, 2], ["牡丹江", 129.63, 44.55, 2], ["延吉", 129.51, 42.89, 2], ["烟台", 121.45, 37.46, 2],
        ["洛阳", 112.45, 34.62, 2], ["宝鸡", 107.24, 34.36, 2], ["酒泉", 98.49, 39.73, 2], ["库尔勒", 86.15, 41.76, 2],
        ["怀化", 110.00, 27.57, 2], ["柳州", 109.42, 24.33, 2]]
HAND = [{"n": n, "at": [x, y], "r": r} for n, x, y, r in HAND]
# Where a country lies: every one of its cities is in there.
BOX = {"cn": (73, 15, 136, 54), "jp": (122, 24, 146, 46), "kr": (124, 33, 131, 39), "uk": (-9, 49, 2, 61)}
# Abroad: how many cities, and how many of rank 1 (the capital and the cities the world knows).
ABROAD = {"jp": (47, 6), "kr": (16, 2), "uk": (7, 5)}
country = lambda e: e.get("g", "cn")
FIELDS = ("n", "at", "r", "g", "side", "nz", "ne", "m")


class Cities(unittest.TestCase):
    def test_the_hand_made_cities_stay_as_they_were(self):
        # their names, places and ranks; an English name may be added
        self.assertEqual([{k: e[k] for k in ("n", "at", "r")} for e in CITIES[:70]], HAND)
        self.assertTrue(all(set(e) <= {"n", "at", "r", "ne"} for e in CITIES[:70]))
        published = subprocess.run(["git", "show", "b053ec3:data/cities.json"], cwd=ROOT, capture_output=True, text=True)
        if published.returncode == 0:                 # (where the history is at hand: the file as it was published)
            self.assertEqual([{"n": n, "at": [x, y], "r": r} for n, x, y, r in json.loads(published.stdout)], HAND)

    def test_every_entry_is_whole(self):
        for e in CITIES:
            self.assertTrue(set(e) <= set(FIELDS) and {"n", "at", "r"} <= set(e), e)
            for k in ("n", "nz", "ne", "m"):
                if k in e:
                    self.assertTrue(isinstance(e[k], str) and e[k].strip() == e[k] and e[k], e)
            self.assertIn(e["r"], (1, 2, 3), e)
            self.assertIn(country(e), BOX, e)
            w, s, east, north = BOX[country(e)]
            x, y = e["at"]
            self.assertTrue(w <= x <= east and s <= y <= north, e)
            self.assertEqual([round(x, 2), round(y, 2)], e["at"], e)
            # an English name is given only where it is another (a Chinese one abroad always: 大阪 is 大阪)
            self.assertNotEqual(e["n"], e.get("ne"), e)

    def test_one_label_of_a_name_in_a_country(self):
        twice = [k for k, n in Counter((country(e), e["n"]) for e in CITIES).items() if n > 1]
        self.assertEqual(twice, [])

    def test_china_has_every_prefecture_level_unit_once(self):
        cn = [e for e in CITIES if country(e) == "cn"]
        # 333 units; 57 of their seats are among the hand-made cities, the other 276 are rank 3
        self.assertEqual(Counter(e["r"] for e in cn), {1: 33, 2: 37, 3: 276})
        names = {e["n"] for e in cn}
        # the seat of a prefecture or a league is labelled, not the unit
        for seat in "恩施 吉首 西昌 马尔康 康定 兴义 凯里 都匀 蒙自 文山 楚雄 芒市 泸水 香格里拉 临夏 合作 德令哈 玉树 伊宁 博乐 阿图什 昌吉 塔城 阿勒泰 阿克苏 和田 乌兰浩特 锡林浩特 巴彦浩特 加格达奇 狮泉河".split():
            self.assertIn(seat, names)
        for e in cn:
            self.assertRegex(e["n"], r"^[一-鿿]{2,5}$")
            self.assertFalse(re.search(r"(自治州|地区|盟)$", e["n"]), e)
            self.assertNotIn("nz", e)                 # (the name is Chinese)
        self.assertEqual([e["n"] for e in cn if e["r"] == 3 and e["n"].endswith("市")], ["芒市"])
        # nothing was added in Hong Kong, Macau or Taiwan: what lies there is hand-made
        for w, south, east, north in ((113.82, 22.14, 114.45, 22.57), (113.52, 22.10, 113.60, 22.22), (119.9, 21.8, 122.1, 25.4)):
            for e in cn:
                if w <= e["at"][0] <= east and south <= e["at"][1] <= north:
                    self.assertIn({k: e[k] for k in ("n", "at", "r")}, HAND)

    def test_abroad_is_the_listed_cities_and_no_others(self):
        for g, (count, first) in ABROAD.items():
            there = [e for e in CITIES if country(e) == g]
            self.assertEqual(len(there), count, g)
            self.assertEqual(Counter(e["r"] for e in there), {1: first, 2: count - first}, g)
        rank1 = {g: [(e["n"], e["nz"]) for e in CITIES if country(e) == g and e["r"] == 1] for g in ABROAD}
        self.assertEqual(rank1["jp"], [("東京", "东京"), ("大阪", "大阪"), ("京都", "京都"), ("名古屋", "名古屋"), ("札幌", "札幌"), ("福岡", "福冈")])
        self.assertEqual(rank1["kr"], [("서울", "首尔"), ("부산", "釜山")])
        self.assertEqual(rank1["uk"], [("London", "伦敦"), ("Edinburgh", "爱丁堡"), ("Manchester", "曼彻斯特"), ("Birmingham", "伯明翰"), ("Glasgow", "格拉斯哥")])

    def test_the_names_abroad_are_in_their_form(self):
        han = r"[一-鿿]+"
        for e in CITIES:
            g = country(e)
            if g != "cn":                             # every place abroad has its Chinese name, from the script's table
                self.assertRegex(e["nz"], f"^{han}$", e)
            if g == "jp":                             # its own name in kanji or kana
                self.assertRegex(e["n"], r"^[一-鿿ぁ-んァ-ン]+$", e)
            elif g == "kr":
                self.assertRegex(e["n"], r"^[가-힣]+$", e)
            elif g == "uk":                           # its own name is the English one
                self.assertRegex(e["n"], r"^[A-Z][A-Za-z -]*[a-z]$", e)
                self.assertNotIn("ne", e)
            if "ne" in e:                             # English: Latin letters, words that begin with a capital
                self.assertRegex(e["ne"], r"^[A-Z][A-Za-z'’-]*( [A-Z][A-Za-z'’-]*)*$", e)
        # a name that keeps to one side of its dot (Japan's view: 京都 just above 大阪, 名古屋 to its right)
        self.assertEqual({e["n"]: e["side"] for e in CITIES if "side" in e}, {"大阪": "left", "京都": "above-left"})
        # every place outside China and nearly every one inside has its English name (the extract has none for a few)
        without = sorted(e["n"] for e in CITIES if "ne" not in e and country(e) != "uk")
        self.assertLessEqual(len(without), 8, without)

    def test_a_city_with_a_metro_is_named_as_the_metro_list_names_it(self):
        for g, file in (("cn", "metro_cities.json"), ("jp", "jp_metro_cities.json"), ("kr", "kr_metro_cities.json"), ("uk", "uk_metro_cities.json")):
            metro = {c["n"] for c in json.loads((ROOT / "data" / file).read_text())}
            for e in CITIES:
                if country(e) != g:
                    continue
                if "m" in e:                          # the label says which metro city it is: the one of its Chinese name
                    self.assertIn(e["m"], metro, e)
                    self.assertEqual(e["m"], e["nz"], e)
                elif g != "cn":
                    self.assertNotIn(e["nz"], metro, e)
        # Korea's six metro cities and the capital's metro abroad are all labelled
        known = {(country(e), e.get("m", e["n"])) for e in CITIES}
        for g, name in (("kr", "首尔"), ("kr", "釜山"), ("kr", "大邱"), ("kr", "仁川"), ("kr", "光州"), ("kr", "大田"), ("jp", "东京"), ("jp", "大阪"), ("uk", "伦敦")):
            self.assertIn((g, name), known)


if __name__ == "__main__":
    unittest.main()
