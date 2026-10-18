"""Unlabelled coverage has no shared identity, but still covers a named line's gap."""
import sys
import unittest
from pathlib import Path

from shapely.geometry import LineString
from shapely.strtree import STRtree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_country import breaks, twice


class CountryChecks(unittest.TestCase):
    def test_parallel_unnamed_tracks_are_not_one_named_line(self):
        tracks = [[[0, 0], [0.06, 0]], [[0, 0.0001], [0.06, 0.0001]]]
        self.assertEqual(twice({"": tracks}), [])
        self.assertEqual([row["line"] for row in twice({"A": tracks})], ["A"])

    def test_unnamed_coverage_still_fills_a_named_gap(self):
        pieces = [[[0, 0], [0.03, 0]], [[0.04, 0], [0.07, 0]]]
        cover = [[[0.03, 0], [0.04, 0]]]
        raw_track = STRtree([LineString([[0, 0], [0.07, 0]])])
        self.assertEqual([row["line"] for row in breaks({"A": pieces}, raw_track)], ["A"])
        self.assertEqual(breaks({"A": pieces, "": cover}, raw_track), [])
        self.assertEqual(breaks({"": pieces}, raw_track), [])


if __name__ == "__main__":
    unittest.main()
