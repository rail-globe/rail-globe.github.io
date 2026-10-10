"""Which metro lines stop at a station (scripts/metro_stops.py), and the stations linked by it in
the routing network (scripts/build_graph.py)."""
import json
import math
import pickle
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from metro_stops import canon, lines_at, overrides, stops_of

ROOT = Path(__file__).resolve().parents[1]
M = 1 / 111320                     # a metre north, in degrees


class CanonTest(unittest.TestCase):
    def test_spellings_of_one_station(self):
        self.assertEqual(canon("平安里站"), "平安里")
        self.assertEqual(canon("盧押道 Luard Road"), "盧押道")
        self.assertEqual(canon("东环城路（在建）"), "东环城路")
        self.assertEqual(canon("機場"), "机场")
        self.assertEqual(canon("北站"), "北站")                   # too short to lose its 站


class LinesAtTest(unittest.TestCase):
    STOPS = {"19号线": [("平安里", "平安里", 116.3665, 39.9355)],          # its platform 350 m from the dot
             "2号线": [("长椿街", "长椿街", 116.3572, 39.8980)],
             "4号线": [("国图", "国图", 116.3250, 39.9430)]}

    def test_a_line_stops_where_a_stop_of_its_has_the_name(self):
        found = lines_at([("平安里", 116.36649, 39.93232)], self.STOPS)
        self.assertEqual(found, [["19号线"]])

    def test_a_line_that_passes_without_stopping_is_not_the_station_s(self):
        found = lines_at([("长椿街", 116.35721, 39.89804)], self.STOPS)
        self.assertEqual(found, [["2号线"]])                       # not the 19号线 under it

    def test_a_stop_named_otherwise_right_at_the_dot(self):
        self.assertEqual(lines_at([("国家图书馆", 116.3251, 39.9431)], self.STOPS), [["4号线"]])
        self.assertEqual(lines_at([("国家图书馆", 116.3250 + 400 * M, 39.9430)], self.STOPS), [[]])

    def test_dots_of_one_name_close_together_share_their_lines(self):
        stops = {"A": [("换乘", "换乘站", 116.0, 39.0)], "B": [("换乘", "换乘站", 116.0, 39.0 + 3000 * M)]}
        found = lines_at([("换乘站", 116.0, 39.0 + 1000 * M), ("换乘站", 116.0, 39.0 + 2000 * M)], stops)
        self.assertEqual(found, [["A", "B"], ["A", "B"]])

    def test_a_stop_a_source_gives(self):
        extra = [{"line": "7号线", "station": "中央公园", "at": [120.65616, 31.31593]}]
        self.assertEqual(lines_at([("中央公园", 120.65616, 31.31593)], {}, extra), [["7号线"]])

    def test_every_override_has_its_source(self):
        for row in overrides():
            self.assertTrue(row["source"].startswith("https://") and row["line"] and row["station"] and len(row["at"]) == 2, row)


class StopsOfTest(unittest.TestCase):
    def test_stop_and_platform_members_with_their_names(self):
        stopping = {"routes": {1: [("n", 10, "stop"), ("w", 20, "platform"), ("n", 11, "stop_entry_only")]},
                    "nodes": {10: ({"name": "东门站"}, 116.0, 39.0), 11: ({"name": "1"}, 116.1, 39.1)},
                    "platforms": {20: ({"name:zh": "西门"}, 116.05, 39.05)}, "areas": {11: "南门站"}}
        self.assertEqual(stops_of([1], stopping), {1: [("东门", "东门站", 116.0, 39.0), ("西门", "西门", 116.05, 39.05), ("南门", "南门站", 116.1, 39.1)]})


class GeneratedStopsTest(unittest.TestCase):
    """The stations as linked in data/graph.json."""

    @classmethod
    def setUpClass(cls):
        G = json.loads((ROOT / "data" / "graph.json").read_text())
        L, E = G["lines"], [tuple(G["edges"][5 * i:5 * i + 5]) for i in range(len(G["edges"]) // 5)]
        adj = {}
        for i, e in enumerate(E):
            adj.setdefault(e[0], []).append((e[1], i))
            adj.setdefault(e[1], []).append((e[0], i))
        cls.lines = {}
        for f in json.loads((ROOT / "data" / "metro_stations.geojson").read_text())["features"]:
            h = f["properties"].get("g")
            if h is None:
                continue
            lines = {L[E[e2][2]][0] for n, ei in adj.get(h, ()) if L[E[ei][2]][1] in "xy" for _, e2 in adj.get(n, ()) if L[E[e2][2]][1] in ("metro", "mrail")}
            cls.lines[(f["properties"]["n"], *f["geometry"]["coordinates"])] = lines

    def at(self, name, lon, lat):
        return next(v for k, v in self.lines.items() if k[0] == name and math.hypot(k[1] - lon, k[2] - lat) < 0.003)

    def test_the_cases_that_were_wrong(self):
        self.assertNotIn("北京地铁19号线", self.at("长椿街", 116.35721, 39.89804))
        self.assertNotIn("济南轨道交通3号线", self.at("王舍人立交桥", 117.1401, 36.72101))
        self.assertIn("北京地铁19号线", self.at("平安里", 116.36649, 39.93232))
        self.assertIn("苏州轨道交通7号线", self.at("中央公园", 120.65616, 31.31593))
        self.assertIn("苏州轨道交通7号线", self.at("黄天荡", 120.66031, 31.29893))
        self.assertIn("苏州轨道交通3号线", self.at("唯亭", 120.78483, 31.36645))


if __name__ == "__main__":
    unittest.main()
