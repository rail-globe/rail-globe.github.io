import copy
import json
import pickle
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from fr_tram_seats import (apply_fr_tram_seats, canonical_route_key, identity,
                           line_fingerprint, load_config, parts,
                           digest, validate_alias_sources, validate_config, validate_extract)


def feature(coords, off=0.5, country="fr", geometry_type="LineString"):
    return {"type": "Feature",
            "properties": {"g": country, "ct": "Test", "n": "Line", "col": "#123456",
                           "jk": "urban", "off": off},
            "geometry": {"type": geometry_type, "coordinates": coords}}


def config_for(features):
    return {"version": 1, "country": "fr", "aliases": [], "independent": [{
        "id": "test-independent", "identity": ["Test", "Line", "#123456", "urban"],
        "bbox": [2.001, 48.0, 2.003, 48.001], "ramp_m": 200,
        "line_sha256": line_fingerprint(features),
        "why": "Independent tracks confirmed by source.", "asked": "Test authority."}]}


def edges(features, properties=False):
    result = Counter()
    for f in features:
        props = {k: v for k, v in f["properties"].items() if k not in ("goff", "frseat")}
        for coords in parts(f):
            for a, b in zip(coords, coords[1:]):
                key = (tuple(a), tuple(b))
                if properties:
                    key += (json.dumps(props, sort_keys=True),)
                result[key] += 1
    return result


class FrenchSeatContract(unittest.TestCase):
    def setUp(self):
        self.baseline = [feature([[1.993 + i * 0.0002, 48.0005] for i in range(91)])]
        self.config = config_for(self.baseline)

    def test_no_in_place_mutation_and_original_vertices(self):
        frozen = copy.deepcopy(self.baseline)
        result, ledger = apply_fr_tram_seats(self.baseline, self.config)
        self.assertTrue(ledger)
        self.assertEqual(self.baseline, frozen)
        self.assertEqual(edges(frozen, True), edges(result, True))
        self.assertTrue(all("ap" not in f["properties"] and "sh" not in f["properties"] for f in result))

    def test_off_unchanged_and_high_zoom_return(self):
        result, _ = apply_fr_tram_seats(self.baseline, self.config)
        p = next(f["properties"] for f in result if f["properties"].get("goff") == 0.5)
        self.assertEqual(p["off"], 0.5)
        # Actual app.html beside() stops: no goff contribution before z14.5,
        # 25% of the z14.5 displacement at z16, exactly zero at z16.5.
        self.assertEqual(p["off"] * 5, 2.5)
        self.assertAlmostEqual(p["off"] * 8 - p["goff"] * (8 - 6.875 * 0.25), 0.859375)
        self.assertEqual(p["off"] * 8 - p["goff"] * 8, 0)

    def test_unrelated_and_foreign_features_pass_through(self):
        other = feature([[2.002, 48.0004], [2.0022, 48.0004]], country="ch")
        result, _ = apply_fr_tram_seats(self.baseline + [other], self.config)
        self.assertIs(result[-1], other)

    def test_outside_scope_and_zero_offset_unchanged(self):
        far = feature([[3, 48], [3.001, 48]])
        zero = feature([[2.002, 48.0004], [2.0022, 48.0004]], off=0)
        all_features = self.baseline + [far, zero]
        result, _ = apply_fr_tram_seats(all_features, config_for(all_features))
        self.assertIs(result[-2], far)
        self.assertIs(result[-1], zero)

    def test_reverse_direction_does_not_flip_seat(self):
        reversed_input = [feature(list(reversed(self.baseline[0]["geometry"]["coordinates"])), off=-0.5)]
        result, ledger = apply_fr_tram_seats(reversed_input, config_for(reversed_input))
        self.assertTrue(ledger)
        self.assertTrue(all(row["goff"] <= 0 for row in ledger))
        self.assertEqual(edges(result), edges(reversed_input))

    def test_multiline_preserves_every_edge(self):
        f = feature([self.baseline[0]["geometry"]["coordinates"],
                     [[4, 49], [4.001, 49]]], geometry_type="MultiLineString")
        result, _ = apply_fr_tram_seats([f], config_for([f]))
        self.assertEqual(edges([f], True), edges(result, True))

    def test_existing_vertex_ramp_is_small_and_continuous(self):
        result, _ = apply_fr_tram_seats(self.baseline, self.config)
        values = [f["properties"].get("goff", 0) for f in result]
        self.assertEqual(values[0], 0)
        self.assertEqual(values[-1], 0)
        self.assertLessEqual(max(abs(a - b) for a, b in zip(values, values[1:])), 1 / 16)
        for a, b in zip(result, result[1:]):
            self.assertEqual(a["geometry"]["coordinates"][-1], b["geometry"]["coordinates"][0])

    def test_stale_input_fails_closed(self):
        bad = copy.deepcopy(self.baseline)
        bad[0]["geometry"]["coordinates"][0][0] += 0.000001
        with self.assertRaisesRegex(ValueError, "Stale"):
            apply_fr_tram_seats(bad, self.config)

    def test_repeated_application_fails_closed(self):
        result, _ = apply_fr_tram_seats(self.baseline, self.config)
        with self.assertRaisesRegex(ValueError, "Conflicting existing displacement"):
            apply_fr_tram_seats(result, self.config)

    def test_existing_shared_or_displacement_properties_fail(self):
        for key in ("goff", "ap", "sh", "frseat"):
            bad = copy.deepcopy(self.baseline)
            bad[0]["properties"][key] = 0
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                apply_fr_tram_seats(bad, self.config)

    def test_preflight_all_selectors_before_mutation(self):
        bad = copy.deepcopy(self.config)
        second = copy.deepcopy(bad["independent"][0])
        second.update({"id": "second", "identity": ["Missing", "Line", "#123456", "urban"]})
        bad["independent"].append(second)
        with self.assertRaises(ValueError):
            apply_fr_tram_seats(self.baseline, bad)
        self.assertNotIn("goff", self.baseline[0]["properties"])

    def test_unbounded_or_unauthorised_config_rejected(self):
        for change in ({"ramp_m": 501}, {"bbox": [2, 48, 2.05, 48.01]}, {"why": ""}):
            bad = copy.deepcopy(self.config)
            bad["independent"][0].update(change)
            with self.assertRaises(ValueError):
                validate_config(bad)


class FrenchSourceRegression(unittest.TestCase):
    def test_source_preflight_rejects_every_changed_field_and_missing_extract(self):
        extract = {"ways": [[1, {"railway": "tram"}, [[2, 48], [2.01, 48]]]],
                   "relations": [[7, {"route": "tram"}, [["w", 1]]]],
                   "places": [], "named": [], "sources": [], "stations": [], "stops": {}}
        config = {"extract_fields_sha256": {key: digest(value) for key, value in extract.items()}}
        validate_extract(extract, config)
        with self.assertRaisesRegex(ValueError, "complete pinned extract"):
            validate_extract(None, config)
        for key in extract:
            changed = copy.deepcopy(extract)
            changed[key] = ["changed"]
            with self.assertRaisesRegex(ValueError, "Stale French extract field"):
                validate_extract(changed, config)

    def test_actual_revision_matches_pinned_extract_and_each_field(self):
        import hashlib
        config = load_config()
        raw = (ROOT / "data/raw/extract_fr.pkl").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), config["extract_sha256"])
        self.assertNotEqual(config["extract_sha256"], config["previous_extract_sha256"])
        validate_extract(pickle.loads(raw), config)

    def test_canonical_aliases_use_observed_master_colour(self):
        config = load_config()
        validate_config(config)
        for row in config["aliases"]:
            for rid in row["relations"]:
                for colour in row["source_colours"]:
                    key = row["network"], row["name"], colour
                    self.assertEqual(canonical_route_key(key, rid, config),
                                     (row["network"], row["name"], row["canonical_colour"]))
                    self.assertEqual(canonical_route_key(key, -1, config), key)
            with self.assertRaises(ValueError):
                canonical_route_key((row["network"], "Other line", row["source_colours"][0]),
                                    row["relations"][0], config)

    def test_no_network_or_colour_wide_merging(self):
        config = load_config()
        for key in (("Divia", "Tram T1", "#ab0672"), ("Other", "Tram B", "#762a80"),
                    ("FR:TAO", "Tram B", "#762a80")):
            self.assertEqual(canonical_route_key(key, 999999, config), key)

    def test_duplicate_alias_relation_rejected(self):
        config = load_config()
        config["aliases"][1]["relations"].append(config["aliases"][0]["relations"][0])
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_actual_eight_relations_and_source_key_contract(self):
        source = ROOT / "data/raw/extract_fr.pkl"
        if not source.exists():
            self.skipTest("Frozen French extract not available")
        checked = validate_alias_sources(pickle.loads(source.read_bytes()))
        self.assertEqual(len(checked), 8)
        self.assertEqual(len({row["after"] for row in checked}), 3)

    def test_all_city_bundle_entry_does_not_reapply_archived_manual_seats(self):
        import process_europe
        cfg = process_europe.COUNTRIES["fr"]
        self.assertIs(cfg.urban_bundles, True)
        self.assertIsNotNone(cfg.urban_seats)
        baseline = json.loads((ROOT / "data/fr_metro.geojson").read_text())["features"]
        self.assertFalse(any(f["properties"].get("frseat") for f in baseline))
        self.assertTrue(any(f["properties"].get("bn") is not None for f in baseline))


if __name__ == "__main__":
    unittest.main()
