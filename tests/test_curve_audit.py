"""The visible-corner check must include joins, not just each feature's interior."""
import sys
import unittest
from pathlib import Path

from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_curves import audit
from check_layers import COLOUR, hidden


class CurveAuditTest(unittest.TestCase):
    def test_feature_seam_is_checked_as_one_line(self):
        pieces = [(LineString([(116, 40), (116.001, 40)]), 0),
                  (LineString([(116.001, 40), (116.002, 40.001)]), .5)]
        result = audit(lines={("北京", "test"): pieces})
        self.assertEqual(result["corners"], 1)
        self.assertGreater(result["findings"][0]["angle"], 45)

    def test_different_lines_are_not_joined_at_a_crossing(self):
        result = audit(lines={("city", "one"): [(LineString([(116, 40), (116.001, 40)]), 0)],
                              ("city", "two"): [(LineString([(116.001, 40), (116.002, 40.001)]), 0)]})
        self.assertEqual(result["corners"], 0)

    def test_circular_lines_include_the_closing_vertex(self):
        co = [(116, 40), (116.001, 40), (116.001, 40.001), (116, 40.001), (116, 40)]
        result = audit(lines={("city", "loop"): [(LineString(co), 0)]})
        self.assertEqual(result["corners"], 4)

    def test_shared_line_is_counted_once_across_many_short_features(self):
        one, two = ("city", "one"), ("city", "two")
        previous = dict(COLOUR)
        try:
            COLOUR.update({one: "#ff0000", two: "#0000ff"})
            pieces = [(LineString([(116 + i * .0005, 40), (116 + (i + 1) * .0005, 40)]), 0) for i in range(20)]
            result = hidden({one: [(LineString([(116, 40), (116.01, 40)]), 0)], two: pieces}, .0005)
            self.assertEqual(len(result), 1)
            self.assertAlmostEqual(result[0][0], 1.11, places=2)
        finally:
            COLOUR.clear()
            COLOUR.update(previous)
