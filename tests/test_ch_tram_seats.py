"""Source, scope and direction contracts; these tests do not certify pixels."""
import copy
import sys
import unittest
from pathlib import Path

from shapely.geometry import LineString, shape
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ch_tram_seats import (apply_ch_tram_seats, compile_corridors, coordinates,
                           source_identity, source_signature, way_signature,
                           build_ch_seat_profiles, digest, profile_value, resolve_source)
from ch_tram_seats import apply_ch_continuous_seats, apply_ch_verified_profiles


class SwissSeatsTests(unittest.TestCase):
    def setUp(self):
        self.co = [[8.5, 47.3], [8.501, 47.3004], [8.504, 47.302]]
        self.extract = {"ways": [(10, {"railway": "tram", "bridge": "yes"}, self.co)], "sources": []}
        self.sources = [{"ct": "test", "network": "operator", "name": name,
                         "col": "#707070", "relations": [rid], "way_ids": [10],
                         "route_kinds": {"tram": 1}}
                        for name, rid in (("A", 1), ("B", 2))]
        self.features = [{"type": "Feature", "properties": {
            "g": "ch", "jk": "urban", "ct": "test", "n": name, "col": "#707070"},
            "geometry": {"type": "LineString", "coordinates": self.co}} for name in ("A", "B")]
        self.config = {"version": 1, "country": "ch", "corridors": [{
            "id": "manual", "ct": "test", "order": ["A", "B"], "why": "Source-owned seats",
            "asked": "User instruction", "reach_m": 8, "ramp_m": 30,
            "chains": [{"way_ids": [10], "lines": ["A", "B"],
                        "from": self.co[0], "to": self.co[-1]}]}]}

    def run_seats(self, features=None, sources=None, config=None, extract=None):
        return apply_ch_tram_seats(self.features if features is None else features,
                                   self.extract if extract is None else extract,
                                   self.config if config is None else config,
                                   self.sources if sources is None else sources)

    def test_distinct_same_colour_services_are_seated(self):
        after, records = self.run_seats()
        self.assertTrue(any(r.get("seat") == .5 and r["off"] == .5 for r in records))
        self.assertEqual({f["properties"]["n"] for f in after}, {"A", "B"})
        offsets = {f["properties"].get("off") for f in after}
        self.assertEqual((min(offsets), max(offsets)), (-.5, .5))
        self.assertEqual(offsets, {-value for value in offsets})

    def test_geometry_coverage_and_endpoints_do_not_change(self):
        after, _ = self.run_seats()
        for name in ("A", "B"):
            lines = [LineString(co) for f in after if f["properties"]["n"] == name for co in coordinates(f)]
            actual = unary_union(lines)
            expected = LineString(self.co)
            self.assertLess(actual.hausdorff_distance(expected), 1e-12)
            self.assertAlmostEqual(actual.length, expected.length, places=12)
            self.assertEqual(list(lines[0].coords[0]), self.co[0])
            self.assertEqual(list(lines[-1].coords[-1]), self.co[-1])

    def test_reverse_display_keeps_physical_side(self):
        forward, a = self.run_seats()
        reverse_features = copy.deepcopy(self.features)
        for f in reverse_features:
            f["geometry"]["coordinates"] = list(reversed(f["geometry"]["coordinates"]))
        backward, b = self.run_seats(features=reverse_features)
        a = sorted((r["identity"][4], round(r["at"][0], 8), r["off"]) for r in a)
        b = sorted((r["identity"][4], round(r["at"][0], 8), -r["off"]) for r in b)
        self.assertEqual(a, b)

    def test_verified_profile_requires_exact_identity_and_geometry(self):
        import json
        profile = {"version": 1, "country": "ch",
                   "source_rows_sha256": source_signature(self.sources),
                   "profiles": [{
                       "identity": json.loads(json.dumps(source_identity(self.sources[1]))),
                       "geometry_sha256": digest(self.co),
                       "selected_sha256": "selected", "native_sha256": "native",
                       "direction": 1,
                       "op": {"v": 1, "base": .5, "ramps": [], "origin": 0,
                              "direction": 1, "period": None},
                   }]}
        after, ledger = apply_ch_verified_profiles(
            self.features, sources=self.sources, profiles=profile)
        self.assertEqual(after[1]["properties"]["off"], .5)
        self.assertEqual(len(ledger), 1)
        changed = copy.deepcopy(self.features)
        changed[1]["geometry"]["coordinates"][1][0] += .00001
        with self.assertRaisesRegex(ValueError, "no longer match"):
            apply_ch_verified_profiles(changed, sources=self.sources, profiles=profile)

    def test_reverse_source_order_does_not_flip_seats(self):
        extract = copy.deepcopy(self.extract)
        extract["ways"][0][2].reverse()
        self.assertEqual(self.run_seats()[0], self.run_seats(extract=extract)[0])

    def test_reorder_inputs_does_not_change_service_result(self):
        after, _ = self.run_seats()
        backwards, _ = self.run_seats(features=self.features[::-1], sources=self.sources[::-1])
        for name in ("A", "B"):
            self.assertEqual([f for f in after if f["properties"]["n"] == name],
                             [f for f in backwards if f["properties"]["n"] == name])

    def test_other_countries_and_subway_are_untouched(self):
        for field, value in (("g", "fr"), ("jk", "subway")):
            features = copy.deepcopy(self.features)
            for f in features:
                f["properties"][field] = value
            after, records = self.run_seats(features=features)
            self.assertEqual(after, features)
            self.assertEqual(records, [])
            self.assertIs(after[0], features[0])

    def test_nearby_independent_track_has_no_shared_seat(self):
        features = copy.deepcopy(self.features)
        for f in features:
            f["geometry"]["coordinates"] = [[x, y + 0.001] for x, y in self.co]
        after, records = self.run_seats(features=features)
        self.assertEqual(after, features)
        self.assertEqual(records, [])

    def test_crossing_not_authorised_by_proximity(self):
        features = copy.deepcopy(self.features)
        for f in features:
            f["geometry"]["coordinates"] = [[8.502, 47.299], [8.502, 47.303]]
        after, records = self.run_seats(features=features)
        self.assertEqual(after, features)
        self.assertEqual(records, [])

    def test_non_shared_way_is_rejected_even_if_same_layer(self):
        sources = copy.deepcopy(self.sources)
        sources[1]["way_ids"] = [11]
        with self.assertRaisesRegex(ValueError, "Unproven common source"):
            self.run_seats(sources=sources)

    def test_different_height_adjacent_way_cannot_be_borrowed(self):
        extract = copy.deepcopy(self.extract)
        extract["ways"].append((11, {"railway": "tram", "layer": "-1"}, self.co))
        sources = copy.deepcopy(self.sources)
        sources[1]["way_ids"] = [11]
        with self.assertRaisesRegex(ValueError, "Unproven common source"):
            self.run_seats(sources=sources, extract=extract)

    def test_ambiguous_same_name_source_remains_open(self):
        sources = copy.deepcopy(self.sources)
        other = copy.deepcopy(sources[1])
        other["network"], other["relations"] = "other operator", [3]
        sources.append(other)
        after, records = self.run_seats(sources=sources)
        self.assertEqual([f for f in after if f["properties"]["n"] == "B"], [self.features[1]])
        self.assertTrue(any(r.get("status") == "OPEN_AMBIGUOUS_SOURCE" for r in records))
        self.assertNotEqual(source_identity(sources[1]), source_identity(other))

    def test_wrong_configuration_and_missing_authority_rejected(self):
        for mutate in (lambda c: c.update(country="de"),
                       lambda c: c["corridors"][0].update(why=""),
                       lambda c: c["corridors"][0].update(reach_m=100),
                       lambda c: c["corridors"][0].update(order=["A", "A"])):
            config = copy.deepcopy(self.config)
            mutate(config)
            with self.assertRaises(ValueError):
                self.run_seats(config=config)

    def test_stale_endpoints_and_missing_way_rejected(self):
        for field, value in (("from", [0, 0]), ("way_ids", [999])):
            config = copy.deepcopy(self.config)
            config["corridors"][0]["chains"][0][field] = value
            with self.assertRaises(ValueError):
                self.run_seats(config=config)

    def test_membership_interval_can_end_inside_original_way(self):
        config = copy.deepcopy(self.config)
        config["corridors"][0]["chains"][0]["to"] = self.co[1]
        after, records = self.run_seats(config=config)
        self.assertTrue(records)
        self.assertTrue(all(r["at"][0] < self.co[1][0] for r in records))

    def test_original_source_and_features_are_not_mutated(self):
        baseline = copy.deepcopy((self.features, self.extract, self.config, self.sources))
        self.run_seats()
        self.assertEqual((self.features, self.extract, self.config, self.sources), baseline)

    def test_sh_is_finite_and_shared_ramps_remain_bounded(self):
        _, records = self.run_seats()
        self.assertTrue(all(0 <= r["sh"] <= 1 for r in records))
        self.assertTrue(any(0 < r["sh"] < 1 for r in records))
        self.assertTrue(all(r["source_distance_m"] <= 8 for r in records))

    def test_no_implicit_geometry_replay(self):
        with self.assertRaisesRegex(ValueError, "implicit geometry replay"):
            apply_ch_tram_seats(self.features, self.extract, self.config)

    def test_review_only_configuration_cannot_enter_production(self):
        config = copy.deepcopy(self.config)
        config["publication_state"] = "review-only"
        with self.assertRaisesRegex(ValueError, "production visual acceptance"):
            self.run_seats(config=config)
        _, records = apply_ch_tram_seats(self.features, self.extract, config, self.sources, review=True)
        self.assertTrue(records)

    def test_disabled_corridor_does_not_change_features(self):
        config = copy.deepcopy(self.config)
        config["corridors"][0].update(enabled=False, open_reason="Failed visual review")
        after, records = self.run_seats(config=config)
        self.assertEqual(after, self.features)
        self.assertEqual(records, [])
        config["corridors"][0]["open_reason"] = ""
        with self.assertRaisesRegex(ValueError, "disabled-corridor reason"):
            self.run_seats(config=config)

    def test_nearby_owned_independent_track_cannot_borrow_seat(self):
        co = [[x, y + 0.000025] for x, y in self.co]
        extract = copy.deepcopy(self.extract)
        extract["ways"].append((11, {"railway": "tram", "layer": "-1"}, co))
        sources = copy.deepcopy(self.sources)
        for s in sources:
            s["way_ids"].append(11)
        features = copy.deepcopy(self.features)
        for f in features:
            f["geometry"]["coordinates"] = co
        after, records = self.run_seats(features=features, sources=sources, extract=extract)
        self.assertEqual(after, features)
        self.assertEqual(records, [])

    def test_coincident_different_height_host_is_ambiguous(self):
        extract = copy.deepcopy(self.extract)
        extract["ways"].append((11, {"railway": "tram", "layer": "-1"}, copy.deepcopy(self.co)))
        sources = copy.deepcopy(self.sources)
        for s in sources:
            s["way_ids"].append(11)
        after, records = self.run_seats(sources=sources, extract=extract)
        self.assertEqual(after, self.features)
        self.assertEqual(records, [])

    def test_source_identity_and_way_content_are_pinned(self):
        config = copy.deepcopy(self.config)
        config["source_rows_sha256"] = source_signature(self.sources)
        config["source_ways_sha256"] = way_signature({10: self.extract["ways"][0][1:]}, self.sources)
        self.run_seats(config=config)
        sources = copy.deepcopy(self.sources)
        sources[0]["relations"].append(3)
        with self.assertRaisesRegex(ValueError, "identities or membership"):
            self.run_seats(config=config, sources=sources)
        extract = copy.deepcopy(self.extract)
        extract["ways"][0][1]["layer"] = "-2"
        with self.assertRaisesRegex(ValueError, "geometry or tags"):
            self.run_seats(config=config, extract=extract)
        extract = copy.deepcopy(self.extract)
        extract["ways"][0][2][1][1] += 0.000001
        with self.assertRaisesRegex(ValueError, "geometry or tags"):
            self.run_seats(config=config, extract=extract)

    def test_pins_allow_raw_direction_and_input_order_reversal(self):
        config = copy.deepcopy(self.config)
        config["source_rows_sha256"] = source_signature(self.sources)
        config["source_ways_sha256"] = way_signature({10: self.extract["ways"][0][1:]}, self.sources)
        extract = copy.deepcopy(self.extract)
        extract["ways"][0][2].reverse()
        self.assertEqual(self.run_seats(config=config)[0],
                         self.run_seats(config=config, extract=extract, sources=self.sources[::-1])[0])

    def test_full_network_and_rid_select_one_actual_row(self):
        sources = copy.deepcopy(self.sources)
        other = {**sources[1], "network": "other", "relations": [3, 4]}
        sources.append(other)
        p = self.features[1]["properties"]
        self.assertIsNone(resolve_source(p, sources))
        self.assertEqual(resolve_source({**p, "network": "other", "rid": "4,3"}, sources), other)
        for selector in ({"network": "other", "rid": "2"},
                         {"network": "operator", "rid": "2,3,4"},
                         {"network": "operator", "rid": "not-an-id"}):
            self.assertIsNone(resolve_source({**p, **selector}, sources))

    def test_hook_uses_network_and_rid_for_each_ledger_identity(self):
        sources = copy.deepcopy(self.sources)
        other = {**sources[1], "network": "other", "relations": [3, 4]}
        sources.append(other)
        features = copy.deepcopy(self.features)
        features[1]["properties"].update(network="other", rid="4,3")
        _, ledger = self.run_seats(features=features, sources=sources)
        rows = [r for r in ledger if r.get("identity", [None] * 5)[4] == "B"]
        self.assertTrue(rows)
        self.assertTrue(all(r["identity"] == source_identity(other) for r in rows))
        features[1]["properties"]["rid"] = "2"
        after, ledger = self.run_seats(features=features, sources=sources)
        self.assertTrue(any(r.get("status") == "OPEN_AMBIGUOUS_SOURCE" for r in ledger))
        self.assertIn(features[1], after)

    def test_actual_basel_tram8_rows_are_distinct_without_guessing_frozen_features(self):
        root = Path(__file__).resolve().parents[1]
        import pickle
        native = pickle.loads((root / "data/raw/extract_ch.pkl").read_bytes())
        by_id = {rid: tags for rid, tags, _ in native["relations"]}
        sources = []
        for relation_ids in ((4253314, 9129284), (11815262, 11815263)):
            tags = [by_id[rid] for rid in relation_ids]
            self.assertTrue(all(t["route"] == "tram" and t["ref"] == "8" for t in tags))
            self.assertEqual(len({t["network"] for t in tags}), 1)
            self.assertEqual(len({t["colour"] for t in tags}), 1)
            sources.append({"ct": "巴塞尔", "name": "Tram 8",
                            "network": tags[0]["network"], "col": tags[0]["colour"],
                            "relations": list(relation_ids)})
        rows = [s for s in sources if s["ct"] == "\u5df4\u585e\u5c14" and s["name"] == "Tram 8"]
        self.assertEqual({tuple(r["relations"]) for r in rows},
                         {(4253314, 9129284), (11815262, 11815263)})
        self.assertEqual({r["network"] for r in rows}, {"RVL;TNW", "TNW"})
        props = {"ct": rows[0]["ct"], "n": "Tram 8", "col": rows[0]["col"]}
        self.assertIsNone(resolve_source(props, sources))
        for row in rows:
            self.assertEqual(resolve_source({**props, "network": row["network"],
                                             "rid": row["relations"]}, sources), row)

    def test_member_ownership_cannot_union_different_network_rows(self):
        extract = copy.deepcopy(self.extract)
        extract["ways"].append((11, {"railway": "tram"}, [self.co[-1], [8.505, 47.303]]))
        sources = copy.deepcopy(self.sources)
        sources[0]["way_ids"].append(11)
        sources.append({**sources[1], "network": "other", "relations": [3], "way_ids": [11]})
        config = copy.deepcopy(self.config)
        config["corridors"][0]["chains"][0].update(way_ids=[10, 11], to=[8.505, 47.303])
        with self.assertRaisesRegex(ValueError, "Unproven common source"):
            self.run_seats(config=config, extract=extract, sources=sources)

    def test_fixed_direction_overrides_reversed_chain_endpoints(self):
        config = copy.deepcopy(self.config)
        config["corridors"][0]["direction"] = {"from": self.co[0], "to": self.co[-1]}
        baseline = self.run_seats(config=config)
        row = config["corridors"][0]["chains"][0]
        row["from"], row["to"] = row["to"], row["from"]
        self.assertEqual(self.run_seats(config=config), baseline)


class SwissContinuousProfileTests(unittest.TestCase):
    def setUp(self):
        SwissSeatsTests.setUp(self)
        self.config["corridors"][0]["direction"] = {"from": self.co[0], "to": self.co[-1]}
        self.metadata = {"ways": {"10": {"nodes": [100, 101, 102],
                                        "tags": {"railway": "tram", "gauge": "1000"}}}}

    def build(self):
        self.config["raw_metadata_sha256"] = digest(self.metadata)
        self.config["raw_node_coordinates_sha256"] = digest(
            [[wid, self.metadata["ways"][str(wid)]["nodes"], co]
             for wid, _, co in sorted(self.extract["ways"])])
        return build_ch_seat_profiles(self.extract, self.sources, self.metadata, self.config)

    def add_branch(self, wid=11, start_node=102, coords=None, tags=None):
        coords = [self.co[-1], [8.505, 47.303]] if coords is None else coords
        self.extract["ways"].append((wid, {"railway": "tram"}, coords))
        self.metadata["ways"][str(wid)] = {"nodes": [start_node, 200 + wid],
                                           "tags": tags or {"railway": "tram", "gauge": "1000"}}
        self.sources[1]["way_ids"].append(wid)

    def test_shared_full_seat_and_no_internal_ramp(self):
        result = self.build()
        shared = next(s for s in result["profiles"] if s["seat"] == .5)
        for at in (0, 1e-9, shared["length_m"] / 2, shared["length_m"]):
            self.assertEqual(profile_value(shared, at), {"soff": .5, "sh": 1})
        self.assertEqual(result["publication_state"], "review-only")

    def test_branch_inherits_only_actual_node_and_decay_is_outside_shared(self):
        self.add_branch()
        result = self.build()
        branch = next(s for s in result["profiles"] if s["kind"] == "independent")
        self.assertEqual(branch["inherited_node"], 102)
        self.assertEqual(branch["way_ids"], [11])
        self.assertEqual(profile_value(branch, 0), {"soff": .5, "sh": 0})
        self.assertEqual(profile_value(branch, branch["length_m"]), {"soff": 0, "sh": 0})
        eps = 0.001
        self.assertLess(abs(profile_value(branch, eps)["soff"] - .5), 1e-9)
        self.assertLess(abs(profile_value(branch, branch["ramp_m"] - eps)["soff"]), 1e-9)

    def test_adjacent_and_coincident_other_node_never_inherit(self):
        self.add_branch(start_node=999)
        result = self.build()
        self.assertFalse(any(s["kind"] == "independent" for s in result["profiles"]))
        self.assertTrue(any(p["node"] == 102 and p["status"] == "OPEN_NO_CONTINUATION"
                            for p in result["ports"]))

    def test_different_layer_gauge_bridge_tunnel_and_service_remain_open(self):
        for change in ({"layer": "-1"}, {"gauge": "1435"}, {"bridge": "yes"},
                       {"tunnel": "yes"}, {"service": "yard"}):
            self.setUp()
            self.add_branch(tags={"railway": "tram", "gauge": "1000", **change})
            result = self.build()
            self.assertFalse(any(s["kind"] == "independent" for s in result["profiles"]))
            self.assertTrue(any(p["status"] == "OPEN_LEVEL_CONFLICT" for p in result["ports"]))

    def test_multiple_same_service_branches_are_not_chosen_by_proximity(self):
        self.add_branch()
        self.add_branch(wid=12, coords=[self.co[-1], [8.506, 47.302]])
        result = self.build()
        self.assertFalse(any(s["kind"] == "independent" for s in result["profiles"]))
        self.assertTrue(any(p["status"] == "OPEN_BRANCH_AMBIGUOUS" for p in result["ports"]))

    def test_profile_does_not_modify_or_duplicate_features_or_sources(self):
        frozen = copy.deepcopy((self.features, self.extract, self.sources, self.metadata))
        self.build()
        self.assertEqual((self.features, self.extract, self.sources, self.metadata), frozen)

    def test_profile_node_and_coordinate_pins_fail_closed(self):
        self.build()
        self.metadata["ways"]["10"]["nodes"][0] = 999
        with self.assertRaisesRegex(ValueError, "stale pinned raw"):
            build_ch_seat_profiles(self.extract, self.sources, self.metadata, self.config)
        self.config["raw_metadata_sha256"] = digest(self.metadata)
        with self.assertRaisesRegex(ValueError, "node-to-coordinate"):
            build_ch_seat_profiles(self.extract, self.sources, self.metadata, self.config)

    def test_shared_membership_change_inherits_same_fixed_seat(self):
        self.add_branch()
        self.sources[0]["way_ids"].append(11)
        second = copy.deepcopy(self.config["corridors"][0]["chains"][0])
        second.update(way_ids=[11], **{"from": self.co[-1], "to": [8.505, 47.303]})
        self.config["corridors"][0]["chains"].append(second)
        result = self.build()
        self.assertTrue(all(p["status"] == "INHERITED_SHARED_PORT"
                            for p in result["ports"] if p["node"] == 102))
        self.assertFalse(any(s["kind"] == "independent" for s in result["profiles"]))

    def test_conflicting_shared_seat_is_not_inherited(self):
        self.add_branch()
        self.sources[0]["way_ids"].append(11)
        second = copy.deepcopy(self.config["corridors"][0])
        second.update(id="second", order=["B", "A"])
        second["chains"][0].update(way_ids=[11], **{"from": self.co[-1], "to": [8.505, 47.303]})
        self.config["corridors"].append(second)
        result = self.build()
        self.assertTrue(all(p["status"] == "OPEN_SHARED_PORT_CONFLICT"
                            for p in result["ports"] if p["node"] == 102))

    def test_missing_direction_and_production_bypass_rejected(self):
        self.build()
        self.config["corridors"][0].pop("direction")
        with self.assertRaisesRegex(ValueError, "explicit fixed"):
            build_ch_seat_profiles(self.extract, self.sources, self.metadata, self.config)
        self.config["publication_state"] = "review-only"
        with self.assertRaisesRegex(ValueError, "production visual acceptance"):
            build_ch_seat_profiles(self.extract, self.sources, self.metadata, self.config)

    def test_continuous_hook_selected_binding_and_generic_degree_op(self):
        from continuous_offset import value_at
        self.build()
        selected = {source_identity(row): {"kept": [LineString(self.co)], "native": [self.co]}
                    for row in self.sources}
        after, ledger = apply_ch_continuous_seats(
            self.features, self.extract, sources=self.sources, metadata=self.metadata,
            config=self.config, selected=selected, review=True)
        self.assertEqual([f["geometry"] for f in after], [f["geometry"] for f in self.features])
        import json
        op = json.loads(after[1]["properties"]["op"])
        self.assertAlmostEqual(value_at(op, LineString(self.co).length / 2), .5)
        self.assertEqual(len(ledger), 2)
        self.assertTrue(all(r["status"] == "BOUND_SELECTED_ORIGINAL_EDGES" for r in ledger))

    def test_actual_selected_other_way_cannot_authorise_shared_profile(self):
        self.build()
        parallel = [[x, y + .000025] for x, y in self.co]
        selected = {source_identity(row): {"kept": [LineString(parallel)], "native": [self.co]}
                    for row in self.sources}
        after, ledger = apply_ch_continuous_seats(
            self.features, self.extract, sources=self.sources, metadata=self.metadata,
            config=self.config, selected=selected, review=True)
        self.assertEqual(after, self.features)
        self.assertFalse(any(r["status"] == "BOUND_SELECTED_ORIGINAL_EDGES" for r in ledger))

    def test_bound_display_not_a_native_subpath_remains_open(self):
        self.build()
        selected = {source_identity(row): {"kept": [LineString(self.co)], "native": [self.co]}
                    for row in self.sources}
        features = copy.deepcopy(self.features)
        features[1]["geometry"]["coordinates"][1][1] += .000001
        after, ledger = apply_ch_continuous_seats(
            features, self.extract, sources=self.sources, metadata=self.metadata,
            config=self.config, selected=selected, review=True)
        self.assertIn(features[1], after)
        self.assertTrue(any(r["status"] == "OPEN_NATIVE_PATH_BINDING" for r in ledger))


if __name__ == "__main__":
    unittest.main()
