"""Inland boundary contracts; never rebuild railway or camera data."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_europe_borders as borders

DATA = Path(os.environ.get("BORDERS_DATA_DIR", ROOT / "data"))
CACHE = Path(os.environ.get("BORDERS_CACHE_DIR", borders.DEFAULT_CACHE))
NEIGHBORS = {
    "de": {"AUT", "BEL", "CHE", "CZE", "DNK", "FRA", "LUX", "NLD", "POL"},
    "fr": {"AND", "BEL", "CHE", "DEU", "ESP", "ITA", "LUX", "MCO"},
    "ch": {"AUT", "DEU", "FRA", "ITA", "LIE"},
    "es": {"AND", "FRA", "GIB", "MAR", "PRT"},
    "nl": {"BEL", "DEU"}, "be": {"DEU", "FRA", "LUX", "NLD"},
    "it": {"AUT", "CHE", "FRA", "SMR", "SVN", "VAT"},
}


class BoundaryDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (CACHE / borders.SOURCE["cache_file"]).exists():
            # the GISCO lines are a 51 MB download kept out of the repository (data/cache is not committed)
            raise unittest.SkipTest("the cached GISCO boundary lines are not present")
        cls.canonical_bytes = (DATA / "europe_borders.geojson").read_bytes()
        cls.visible = json.loads(cls.canonical_bytes)
        cls.raw, cls.receipt = borders.load_source(CACHE, offline=True)
        cls.features = {f["properties"]["g"]: f for f in cls.visible["features"]}
        cls.lines = {g: unary_union([LineString(p) for p in f["geometry"]["coordinates"]])
                     for g, f in cls.features.items()}

    def test_countries_and_inland_contract(self):
        self.assertEqual(set(self.features), set(borders.COUNTRIES))
        self.assertIn("no coastlines or maritime", self.visible["purpose"])
        self.assertIn("not ADM1", self.visible["purpose"])
        self.assertEqual(self.visible["selection"]["COAS_FLAG"], "F")
        self.assertEqual(self.visible["crs_note"], "WGS84 longitude, latitude")
        # 29 for the seven of 2026-10-17; Austria and Hungary added 11 (2026-10-21)
        self.assertEqual(self.visible["selection"]["unique_in_scope_boundaries"], 40)

    def test_finite_actual_lines_not_closed_country_outlines(self):
        for g, feature in self.features.items():
            with self.subTest(country=g):
                self.assertEqual(feature["properties"], {"g": g, "k": "land"})
                self.assertEqual(feature["geometry"]["type"], "MultiLineString")
                parts = feature["geometry"]["coordinates"]
                self.assertTrue(any(p[0] != p[-1] for p in parts))
                for points in parts:
                    self.assertGreaterEqual(len(points), 2)
                    self.assertTrue(LineString(points).is_simple)
                    self.assertTrue(all(len(p) == 2 and all(math.isfinite(v) for v in p)
                                        and -180 <= p[0] <= 180 and -90 <= p[1] <= 90 for p in points))
                counts = self.visible["counts"][g]
                self.assertEqual(counts["parts"], len(parts))
                self.assertEqual(counts["display_vertices"], sum(map(len, parts)))
                self.assertEqual(counts["continuous_error_bound_degrees"], 0)

    def test_every_in_scope_noncoastal_source_part_preserved_exactly(self):
        self.assertEqual(self.receipt["sha256"], self.visible["sources"]["gisco"]["sha256"])
        self.assertEqual(self.receipt["download_bytes"], 52305233)
        self.assertEqual(len(self.raw["features"]), 564)
        self.assertEqual(borders.build(CACHE, offline=True), self.visible)
        for g, iso3 in borders.COUNTRIES.items():
            expected = []
            for f in sorted(self.raw["features"], key=lambda f: f["properties"]["CNTR_BN_ID"]):
                p = f["properties"]
                if p["COAS_FLAG"] != "F" or iso3 not in (p["LEFT_URI"], p["RIGHT_URI"]):
                    continue
                if not p["LEFT_URI"] or not p["RIGHT_URI"] or p["LEFT_URI"] == p["RIGHT_URI"]:
                    continue
                for points in f["geometry"]["coordinates"]:
                    if all(-25 <= x <= 45 and 34 <= y <= 72 for x, y in points):
                        expected.append(points)
            self.assertEqual(self.features[g]["geometry"]["coordinates"], expected, g)

    def test_all_neighbors_including_not_yet_enabled_countries(self):
        for g, expected in NEIGHBORS.items():
            counts = self.visible["counts"][g]
            self.assertEqual(set(counts["neighbors"]), expected, g)
            self.assertTrue(all(p["COAS_FLAG"] == "F" for p in counts["boundaries"]))

    def test_coastlines_and_french_overseas_have_no_line_overlap(self):
        visible = unary_union(list(self.lines.values()))
        coast_count = 0
        for f in self.raw["features"]:
            p = f["properties"]
            if p["COAS_FLAG"] == "T" and set(borders.COUNTRIES.values()).intersection(
                    (p["LEFT_URI"], p["RIGHT_URI"])):
                coast_count += 1
                coast = unary_union([LineString(points) for points in f["geometry"]["coordinates"]])
                self.assertLessEqual(visible.intersection(coast).length, 1e-12)
        self.assertEqual(coast_count, 6)
        for bounds in [(-18.5, 27.5, -13, 29.5), (1, 38, 5, 40.5), (8, 41.3, 9.7, 43.1),
                       (8, 38.7, 10, 41.3), (12, 36, 16, 39), (-65, -5, -45, 20)]:
            self.assertTrue(visible.intersection(box(*bounds)).is_empty, bounds)

    def test_ceuta_melilla_and_real_inland_river_lake_borders(self):
        es_parts = self.features["es"]["geometry"]["coordinates"]
        records = self.visible["counts"]["es"]["boundaries"]
        self.assertEqual(next(p for p in records if p["id"] == 493)["parts"], [0, 1])
        for bounds in [(-5.39, 35.86, -5.33, 35.92), (-2.98, 35.26, -2.92, 35.33)]:
            parts = [p for p in es_parts if LineString(p).intersects(box(*bounds))]
            self.assertEqual(len(parts), 1)
            self.assertNotEqual(parts[0][0], parts[0][-1])
        for name, g, x, y in [("Rhine", "fr", 7.80, 48.575),
                              ("Lake Geneva", "ch", 6.50, 46.40),
                              ("Lake Constance generalized boundary", "de", 9.45, 47.57)]:
            self.assertLess(self.lines[g].distance(Point(x, y)), 0.05, name)

    def test_baarle_vennbahn_and_small_enclave_limitations(self):
        for g, boundary_id, closed_count in [("be", 500, 4), ("be", 499, 1),
                                             ("es", 515, 1), ("ch", 557, 1), ("it", 535, 1)]:
            source = next(f for f in self.raw["features"] if f["properties"]["CNTR_BN_ID"] == boundary_id)
            rings = [p for p in source["geometry"]["coordinates"] if p[0] == p[-1]]
            self.assertEqual(len(rings), closed_count)
            for points in rings:
                self.assertIn(points, self.features[g]["geometry"]["coordinates"])
        baarle = [p for p in self.features["be"]["geometry"]["coordinates"] if p[0] == p[-1]]
        self.assertTrue(any(Polygon(p).covers(Point(4.931, 51.442)) for p in baarle))
        self.assertTrue(any(Polygon(p).covers(Point(6.258573849229325, 50.642582996000044))
                            for p in baarle))
        self.assertTrue(any("not all exclaves" in note for note in self.visible["limitations"]))

    def test_shared_boundaries_identical_for_each_g(self):
        for i, (g, iso3) in enumerate(borders.COUNTRIES.items()):
            for other, other_iso3 in list(borders.COUNTRIES.items())[i + 1:]:
                for source in self.raw["features"]:
                    p = source["properties"]
                    if {p["LEFT_URI"], p["RIGHT_URI"]} != {iso3, other_iso3}:
                        continue
                    for points in source["geometry"]["coordinates"]:
                        if borders.in_scope(points):
                            self.assertIn(points, self.features[g]["geometry"]["coordinates"])
                            self.assertIn(points, self.features[other]["geometry"]["coordinates"])

    def test_packed_hash_binds_canonical_bytes(self):
        packed = json.loads((DATA / "europe_borders.packed.json").read_bytes())
        self.assertEqual(packed["canonical_sha256"], hashlib.sha256(self.canonical_bytes).hexdigest())
        self.assertEqual(packed, borders.packed_boundaries(self.visible, self.canonical_bytes))


def fixture(flag="F", left="FRA", right="ESP", points=None, geometry_type="MultiLineString"):
    parts = points or [[[0, 40], [1, 41]]]
    return {"type": "Feature", "properties": {"CNTR_BN_ID": 1, "COAS_FLAG": flag,
            "LEFT_URI": left, "RIGHT_URI": right, "POL_STAT": 0},
            "geometry": {"type": geometry_type,
                         "coordinates": parts[0] if geometry_type == "LineString" else parts}}


class BoundaryAlgorithmTests(unittest.TestCase):
    def test_explicit_flags_and_distinct_countries_not_distance_matching(self):
        for feature, reason in [(fixture("T"), "coastline"), (fixture(right=None), "not two"),
                                (fixture(right="FRA"), "not two"), (fixture(right="FR"), "not two")]:
            selected, excluded = borders.select_boundaries({"features": [feature]})
            self.assertEqual(selected, [])
            self.assertIn(reason, excluded[0]["reason"])
        for flag in [None, "false", False]:
            with self.assertRaisesRegex(ValueError, "COAS_FLAG"):
                borders.select_boundaries({"features": [fixture(flag)]})
        selected, _ = borders.select_boundaries({"features": [fixture(right="MCO")]})
        self.assertEqual(len(selected), 1)

    def test_whole_parts_excluded_never_clipped_or_joined(self):
        f = fixture(points=[[[0, 40], [1, 41]], [[-54, 4], [-53, 5]]])
        selected, excluded = borders.select_boundaries({"features": [f]})
        self.assertEqual(selected[0][1], [0])
        self.assertEqual(excluded[0]["part"], 1)
        with self.assertRaisesRegex(ValueError, "straddles"):
            borders.in_scope([[0, 40], [-54, 4]])

    def test_open_lines_and_closed_foreign_enclaves_retained(self):
        for points in [[[[0, 40], [1, 41]]], [[[0, 40], [1, 40], [1, 41], [0, 40]]]]:
            f = fixture(points=points)
            self.assertEqual(borders.line_parts(f), points)
            selected, _ = borders.select_boundaries({"features": [f]})
            self.assertEqual(selected[0][1], [0])
        self.assertEqual(borders.line_parts(fixture(geometry_type="LineString")), [[[0, 40], [1, 41]]])

    def test_invalid_geometry_and_duplicate_ids_rejected(self):
        for f in [fixture(geometry_type="Polygon"), fixture(points=[[[0, 40]]]),
                  fixture(points=[[[0, 40], [0, 40]]]),
                  fixture(points=[[[0, 40], [float("nan"), 41]]]),
                  fixture(points=[[[0, 40], [200, 41]]]),
                  fixture(points=[[[0, 40], [1, 41], [0, 41], [1, 40]]])]:
            with self.assertRaises(ValueError):
                borders.select_boundaries({"features": [f]})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            borders.select_boundaries({"features": [fixture(), copy.deepcopy(fixture())]})

    def test_missing_changed_or_unpinned_cache_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            with self.assertRaises(FileNotFoundError):
                borders.load_source(cache, offline=True)
            with patch.object(borders, "urlopen") as request:
                request.return_value.__enter__.return_value.read.return_value = b"{}"
                with self.assertRaisesRegex(ValueError, "hash changed"):
                    borders.load_source(cache)
                self.assertFalse((cache / borders.SOURCE["cache_file"]).exists())
            (cache / borders.SOURCE["cache_file"]).write_text("{}")
            with self.assertRaisesRegex(ValueError, "hash changed"):
                borders.load_source(cache, offline=True)


if __name__ == "__main__":
    unittest.main()
