"""Coverage of short and unlabelled construction without fabricating a line identity."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from europe_build import construction_features
from names import Names
from process_europe import COUNTRIES
from process_kr import KR
from process_uk import UK


class EuropeanConstructionTest(unittest.TestCase):
    def test_short_unnamed_extension_is_retained_as_sourced_construction(self):
        ways = {1: ({"railway": "construction", "construction": "tram"},
                    [(8, 47), (8.001, 47)])}
        rows = construction_features(COUNTRIES["ch"], ways, Names("ch"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["properties"], {"c": "build", "n": "", "g": "ch",
                         "construction_kind": "tram", "source_way_ids": "1", "unnamed": 1})
        self.assertNotIn("d", rows[0]["properties"])
        self.assertEqual(rows[0]["geometry"]["coordinates"][0], [8, 47])

    def test_narrow_gauge_is_included_but_platforms_and_service_tracks_are_not(self):
        ways = {1: ({"railway": "construction", "construction": "narrow_gauge"},
                    [(8, 47), (8.001, 47)]),
                2: ({"railway": "construction", "construction": "platform", "name": "Platform"},
                    [(8, 47), (8.002, 47)]),
                3: ({"railway": "construction", "construction": "rail", "service": "yard"},
                    [(8, 47), (8.003, 47)])}
        rows = construction_features(COUNTRIES["ch"], ways, Names("ch"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["properties"]["source_way_ids"], "1")

    def test_legacy_countries_do_not_opt_into_new_construction_coverage(self):
        self.assertIsNone(UK.construction_of)
        self.assertIsNone(KR.construction_of)


if __name__ == "__main__":
    unittest.main()
