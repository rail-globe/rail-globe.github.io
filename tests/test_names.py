"""The names beside a feature's own (scripts/names.py): nz in simplified Chinese, ne in English,
and nl, a metro city's own name; n stays the key everything is found by."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import names as N

ROOT = Path(__file__).resolve().parents[1]
KR_HEAD = "kind\tko\tlon\tlat\tzh\tsource\tnote\twikidata\tzh_wikipedia_form\thanja_form\n"
UK_HEAD = "kind\tname_en\tlon\tlat\tname_zh\ttier\tsource\tnote\n"


def table(folder, g, text):
    (Path(folder) / f"{g}_names.tsv").write_text(text, encoding="utf-8")
    return N.Table(g, Path(folder))


class PutTest(unittest.TestCase):
    def test_only_what_is_known_and_differs_from_n(self):
        self.assertEqual(N.put({"n": "서울"}, "首尔", "Seoul"), {"n": "서울", "nz": "首尔", "ne": "Seoul"})
        self.assertEqual(N.put({"n": "大阪"}, "大阪", None), {"n": "大阪"})
        self.assertEqual(N.put({"n": "London"}, None, "London"), {"n": "London"})

    def test_never_with_brackets(self):
        self.assertEqual(N.put({"n": "김천(구미)"}, "金泉(龟尾)", "Gimcheon (Gumi)"), {"n": "김천(구미)"})

    def test_a_station_s_english_name_drops_station(self):
        self.assertEqual(N.english({"name:en": "Beijing South Railway Station"}, station=True), "Beijing South")
        self.assertEqual(N.english({"name:en": "Admiralty MTR Station"}, station=True), "Admiralty")
        self.assertEqual(N.english({"name:en": "Station Road"}, station=True), "Station Road")
        self.assertEqual(N.english({"name:en": "  Pudian   Road "}), "Pudian Road")
        self.assertIsNone(N.english({}))

    def test_a_japanese_name_zh_where_it_is_sound(self):
        self.assertEqual(N.sound_zh("岛本", "島本"), "岛本")
        self.assertIsNone(N.sound_zh("門前仲町站", "門前仲町"))          # the Japanese name itself, with 站
        self.assertIsNone(N.sound_zh("ゆりかもめ", "ゆりかもめ"))
        self.assertIsNone(N.sound_zh("Tokyo", "東京"))
        self.assertIsNone(N.sound_zh("东京（JR）", "東京"))
        self.assertEqual(N.sound_zh("京滨东北线", "JR京浜東北線"), "京滨东北线")


class TableTest(unittest.TestCase):
    def test_a_station_by_its_name_and_its_place(self):
        with tempfile.TemporaryDirectory() as d:
            t = table(d, "kr", KR_HEAD + "station\t양정\t129.0\t35.17\t杨亭\ts\t\t\t\t\nstation\t양정\t126.9\t37.5\t养正\ts\t\t\t\t\n")
            self.assertEqual(t.zh("station", "양정", (129.0002, 35.1702)), "杨亭")
            self.assertEqual(t.zh("station", "양정", (126.9, 37.5)), "养正")
            self.assertIsNone(t.zh("station", "양정", (127.5, 36.0)))           # no row within 50 m

    def test_a_line_by_its_name_and_a_name_with_two_rows_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            t = table(d, "kr", KR_HEAD + "rail line\t경부선\t\t\t京釜线\ts\t\t\t\t\nmetro line\t2호선\t\t\t釜山都市铁道2号线\ts\t\t\t\t\n"
                      "metro line\t3호선\t\t\t甲\ts\t\t\t\t\nrail line\t3호선\t\t\t乙\ts\t\t\t\t\n")
            self.assertEqual(t.zh("line", "경부선"), "京釜线")
            self.assertEqual(t.zh("line", "2호선"), "釜山都市铁道2号线")
            self.assertIsNone(t.zh("line", "3호선"))

    def test_a_chinese_name_with_brackets_of_its_own_takes_the_form_the_row_gives(self):
        with tempfile.TemporaryDirectory() as d:
            t = table(d, "kr", KR_HEAD + "station\t김천(구미)\t128.18\t36.11\t金泉(龟尾)\ts\twithout inner parentheses: 金泉龟尾 (or 金泉)\t\t\t\n"
                      "station\t어딘가(무엇)\t128.0\t36.0\t某地(某)\ts\tno other form\t\t\t\n")
            self.assertEqual(t.zh("station", "김천(구미)", (128.18, 36.11)), "金泉龟尾")
            self.assertIsNone(t.zh("station", "어딘가(무엇)", (128.0, 36.0)))

    def test_the_uk_rows_that_are_switched_off(self):
        with tempfile.TemporaryDirectory() as d:
            t = table(d, "uk", UK_HEAD + "station\tSwindon\t-1.785\t51.566\t斯温登\tC\ts\t\n"
                      "station\tChalfont\t-0.56\t51.66\t查尔方特\tB\ts\t\n"
                      "station\tWaddon\t-0.117\t51.367\t华顿\tA\ts\tFLAG wording: the title is in Hong Kong or Taiwan wording\n")
            self.assertEqual([row["own"] for row in t.rows], ["Swindon"])

    def test_no_table_no_names(self):
        with tempfile.TemporaryDirectory() as d:
            names = N.Names("kr", Path(d))
            self.assertEqual(names.station({"n": "서울", "g": "kr"}, {"name:en": "Seoul"}, (127.0, 37.55)), {"n": "서울", "g": "kr", "ne": "Seoul"})


class NamesTest(unittest.TestCase):
    def test_a_line_s_english_name_is_the_one_most_of_its_track_carries(self):
        names = N.Names("cn", Path(tempfile.gettempdir()) / "no-such-folder")
        names.add("京沪线", {"name:en": "Beijing–Shanghai Railway"}, 900)
        names.add("京沪线", {"name:en": "Jinghu Railway"}, 50)
        names.add("京沪线", {}, 400)
        self.assertEqual(names.line({"n": "京沪线"}), {"n": "京沪线", "ne": "Beijing–Shanghai Railway"})
        self.assertEqual(names.line({"n": "无名线"}), {"n": "无名线"})

    def test_the_uk_gets_no_english_name_and_china_no_chinese_one(self):
        uk = N.Names("uk", Path(tempfile.gettempdir()) / "no-such-folder")
        uk.add("East Coast Main Line", {"name:en": "East Coast Main Line (ECML)"}, 10)
        self.assertEqual(uk.line({"n": "East Coast Main Line"}), {"n": "East Coast Main Line"})
        cn = N.Names("cn", Path(tempfile.gettempdir()) / "no-such-folder")
        self.assertEqual(cn.station({"n": "上海虹桥"}, {"name:zh": "上海虹桥站", "name:en": "Shanghai Hongqiao"}, (121.3, 31.2)),
                         {"n": "上海虹桥", "ne": "Shanghai Hongqiao"})

    def test_a_metro_city_s_own_name(self):
        known = {"东京": ("東京", "Tokyo"), "北京": ("北京", "Beijing"), "伦敦": ("London", None)}
        self.assertEqual(N.name_city({"n": "东京"}, known, "jp"), {"n": "东京", "nl": "東京", "ne": "Tokyo"})
        self.assertEqual(N.name_city({"n": "北京"}, known, "cn"), {"n": "北京", "ne": "Beijing"})
        self.assertEqual(N.name_city({"n": "伦敦"}, known, "uk"), {"n": "伦敦", "nl": "London"})
        self.assertEqual(N.name_city({"n": "日本其他"}, known, "jp"), {"n": "日本其他"})


class GeneratedNamesTest(unittest.TestCase):
    """The names in the files as written."""

    def test_every_country_passes_the_check(self):
        for g in ("cn", "jp", "kr", "uk"):
            found, audit = N.check(g)
            self.assertFalse([text for bad, text in found if bad], g)
            self.assertEqual(audit["wrong"], [], g)

    def test_how_many_have_names(self):
        counts = {g: N.check(g)[1]["counts"] for g in ("cn", "jp", "kr", "uk")}
        self.assertGreater(counts["kr"]["station"]["nz"], 1200)
        self.assertGreater(counts["uk"]["station"]["nz"], 1100)
        self.assertGreater(counts["jp"]["station"]["ne"], 9000)
        self.assertGreater(counts["cn"]["station"]["ne"], 5000)
        self.assertEqual(counts["uk"]["station"]["ne"], 0)
        self.assertEqual(counts["cn"]["station"]["nz"], 0)

    def test_the_metro_cities_carry_their_own_names(self):
        cities = {c["n"]: c for g in ("jp_", "kr_", "uk_", "") for c in json.loads((ROOT / "data" / f"{g}metro_cities.json").read_text())}
        self.assertEqual((cities["东京"].get("nl"), cities["东京"].get("ne")), ("東京", "Tokyo"))
        self.assertEqual((cities["首尔"].get("nl"), cities["首尔"].get("ne")), ("서울", "Seoul"))
        self.assertEqual(cities["伦敦"].get("nl"), "London")
        self.assertEqual(cities["北京"].get("ne"), "Beijing")


if __name__ == "__main__":
    unittest.main()
