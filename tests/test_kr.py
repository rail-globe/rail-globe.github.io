"""South Korea: how its track becomes lines, and which lines are fast (scripts/process_kr.py)."""
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from process_kr import HIGH_SPEED, kind_of, plain_name, speed_of, top_speed

ROOT = Path(__file__).resolve().parents[1]
key = lambda **tags: tuple(sorted(tags.items()))
FAST_260 = Counter({key(railway="rail", usage="main", highspeed="yes", maxspeed="260"): 70, key(railway="rail", usage="main", maxspeed="150"): 30})


class KoreaTest(unittest.TestCase):
    def test_a_structure_named_for_itself_is_no_line(self):
        self.assertEqual(plain_name("금정터널"), "")
        self.assertEqual(plain_name("한강철교"), "")
        self.assertEqual(plain_name("경부선 (상행)"), "경부선")
        self.assertEqual(plain_name(None), "")

    def test_the_high_speed_lines_are_known_by_name(self):
        for name in ("경부고속선", "호남고속선", "수서평택고속선"):
            self.assertEqual(kind_of(name, Counter({key(railway="rail", usage="main"): 10})), "hs")
        self.assertEqual(speed_of("경부고속선", "hs", Counter())[:2], (350, False))
        self.assertTrue(HIGH_SPEED["호남고속선"][1])                    # only a top speed so far: marked to verify

    def test_a_line_mostly_signed_as_high_speed_is_semi_high_speed_by_its_signed_speed(self):
        self.assertEqual(top_speed(FAST_260), 260)
        self.assertEqual(kind_of("중앙선", FAST_260), "semi")
        self.assertEqual(speed_of("중앙선", "semi", FAST_260), (260, True, None))        # a top speed, no source: to verify

    def test_a_connecting_line_signed_for_300_belongs_with_the_high_speed_lines(self):
        link = Counter({key(railway="rail", usage="main", highspeed="yes", maxspeed="305"): 3})
        self.assertEqual(kind_of("시흥연결선", link), "hs")
        self.assertEqual(speed_of("시흥연결선", "hs", link), (305, True, None))

    def test_other_lines_are_main_lines_or_branches_and_have_no_speed(self):
        self.assertEqual(kind_of("경부선", Counter({key(railway="rail", usage="main"): 9})), "main")
        self.assertEqual(kind_of("정선선", Counter({key(railway="rail", usage="branch"): 9})), "branch")
        self.assertIsNone(speed_of("경부선", "main", Counter()))


class GeneratedKoreaDataTest(unittest.TestCase):
    def test_generated_lines_are_scoped_to_korea_and_classified(self):
        for name, kinds in (("kr_rail.geojson", {"hs", "semi", "main", "branch"}), ("kr_metro.geojson", {"subway", "urban"})):
            features = json.loads((ROOT / "data" / name).read_text())["features"]
            self.assertTrue(features, name)
            self.assertEqual({f["properties"].get("g") for f in features}, {"kr"}, name)
            self.assertLessEqual({f["properties"].get("jk") for f in features}, kinds, name)
        for name in ("kr_stations.geojson", "kr_yards.geojson", "kr_depots.geojson", "kr_build.geojson"):
            features = json.loads((ROOT / "data" / name).read_text())["features"]
            self.assertTrue(features, name)
            self.assertEqual({f["properties"]["g"] for f in features}, {"kr"}, name)

    def test_generated_lines_follow_the_one_colour_rule(self):
        features = [f["properties"] for f in json.loads((ROOT / "data" / "kr_rail.geojson").read_text())["features"]]
        fast = [p for p in features if p["jk"] in ("hs", "semi")]
        self.assertTrue(all("d" in p and p["c"].startswith("hsr") for p in fast))
        self.assertFalse([p["n"] for p in fast if "lc" in p])                        # speed before a line colour
        self.assertFalse([p["n"] for p in fast if not p.get("ref") and not p.get("e")])   # a source, or marked to verify
        self.assertEqual({p["c"] for p in features if p["n"] == "경부고속선"}, {"hsr350"})
        self.assertFalse([p["n"] for p in features if p["jk"] in ("main", "branch") and "d" in p])
        self.assertEqual(json.loads((ROOT / "data" / "kr_facts.json").read_text())["bands"], sorted({p["c"] for p in fast}))

    def test_generated_metros_are_listed_by_city(self):
        cities = {c["n"]: c for c in json.loads((ROOT / "data" / "kr_metro_cities.json").read_text())}
        for city in ("首尔", "釜山", "大邱", "仁川"):
            self.assertIn(city, cities)
        self.assertGreaterEqual(len(cities["首尔"]["lines"]), 12)


if __name__ == "__main__":
    unittest.main()
