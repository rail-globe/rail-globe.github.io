"""Japan's street tramways, and the rule that a station is drawn only where a drawn line passes it
(scripts/process_jp.py; scripts/country.py for Korea and the United Kingdom)."""
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from process_jp import METRO_MIN_KM, SAYS_WHOSE, metro_jk, terminus_track, tram_systems, with_a_line

ROOT = Path(__file__).resolve().parents[1]


def station(name, lon, lat, metro=False):
    props = {"n": name, "g": "jp", **({"m": 1} if metro else {})}
    return {"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [lon, lat]}}


class TramwayTest(unittest.TestCase):
    def test_a_tramway_is_of_the_urban_class(self):
        self.assertEqual(metro_jk(Counter(tram=40)), "urban")
        self.assertEqual(metro_jk(Counter(light_rail=30, tram=4)), "urban")
        self.assertEqual(metro_jk(Counter(subway=30, tram=4)), "subway")

    def test_a_name_that_does_not_say_whose_the_line_is(self):
        for name in ("広島電鉄本線", "函館市電本線", "都電荒川線", "長崎電気軌道本線", "とさでん交通後免線", "宇都宮芳賀ライトレール線"):
            self.assertTrue(SAYS_WHOSE.search(name), name)
        for name in ("東山本線", "清輝橋線", "桟橋線"):
            self.assertFalse(SAYS_WHOSE.search(name), name)

    def test_the_lines_of_one_system_hang_together_and_a_ride_is_on_its_own(self):
        ways = {1: ({}, [(0, 0), (1, 0)]), 2: ({}, [(1, 0), (1, 1)]), 3: ({}, [(1, 1), (2, 1)]), 9: ({}, [(50, 50), (51, 50)]),
                4: ({}, [(5, 5), (6, 5)]), 5: ({}, [(2, 1), (3, 3), (5, 5)])}       # 5: a junction's curve, with no name
        lines = {"本線": [1], "白島線": [2], "横川線": [3], "園内線": [9], "江波線": [4]}
        systems = tram_systems(lines, ways)
        self.assertEqual(systems["白島線"], {"本線", "白島線", "横川線"})
        self.assertEqual(systems["本線"], systems["横川線"])            # joined through the line between them
        self.assertEqual(systems["園内線"], {"園内線"})
        self.assertEqual(systems["江波線"], {"江波線"})                 # nothing named joins it to the rest
        self.assertEqual(tram_systems(lines, ways, track=[5])["江波線"], {"本線", "白島線", "横川線", "江波線"})   # the unnamed curve does
        self.assertEqual(METRO_MIN_KM, 2.0)


class TerminusTest(unittest.TestCase):
    LINE = ("metro", None, "小倉線")

    def ways(self, terminus_at):
        siding = {"railway": "monorail", "name": "小倉線", "service": "siding"}
        return {1: ({"railway": "monorail", "name": "小倉線"}, [(0, 0), (0.01, 0)]),
                2: (siding, [(0.01, 0), (terminus_at, 0)]),                  # on from where the running track stops
                3: (siding, [(terminus_at, 0), (terminus_at + 0.002, 0)]),   # beyond the station, to the depot
                4: (siding, [(0.005, 0), (0.005, 0.002)]),                   # a pocket track off the middle of the line
                5: ({"railway": "monorail", "name": "別の線", "service": "siding"}, [(0.01, 0), (0.018, 0.0001)])}

    def test_siding_tagged_track_into_a_terminus_is_the_line_s(self):
        stations = [({"name": "企救丘"}, 0.018, 0.00001), ({"name": "途中"}, 0.005, 0.0)]
        self.assertEqual(terminus_track({1: self.LINE}, self.ways(0.018), stations), {2: self.LINE})

    def test_not_where_the_running_track_reaches_the_station_already(self):
        self.assertEqual(terminus_track({1: self.LINE}, self.ways(0.0103), [({"name": "彩都西"}, 0.0103, 0.0)]), {})

    def test_not_without_a_station_at_its_end(self):
        self.assertEqual(terminus_track({1: self.LINE}, self.ways(0.018), [({"name": "途中"}, 0.005, 0.0)]), {})


class StationsOnLinesTest(unittest.TestCase):
    RAIL, METRO = [[(0, 0), (1, 0)]], [[(0, 0.5), (1, 0.5)]]

    def kept(self, *stations):
        return [f["properties"]["n"] for f in with_a_line(list(stations), self.RAIL, self.METRO)]

    def test_a_railway_station_needs_a_line_within_600_m(self):
        self.assertEqual(self.kept(station("on the line", 0.5, 0.0001), station("beside it", 0.5, 0.005), station("on a closed line", 0.5, 0.2)),
                         ["on the line", "beside it"])
        self.assertEqual(self.kept(station("by the metro only", 0.5, 0.503)), ["by the metro only"])

    def test_a_tram_stop_needs_a_line_of_its_own_layer_not_a_railway_nearby(self):
        self.assertEqual(self.kept(station("stop on its line", 0.5, 0.5001, True), station("stop with no line, 200 m from the railway", 0.5, 0.002, True)),
                         ["stop on its line"])

    def test_a_station_tagged_as_a_metro_station_on_a_railway_stays(self):
        self.assertEqual(self.kept(station("京急蒲田", 0.5, 0.0002, True)), ["京急蒲田"])

    def test_with_no_lines_drawn_nothing_is_kept(self):
        self.assertEqual(with_a_line([station("anywhere", 0.5, 0.0)], [], []), [])


class GeneratedTramwayDataTest(unittest.TestCase):
    def test_the_tramways_of_japan_are_urban_lines(self):
        lines = {line["n"]: line for city in json.loads((ROOT / "data" / "jp_metro_cities.json").read_text()) for line in city["lines"]}
        for name in ("都電荒川線", "広島電鉄本線", "広島電鉄宇品線", "広島電鉄白島線", "長崎電気軌道本線", "熊本市電幹線", "鹿児島市電谷山線", "函館市電本線",
                     "札幌市電山鼻線", "札幌市電都心線", "岡山電気軌道東山本線", "伊予鉄道城南線", "とさでん交通後免線", "とさでん交通桟橋線",
                     "阪堺電車阪堺線", "豊橋鉄道東田本線", "万葉線高岡軌道線", "宇都宮芳賀ライトレール線"):
            self.assertIn(name, lines)
            self.assertEqual(lines[name]["jk"], "urban", name)
        self.assertNotIn("京都市電", lines)                              # a museum's 700 m

    def test_kokura_line_is_drawn_to_its_terminus(self):
        stations = {f["properties"]["n"] for f in json.loads((ROOT / "data" / "jp_stations.geojson").read_text())["features"]}
        self.assertIn("企救丘", stations)
        line = next(l for city in json.loads((ROOT / "data" / "jp_metro_cities.json").read_text()) for l in city["lines"] if l["n"] == "北九州高速鉄道小倉線")
        self.assertGreaterEqual(line["km"], 9)

    def test_every_station_abroad_has_a_drawn_line_passing_it(self):
        for code in ("jp", "kr", "uk"):
            load = lambda name: json.loads((ROOT / "data" / f"{code}_{name}.geojson").read_text())["features"]
            parts = lambda feats: [co for f in feats for co in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]])]
            stations = load("stations")
            self.assertEqual(len(with_a_line(stations, parts(load("rail")), parts(load("metro")))), len(stations), code)

    def test_tokyo_s_arakawa_line_has_its_stops(self):
        stations = {f["properties"]["n"] for f in json.loads((ROOT / "data" / "jp_stations.geojson").read_text())["features"]}
        for name in ("三ノ輪橋", "町屋二丁目", "荒川二丁目", "王子駅前", "早稲田"):
            self.assertIn(name, stations)


if __name__ == "__main__":
    unittest.main()
