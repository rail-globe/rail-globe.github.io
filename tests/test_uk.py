"""United Kingdom: how track and route relations become lines and their colours (scripts/process_uk.py)."""
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from process_uk import HIGH_SPEED, LINE_COLOURS, kind_of, line_colours, line_of_route, plain_name

ROOT = Path(__file__).resolve().parents[1]


class NameTest(unittest.TestCase):
    def test_a_branch_or_a_direction_in_brackets_is_the_same_line(self):
        self.assertEqual(plain_name("Chatham Main Line (Ramsgate Branch)"), "Chatham Main Line")
        self.assertEqual(plain_name("Merseyrail Northern Line (Up Ormskirk)"), "Merseyrail Northern Line")
        self.assertEqual(plain_name("Derby to Birmingham (Proof House Junction) Line"), "Derby to Birmingham Line")

    def test_one_line_under_several_spellings(self):
        self.assertEqual(plain_name("Channel Tunnel Rail Link"), "High Speed 1")
        self.assertEqual(plain_name("Elizabeth Line"), plain_name("Elizabeth line"))
        self.assertEqual(plain_name("Tunnel sous la Manche / Channel Tunnel ‒ Tunnel Ferroviaire Nord / Running Tunnel North"), "Channel Tunnel")

    def test_a_structure_named_for_itself_is_no_line(self):
        self.assertEqual(plain_name("Severn Tunnel"), "")
        self.assertEqual(plain_name("Ribblehead Viaduct"), "")
        self.assertEqual(plain_name("Settle-Carlisle Railway"), "Settle-Carlisle Railway")     # a hyphen in a name is no dash
        self.assertEqual(plain_name("Weaver Junction and Liverpool Line"), "Weaver Junction and Liverpool Line")
        self.assertEqual(plain_name(None), "")

    def test_a_name_that_says_which_track_is_no_line(self):
        for name in ("Down Fast", "Up Slow", "Up Goods", "Down & Up Tinsley", "CTRL Relief", "Kilburn Up & Down Goods Loop", "Yatton Down Loop", "Whitrope Siding"):
            self.assertEqual(plain_name(name), "", name)
        for name in ("Catford Loop", "Hertford Loop Line", "Northampton Loop Line", "Weston-super-Mare Loop", "Uckfield Branch"):
            self.assertEqual(plain_name(name), name)


class KindTest(unittest.TestCase):
    key = staticmethod(lambda **tags: tuple(sorted(tags.items())))

    def test_a_line_is_a_main_line_or_a_branch_by_most_of_its_track(self):
        self.assertEqual(kind_of("A", Counter({self.key(railway="rail", usage="main"): 80, self.key(railway="rail", usage="branch"): 20})), "main")
        self.assertEqual(kind_of("A", Counter({self.key(railway="rail", usage="branch"): 30, self.key(railway="rail"): 5})), "branch")

    def test_preserved_narrow_gauge_and_tourist_lines_are_heritage(self):
        self.assertEqual(kind_of("A", Counter({self.key(railway="narrow_gauge"): 20})), "heritage")
        self.assertEqual(kind_of("A", Counter({self.key(**{"railway": "rail", "railway:preserved": "yes"}): 12, self.key(railway="rail", usage="branch"): 3})), "heritage")
        self.assertEqual(kind_of("A", Counter({self.key(railway="rail", usage="tourism"): 9})), "heritage")
        self.assertEqual(kind_of("High Speed 1", Counter({self.key(railway="rail", usage="main"): 9})), "hs")


class RouteTest(unittest.TestCase):
    def test_a_route_is_named_by_its_master(self):
        self.assertEqual(line_of_route({"name": "Bakerloo Line: Elephant & Castle → Harrow & Wealdstone", "network": "London Underground", "colour": "#B36305"},
                                       {"name": "Bakerloo line", "colour": "#ae6017"}), ("London Underground", "Bakerloo line", "#b36305"))

    def test_without_a_master_the_name_before_the_colon(self):
        self.assertEqual(line_of_route({"name": "NET: Hucknall → Toton Lane", "network": "NET", "colour": "#003828", "ref": "1"}, {}), ("NET", "NET", "#003828"))

    def test_a_company_brand_is_not_a_line_colour(self):
        routes = [("Great Western Railway", "#0a493e", "National Rail")] * 18 + [("Great Western Railway", "#32366d", "National Rail")] * 36
        self.assertEqual(line_colours(routes), set())                                      # one or two colours: a brand

    def test_a_company_that_colours_its_routes_differently_is_colouring_lines(self):
        scotrail = [("ScotRail", col, "National Rail") for col in ("#0066b3", "#e0a3ba", "#dfca32", "#0089cf", "#0056a0", "#ee4d9b") for _ in range(4)]
        self.assertEqual(len(line_colours(scotrail)), 6)

    def test_the_colour_most_of_a_companys_routes_share_is_its_brand(self):
        trains = [("West Midlands Trains", "#ff8300", "National Rail")] * 28 + [("West Midlands Trains", col, "National Rail") for col in ("#2eac6e", "#009c90", "#93ab7c", "#94c122", "#1e90ff") for _ in range(4)]
        good = line_colours(trains)
        self.assertNotIn(("West Midlands Trains", "#ff8300"), good)
        self.assertIn(("West Midlands Trains", "#2eac6e"), good)

    def test_a_network_of_a_few_lines_with_official_colours_counts_whoever_runs_it(self):
        routes = [("Merseyrail", "#00a654", "Merseyrail Wirral Line (Chester)"), ("Northern", "#ed1c24", "Merseyrail City Line (Wigan)")]
        self.assertEqual(line_colours(routes, LINE_COLOURS), {("Merseyrail", "#00a654"), ("Northern", "#ed1c24")})
        self.assertEqual(line_colours(routes), set())


class GeneratedUKDataTest(unittest.TestCase):
    def test_generated_lines_are_scoped_to_the_uk_and_classified(self):
        for name, kinds in (("uk_rail.geojson", {"hs", "main", "branch", "heritage"}), ("uk_metro.geojson", {"subway", "urban"})):
            features = json.loads((ROOT / "data" / name).read_text())["features"]
            self.assertTrue(features, name)
            self.assertEqual({f["properties"].get("g") for f in features}, {"uk"}, name)
            self.assertLessEqual({f["properties"].get("jk") for f in features}, kinds, name)
        self.assertEqual({f["properties"]["g"] for f in json.loads((ROOT / "data" / "uk_stations.geojson").read_text())["features"]}, {"uk"})

    def test_generated_lines_follow_the_one_colour_rule(self):
        features = [f["properties"] for f in json.loads((ROOT / "data" / "uk_rail.geojson").read_text())["features"]]
        fast = [p for p in features if p["jk"] == "hs"]
        self.assertEqual({p["n"] for p in fast}, set(HIGH_SPEED))
        self.assertEqual({(p["c"], p["d"], p.get("e")) for p in fast}, {("hsr300", 300, 1)})        # a top speed, marked as such
        self.assertFalse([p["n"] for p in fast if "lc" in p])
        trunk = [p for p in features if p["n"] in ("West Coast Main Line", "East Coast Main Line", "Great Western Main Line")]
        self.assertTrue(trunk)
        self.assertFalse([p["n"] for p in trunk if "lc" in p or "d" in p])                        # no company colour, no band
        self.assertFalse([p["n"] for p in features if "o" in p])
        self.assertEqual(json.loads((ROOT / "data" / "uk_facts.json").read_text())["bands"], ["hsr300"])
        self.assertFalse((ROOT / "data" / "uk_operators.json").exists())

    def test_generated_metros_have_the_underground_in_its_colours(self):
        cities = {c["n"]: c for c in json.loads((ROOT / "data" / "uk_metro_cities.json").read_text())}
        london = {l["n"]: l for l in cities["伦敦"]["lines"]}
        for name in ("Bakerloo line", "Central line", "Victoria line", "Docklands Light Railway"):
            self.assertIn(name, london)
        self.assertEqual(len({london[n]["col"] for n in ("Bakerloo line", "Central line", "Victoria line")}), 3)
        self.assertEqual(london["Central line"]["jk"], "subway")
        self.assertEqual(london["Docklands Light Railway"]["jk"], "urban")
        for city in ("曼彻斯特", "纽卡斯尔", "格拉斯哥"):
            self.assertIn(city, cities)


if __name__ == "__main__":
    unittest.main()
