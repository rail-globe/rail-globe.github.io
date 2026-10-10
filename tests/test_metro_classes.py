"""China's urban lines: the three classes (地铁 / 轻轨 / 市郊), and how a tram line is named (scripts/metro_classes.py)."""
import json
import sys
import unittest
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from metro_classes import is_tram, kind_of, light, numbered, tram_key, tram_name

ROOT = Path(__file__).resolve().parents[1]


class ClassTest(unittest.TestCase):
    def test_a_line_is_of_the_kind_most_of_its_track_is(self):
        self.assertEqual(kind_of("长春轨道交通3号线", {"light_rail": 67.5}), "urban")
        self.assertEqual(kind_of("沈阳有轨电车1号线", {"tram": 37.8}), "urban")
        self.assertEqual(kind_of("上海地铁1号线", {"subway": 76.0}), "subway")
        self.assertEqual(kind_of("港鐵東鐵綫", {"rail": 90.0}), "subway")              # a metro on railway track
        self.assertEqual(kind_of("", {}), "subway")

    def test_one_stretch_tagged_otherwise_does_not_move_a_line(self):
        self.assertEqual(kind_of("某地铁1号线", {"subway": 40.0, "light_rail": 3.0}), "subway")
        self.assertEqual(kind_of("某轻轨1号线", {"light_rail": 40.0, "subway": 3.0, None: 1.0}), "urban")
        self.assertFalse(light({"subway": 5.0, "light_rail": 5.0}))                     # a tie is not most

    def test_monorail_and_maglev_are_metro(self):
        self.assertEqual(kind_of("重庆轨道交通3号线", {"monorail": 129.3}), "subway")
        self.assertEqual(kind_of("芜湖轨道交通1号线", {"monorail": 60.0}), "subway")
        self.assertEqual(kind_of("上海磁浮示范运营线", {"monorail": 59.8}), "subway")      # OSM has the maglev's track as monorail
        self.assertEqual(kind_of("长沙磁浮快线", {"maglev": 36.7}), "subway")

    def test_a_people_mover_is_light_rail_whatever_its_track_is_tagged(self):
        self.assertEqual(kind_of("大王山云巴", {"monorail": 16.1}), "urban")
        self.assertEqual(kind_of("坪山云巴1号线", {"light_rail": 17.1}), "urban")
        self.assertEqual(kind_of("济南轨道交通云巴线", {"light_rail": 61.1}), "urban")

    def test_a_train_on_railway_track_is_suburban(self):
        self.assertEqual(kind_of("北京市郊铁路S2线", {"rail": 1}, "s"), "suburban")
        self.assertEqual(kind_of("广清城际线", {"rail": 1}, "m"), "suburban")
        self.assertEqual(kind_of("港鐵東鐵綫", {"rail": 90.0}), "subway")                # a metro's own line on railway track

    def test_a_tram_is_known_by_its_track_or_its_name(self):
        self.assertTrue(is_tram("大连有轨电车201路", {"tram": 23.4}))
        self.assertTrue(is_tram("天水有轨电车1号线", {"tram": 48.6}))
        self.assertTrue(is_tram("广州黄埔有轨电车1号线", {"light_rail": 28.6}))            # mapped as light rail, a tram by name
        self.assertTrue(is_tram("香港電車北角至石塘咀", {"tram": 16.2}))
        self.assertFalse(is_tram("輕鐵505綫", {"light_rail": 11.8}))
        self.assertFalse(is_tram("长春轨道交通3号线", {"light_rail": 67.5}))
        self.assertFalse(is_tram("北京地铁西郊线", {"light_rail": 17.7}))


class TramNameTest(unittest.TestCase):
    def test_a_name_of_its_own_is_kept(self):
        self.assertEqual(tram_name("沈阳有轨电车1号线", "1", {"沈阳有轨电车": 18.9}, "沈阳有轨电车"), "沈阳有轨电车1号线")
        self.assertEqual(tram_name("光谷有轨电车L1线", "L1", {}, "光谷有轨电车"), "光谷有轨电车L1线")
        self.assertEqual(tram_name("香港電車北角至石塘咀", "", {"香港電車": 8.1}, "香港電車", "香港電車有限公司"), "香港電車北角至石塘咀")
        self.assertEqual(tram_name("亦庄新城现代有轨电车T1线", "T1", {}, "", "北京亦庄公交有轨电车有限责任公司"), "亦庄新城现代有轨电车T1线")

    def test_a_route_without_a_name_is_named_after_its_system_and_number(self):
        self.assertEqual(tram_name("", "54", {"长春有轨电车": 7.4}), "长春有轨电车54路")
        self.assertEqual(tram_name("", "T1", {"深圳有轨电车": 11.0}, "深圳有轨电车"), "深圳有轨电车T1线")
        self.assertEqual(tram_name("", "M1", {"红河有轨电车一号线": 13.1}, "", "红河有轨电车公司"), "红河有轨电车一号线")   # the track names the line
        self.assertEqual(tram_name("", "4", {"文山州城市轨道交通现代有轨电车4号线": 12.0, "": 0.3}), "文山州城市轨道交通现代有轨电车4号线")
        self.assertEqual(tram_name("", "2", {}), "")                                                              # nothing to name it by

    def test_numbers(self):
        self.assertEqual([numbered(r) for r in ("54", "202", "1", "T1", "L2", "云巴线", "")], ["54路", "202路", "1号线", "T1线", "L2线", "云巴线", ""])

    def test_a_bus_company_s_tram_route_reads_as_a_tram_line(self):
        self.assertEqual(tram_name("大连公交201路", "201", {"201": 8.2}, "大连公交", "大连公交电车分公司"), "大连有轨电车201路")

    def test_a_district_s_system_takes_its_city_in_front(self):
        self.assertEqual(tram_name("高新有轨电车1号线", "", {}, "苏州高新区有轨电车", "苏州高新有轨电车"), "苏州高新有轨电车1号线")
        self.assertEqual(tram_name("高新有轨电车2号线", "", {}, "", "苏州高新有轨电车"), "苏州高新有轨电车2号线")
        self.assertEqual(tram_name("黄埔有轨电车1号线", "THP1", {}, "广州地铁", "广州有轨电车有限责任公司"), "广州黄埔有轨电车1号线")
        self.assertEqual(tram_name("海珠有轨1号线", "THZ1", {}, "广州地铁", "广州有轨电车有限责任公司"), "广州海珠有轨1号线")
        self.assertEqual(tram_name("南海有轨电车1号线", "TNH1", {}, "佛山有轨电车", "佛山市轨道交通发展有限公司"), "佛山南海有轨电车1号线")
        self.assertEqual(tram_name("高明区现代有轨电车示范线", "TGM1", {}, "", "佛山市轨道交通发展有限公司运营事业总部"), "佛山高明区现代有轨电车示范线")
        self.assertEqual(tram_name("有轨电车T1线", "T1", {}, "三亚轨道交通", "三亚市轨道交通有限公司"), "三亚有轨电车T1线")

    def test_a_city_already_in_the_name_is_not_put_there_twice(self):
        self.assertEqual(tram_name("南京河西有轨电车", "HEXI", {}, "南京有轨电车"), "南京河西有轨电车")
        self.assertEqual(tram_name("淮安有轨电车1号线", "T1", {}, "淮安轨道交通"), "淮安有轨电车1号线")
        self.assertEqual(tram_name("松江有轨电车1号线", "T1", {}, "松江有轨电车", "上海申凯公共交通运营管理有限公司"), "松江有轨电车1号线")
        self.assertEqual(tram_name("黄石现代有轨电车", "", {}, "黄石轨道交通", "黄石市城市轨道交通运营责任有限公司"), "黄石现代有轨电车")

    def test_two_spellings_of_one_line(self):
        self.assertEqual(tram_key("嘉兴有轨电车T1线"), tram_key("嘉兴有轨电车1号线"))
        self.assertNotEqual(tram_key("沈阳有轨电车1号线"), tram_key("沈阳有轨电车2号线"))
        self.assertNotEqual(tram_key("沈阳有轨电车1号线"), tram_key("大连有轨电车201路"))


class GeneratedChinaMetroTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.features = [f["properties"] for f in json.loads((ROOT / "data" / "metro.geojson").read_text())["features"]]
        cls.cities = json.loads((ROOT / "data" / "metro_cities.json").read_text())
        cls.lines = {line["n"]: line for city in cls.cities for line in city["lines"]}

    def test_every_feature_and_every_listed_line_has_one_of_the_three_classes(self):
        self.assertEqual({p.get("jk") for p in self.features}, {"subway", "urban", "suburban"})
        self.assertEqual({line.get("jk") for line in self.lines.values()}, {"subway", "urban", "suburban"})
        self.assertEqual(Counter(line["jk"] for city in self.cities for line in city["lines"]), {"subway": 352, "urban": 74, "suburban": 16})
        kinds = defaultdict(set)
        for p in self.features:
            kinds[(p["ct"], p["n"])].add(p["jk"])
        self.assertFalse({k: v for k, v in kinds.items() if len(v) > 1})                 # one class to a line
        for p in self.features:
            self.assertEqual(self.lines[p["n"]]["jk"], p["jk"], p["n"])

    def test_the_lines_named_when_the_classes_were_decided(self):
        for name in ("重庆轨道交通2号线", "重庆轨道交通3号线", "芜湖轨道交通1号线", "芜湖轨道交通2号线", "上海磁浮示范运营线", "长沙磁浮快线", "北京地铁S1线",
                     "港鐵屯馬綫", "广州地铁18号线"):
            self.assertEqual(self.lines[name]["jk"], "subway", name)
        for name in ("北京市郊铁路S2线", "广清城际线"):
            self.assertEqual(self.lines[name]["jk"], "suburban", name)
        for name in ("长春轨道交通3号线", "长春轨道交通4号线", "长春轨道交通8号线", "輕鐵505綫", "澳門輕軌氹仔線", "高雄環狀輕軌",
                     "济南轨道交通云巴线", "西安高新云巴线", "璧山云巴1号线", "坪山云巴1号线", "大王山云巴"):
            self.assertEqual(self.lines[name]["jk"], "urban", name)

    def test_the_trains_on_railway_track_are_the_suburban_class(self):
        on_railway = {name for name, line in self.lines.items() if line.get("k") in ("s", "m")}
        self.assertEqual(len(on_railway), 16)
        self.assertEqual(on_railway, {name for name, line in self.lines.items() if line["jk"] == "suburban"})
        for p in self.features:
            self.assertEqual(p["jk"] == "suburban", p.get("k") in ("s", "m"), p["n"])

    def test_the_trams_are_there_as_light_rail_under_their_cities(self):
        of = {line["n"]: city["n"] for city in self.cities for line in city["lines"]}
        for name, city in (("沈阳有轨电车1号线", "沈阳"), ("苏州高新有轨电车1号线", "苏州"), ("大连有轨电车201路", "大连"), ("光谷有轨电车L1线", "武汉"),
                           ("长春有轨电车54路", "长春"), ("松江有轨电车1号线", "上海"), ("广州黄埔有轨电车1号线", "广州"), ("佛山南海有轨电车1号线", "佛山"),
                           ("南京河西有轨电车", "南京"), ("香港電車筲箕灣至堅尼地城", "香港")):
            self.assertEqual(self.lines[name]["jk"], "urban", name)
            self.assertEqual(of[name], city, name)

    def test_sightseeing_lines_and_rides_are_not_drawn(self):
        for name in self.lines:
            self.assertNotRegex(name, r"旅游|观光|文旅|小火车|前门大街|氢春号|氢淞号|华为")

    def test_tram_stops_are_marked_and_the_stations_are_not(self):
        stations = json.loads((ROOT / "data" / "metro_stations.geojson").read_text())["features"]
        marked = [f["properties"] for f in stations if f["properties"].get("t")]
        self.assertGreater(len(marked), 300)
        self.assertEqual(Counter(bool(p.get("t")) for p in (f["properties"] for f in stations))[False], len(stations) - len(marked))
        first = next(i for i, f in enumerate(stations) if f["properties"].get("t"))
        self.assertTrue(all(f["properties"].get("t") for f in stations[first:]))          # after the stations, which keep their order


if __name__ == "__main__":
    unittest.main()
