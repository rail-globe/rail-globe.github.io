"""Native relation evidence: no geometry processing or external extracts needed."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from endpoint_sources import ENDPOINT_CITIES, build_sources, route_chunks


class EndpointSourceTests(unittest.TestCase):
    def way(self, *points, **tags):
        return {"railway": "tram", **tags}, list(points)

    def route(self, ways, members):
        return route_chunks(10, {"type": "route", "route": "tram"}, members, ways, {"tram", "rail"})

    def test_unique_continuation_resolves_initial_and_later_reverse(self):
        ways = {1: self.way((1, 0), (0, 0)), 2: self.way((2, 0), (1, 0)),
                3: self.way((2, 0), (3, 0))}
        frozen = copy.deepcopy(ways)
        route = self.route(ways, [("w", 1), ("n", 44), ("w", 2), ("w", 3)])
        self.assertEqual(route["chunks"], [[[0, 0], [1, 0], [2, 0], [3, 0]]])
        self.assertEqual([p["reversed"] for p in route["chunk_members"][0]], [True, True, False])
        self.assertEqual([p["member_index"] for p in route["chunk_members"][0]], [0, 2, 3])
        self.assertEqual(route["breaks"], [])
        self.assertEqual(ways, frozen)

    def test_missing_way_is_barrier_even_if_neighbours_connect(self):
        ways = {1: self.way((0, 0), (1, 0)), 2: self.way((1, 0), (2, 0))}
        route = self.route(ways, [("w", 1), ("w", 99), ("w", 2)])
        self.assertEqual(len(route["chunks"]), 2)
        self.assertEqual(route["breaks"][0]["reason"], "missing_way")
        self.assertEqual(route["breaks"][0]["member_index"], 1)

    def test_ineligible_way_and_nested_relation_are_barriers(self):
        ways = {1: self.way((0, 0), (1, 0)), 2: self.way((1, 0), (2, 0)),
                3: self.way((1, 0), (1, 1), service="yard")}
        for barrier, reason in [(("w", 3), "ineligible_way"), (("r", 99), "unsupported_member_type")]:
            with self.subTest(reason=reason):
                route = self.route(ways, [("w", 1), barrier, ("w", 2)])
                self.assertEqual(len(route["chunks"]), 2)
                self.assertEqual(route["breaks"][0]["reason"], reason)

    def test_gap_is_not_joined_by_coordinate_tolerance(self):
        ways = {1: self.way((0, 0), (1, 0)), 2: self.way((1.000001, 0), (2, 0))}
        route = self.route(ways, [("w", 1), ("w", 2)])
        self.assertEqual(len(route["chunks"]), 2)
        self.assertEqual(route["breaks"][0]["reason"], "endpoint_gap")

    def test_matching_both_ends_is_direction_ambiguity(self):
        ways = {1: self.way((0, 0), (1, 0)), 2: self.way((1, 0), (.5, 1), (0, 0))}
        route = self.route(ways, [("w", 1), ("w", 2)])
        self.assertEqual(len(route["chunks"]), 2)
        self.assertEqual(route["breaks"][0]["reason"], "ambiguous_orientation")

    def test_closed_way_is_retained_but_no_unproved_ring_direction_join(self):
        ways = {1: self.way((0, 0), (1, 0), (0, 0)), 2: self.way((0, 0), (0, 1))}
        route = self.route(ways, [("w", 1), ("w", 2)])
        self.assertEqual(route["chunks"][0], [[0, 0], [1, 0], [0, 0]])
        self.assertEqual(len(route["chunks"]), 2)
        self.assertEqual(route["breaks"][0]["reason"], "ambiguous_orientation")

    def test_three_way_direction_conflict_breaks_instead_of_reversing_prefix(self):
        ways = {1: self.way((0, 0), (1, 0)), 2: self.way((1, 0), (2, 0)),
                3: self.way((1, 0), (1, 1))}
        route = self.route(ways, [("w", 1), ("w", 2), ("w", 3)])
        self.assertEqual(route["chunks"], [[[0, 0], [1, 0], [2, 0]], [[1, 0], [1, 1]]])
        self.assertEqual(route["breaks"][0]["reason"], "direction_conflict")

    def test_master_and_native_way_provenance_preserve_identity(self):
        ways = {1: self.way((0, 0), (1, 0)), 2: self.way((1, 0), (2, 0))}
        relations = {10: ({"type": "route", "route": "tram"}, [("w", 1), ("w", 2)]),
                     11: ({"type": "route", "route": "tram"}, [("w", 2)]),
                     100: ({"type": "route_master"}, [("r", 10), ("r", 11)]),
                     101: ({"type": "route_master"}, [("r", 10)])}
        feature = {"properties": {"network": "N", "n": "1", "rid": "10,11"}}
        source = build_sources([feature, copy.deepcopy(feature)], ways, relations, {"tram"})
        self.assertEqual(list(source), ["N|1|10,11"])
        row = source["N|1|10,11"]
        self.assertEqual(row["rids"], [10, 11])
        self.assertEqual(row["masters"], [100, 101])
        self.assertEqual(row["routes"][0]["masters"], [100, 101])
        self.assertEqual(row["way_ids"], [1, 2])
        self.assertEqual(row["ways"][0]["coordinates"], [[0, 0], [1, 0]])
        self.assertEqual(row["incomplete_reasons"], [])

    def test_missing_relation_or_feature_identity_is_explicit(self):
        for rid, reason in [("99", "missing_relation"), ("", "missing_or_invalid_feature_relation_identity")]:
            with self.subTest(rid=rid):
                source = build_sources([{"properties": {"n": "1", "rid": rid}}], {}, {}, {"tram"})
                row = source[f"|1|{rid}"]
                self.assertEqual(row["routes"], [])
                self.assertEqual(row["incomplete_reasons"][0]["reason"], reason)

    def test_country_scope_is_the_cities_that_passed_their_trial(self):
        # 2026-10-18: every city whose endpoint trial passed against its legacy drawing
        # (output/endpoint-all/trial/compare-<g>.json); Basel, Hamburg and the Ruhr after the
        # shared-centre fix (output/endpoint-all/fix/); Germany's elsewhere keeps the legacy one
        import endpoint_sources
        self.assertIn("罗马", ENDPOINT_CITIES["it"])
        self.assertIn("斯图加特", ENDPOINT_CITIES["de"])
        for g, city in (("ch", "巴塞尔"), ("de", "汉堡"), ("de", "鲁尔")):
            self.assertIn(city, ENDPOINT_CITIES[g])
        self.assertNotIn("德国其他", ENDPOINT_CITIES["de"])
        # 2026-10-19: Kuala Lumpur, Palembang and Jakarta passed the same comparison
        self.assertEqual((ENDPOINT_CITIES["my"], ENDPOINT_CITIES["id"]), (("吉隆坡",), ("巨港", "雅加达")))
        self.assertEqual(sum(len(cities) for cities in ENDPOINT_CITIES.values()), 72)
        self.assertFalse(endpoint_sources.ENDPOINT_TRIAL)


if __name__ == "__main__":
    unittest.main()
