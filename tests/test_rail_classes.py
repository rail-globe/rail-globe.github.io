"""Regressions for mixed-speed lines whose colours are chosen for the whole line."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rail_classes import principal_class


class PrincipalGradeTest(unittest.TestCase):
    def test_a_minority_fast_grade_cannot_outvote_the_principal_grade(self):
        self.assertEqual(principal_class({"main": 1107.5, "hsr250": 760.7,
                                          "hsr200": 615.6, "branch": 4.2}), "main")

    def test_high_speed_line_keeps_its_grade_through_slow_station_tracks(self):
        self.assertEqual(principal_class({"hsr350": 2329.3, "hsr250": 53.2,
                                          "hsr200": 20.3, "main": 1.1}, 23.4), "hsr350")

    def test_missing_speed_does_not_demote_a_known_high_speed_connector(self):
        self.assertEqual(principal_class({"hsr350": 1, "main": .5}, 6), "hsr350")
        self.assertEqual(principal_class({"hsr200": 1, "main": .5}, 6), "hsr200")

    def test_completely_unknown_high_speed_keeps_existing_fallback(self):
        self.assertEqual(principal_class({}, 10), "hsr250")

    def test_grade_ties_are_independent_of_way_order(self):
        self.assertEqual(principal_class({"main": 5, "hsr250": 5}), "main")
        self.assertEqual(principal_class({"hsr250": 5, "main": 5}), "main")


if __name__ == "__main__":
    unittest.main()
