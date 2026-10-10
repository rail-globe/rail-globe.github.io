"""Protect section boundaries and preserve the unmodified OSM cache."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rail_status import corrected_tags, load_rules


class RailStatusTest(unittest.TestCase):
    def rule(self, status="rail"):
        return {"id": "verified-section", "names": ["同一条长线路"], "status": status,
                "bbox": [100, 30, 101, 31], "checked": "2026-10-07", "sources": [{"url": "https://example.com"}]}

    def test_open_section_does_not_promote_other_sections_or_boundary_crossing_ways(self):
        tags = {"name": "同一条长线路", "railway": "construction", "construction": "rail"}
        for coords in [[(101.1, 30.5), (101.2, 30.5)], [(100.5, 30.5), (101.1, 30.5)]]:
            self.assertEqual(corrected_tags(tags, coords, [self.rule()]), (tags, None))

    def test_completed_section_clears_old_construction_tags_without_mutating_source(self):
        tags = {"name:zh": "同一条长线路", "railway": "construction", "construction": "rail",
                "construction:railway": "rail", "maxspeed": "250"}
        fixed, evidence = corrected_tags(tags, [(100.1, 30.1), (100.2, 30.2)], [self.rule()])
        self.assertEqual(fixed["railway"], "rail")
        self.assertNotIn("construction", fixed)
        self.assertNotIn("construction:railway", fixed)
        self.assertEqual(tags["railway"], "construction")
        self.assertEqual(fixed["maxspeed"], "250")
        self.assertEqual(evidence, "verified-section")

    def test_reserved_station_tracks_are_not_operating_network_tracks(self):
        fixed, _ = corrected_tags({"name": "同一条长线路", "railway": "rail"},
                                  [(100.1, 30.1)], [self.rule("construction")])
        self.assertEqual((fixed["railway"], fixed["construction"]), ("construction", "rail"))

    def test_planning_evidence_does_not_create_a_construction_line(self):
        fixed, _ = corrected_tags({"name": "同一条长线路", "railway": "construction", "construction": "rail"},
                                  [(100.1, 30.1)], [self.rule("proposed")])
        self.assertEqual(fixed["railway"], "proposed")
        self.assertNotIn("construction", fixed)

    def test_conflicting_evidence_fails_instead_of_silently_picking_a_status(self):
        with self.assertRaises(ValueError):
            corrected_tags({"name": "同一条长线路"}, [(100.1, 30.1)], [self.rule(), self.rule("construction")])

    def test_unnamed_track_that_a_source_shows_to_be_a_line_s(self):
        rule = {"id": "line-to-mine", "ways": [7, 8], "line": "乐德线", "usage": "branch", "status": "rail",
                "checked": "2026-10-10", "sources": [{"url": "https://example.com"}]}
        spur = {"railway": "rail", "service": "spur", "usage": "industrial"}
        fixed, evidence = corrected_tags(spur, [(117.6, 29.0)], [rule], way=7)
        self.assertEqual((fixed["name"], fixed["usage"], "service" in fixed, evidence), ("乐德线", "branch", False, "line-to-mine"))
        self.assertEqual(corrected_tags(spur, [(117.6, 29.0)], [rule], way=9), (spur, None))     # another way of the same tags
        self.assertEqual(corrected_tags(spur, [(117.6, 29.0)], [rule]), (spur, None))

    def test_the_ways_of_the_rules_are_in_the_extract(self):
        import pickle
        rules = load_rules(Path(__file__).resolve().parents[1] / "data" / "rail_status_overrides.json")
        wanted = {w for rule in rules for w in rule.get("ways", ())}
        if wanted:
            ways = {wid for wid, t, co in pickle.load(open(Path(__file__).resolve().parents[1] / "data" / "raw" / "extract.pkl", "rb"))["ways"]}
            self.assertEqual(wanted - ways, set())

    def test_missing_evidence_is_rejected(self):
        rule = self.rule()
        rule.pop("sources")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rules.json"
            path.write_text(json.dumps([rule]))
            with self.assertRaises(ValueError):
                load_rules(path)


if __name__ == "__main__":
    unittest.main()
