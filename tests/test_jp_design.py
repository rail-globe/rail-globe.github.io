"""Completed upgrades, station-bounded grades, and separate unfinished targets."""
import copy
import sys
import unittest
from pathlib import Path

from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from jp_design import annotate_build, apply_design, base_colour


class JapanDesignTests(unittest.TestCase):
    def test_completed_infrastructure_overrides_the_historical_standard(self):
        self.assertEqual(base_colour("東海道新幹線")["d"], 285)
        self.assertEqual(base_colour("山陽新幹線")["d"], 300)
        self.assertEqual(base_colour("上越新幹線")["d"], 275)
        self.assertEqual(base_colour("北海道新幹線")["d"], 260)
        self.assertNotIn("d", base_colour("未確認新幹線"))

    def example(self):
        xy = [(140., 36.), (140., 37.), (140., 38.), (140., 39.)]
        stations = [({"name": name}, *pt) for name, pt in zip(("東京", "宇都宮", "盛岡", "新青森"), xy)]
        props = {"n": "東北新幹線", "g": "jp", "jk": "shinkansen", "off": -.5, "sh": 1, "bn": 2,
                 **base_colour("東北新幹線")}
        features = [{"type": "Feature", "properties": props,
                     "geometry": {"type": "LineString", "coordinates": xy}}]
        return features, {"東北新幹線": dict(props)}, stations

    def test_section_boundaries_cut_the_same_path_without_moving_offsets(self):
        features, rows, stations = self.example()
        original = copy.deepcopy(features)
        output, audit = apply_design(features, rows, stations)
        self.assertTrue(all(r["placed"] for r in audit))
        self.assertEqual(features, original)
        before = shape(features[0]["geometry"])
        after = unary_union([shape(f["geometry"]) for f in output])
        self.assertEqual(before.hausdorff_distance(after), 0.)
        self.assertEqual(before.length, after.length)
        self.assertEqual([f["properties"]["d"] for f in output], [260, 320, 260])
        self.assertEqual([f["properties"].get("ud") for f in output], [None, None, 320])
        self.assertTrue(all(f["properties"][k] == original[0]["properties"][k]
                            for f in output for k in ("off", "sh", "bn")))
        self.assertNotIn("d", rows["東北新幹線"])
        self.assertEqual(rows["東北新幹線"]["design"], [260, 320])
        for a, b in zip(output, output[1:]):
            self.assertEqual(a["geometry"]["coordinates"][-1], b["geometry"]["coordinates"][0])

    def test_missing_or_ambiguous_boundary_does_not_upgrade_the_whole_line(self):
        features, rows, stations = self.example()
        stations = [s for s in stations if s[0]["name"] != "盛岡"]
        output, audit = apply_design(features, rows, stations)
        self.assertFalse(any(r["placed"] for r in audit))
        self.assertEqual({f["properties"]["d"] for f in output}, {260})
        self.assertEqual(rows["東北新幹線"]["design"], [260])
        self.assertNotIn(320, [s["design"] for s in rows["東北新幹線"]["sections"]])

    def test_hokkaido_construction_target_keeps_its_dashed_identity(self):
        features = [{"properties": {"n": "北海道新幹線", "c": "build", "h": 1}},
                    {"properties": {"n": "中央新幹線", "c": "build", "h": 1}}]
        annotate_build(features)
        self.assertEqual(features[0]["properties"]["c"], "build")
        self.assertEqual(features[0]["properties"]["d"], 320)
        self.assertEqual(features[0]["properties"]["de"], "新函館北斗~札幌")
        self.assertNotIn("d", features[1]["properties"])


if __name__ == "__main__":
    unittest.main()
