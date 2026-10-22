"""Germany's elsewhere listed by its real cities (2026-10-22): process_europe's list and its switches."""
import json
import sys
import unittest
from pathlib import Path

from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from europe_urban_policy import nearest_city
from endpoint_sources import ENDPOINT_CITIES
import process_europe


class GermanElsewhereCities(unittest.TestCase):
    de = process_europe.COUNTRIES["de"]

    def test_names_are_new_and_unique(self):
        names = [c[0] for c in self.de.urban_elsewhere_cities]
        self.assertEqual(len(names), len(set(names)))
        self.assertFalse(set(names) & {c[0] for c in self.de.cities} | ({self.de.elsewhere} & set(names)))
        # only Germany splits its elsewhere; the other countries' lines keep their cities
        for code, cfg in process_europe.COUNTRIES.items():
            if code != "de":
                self.assertEqual(cfg.urban_elsewhere_cities, ())

    def test_each_city_is_its_own_nearest(self):
        cities = self.de.urban_elsewhere_cities
        for name, lon, lat, reach in cities:
            self.assertEqual(nearest_city(cities, Point(lon, lat), self.de.elsewhere), name)
        self.assertEqual(nearest_city(cities, Point(6.0, 54.5), self.de.elsewhere), self.de.elsewhere)

    def test_chinese_names_have_a_source(self):
        # from the label table (Wikidata zh-cn) or names.CITY_NAMES, where each row gives its Wikidata item
        table = json.loads((ROOT / "data" / "europe_city_names.json").read_text())["countries"]["de"]
        from names import CITY_NAMES
        sourced = {row["nz"] for row in table.values()} | set(CITY_NAMES["de"])
        for name, *_ in self.de.urban_elsewhere_cities:
            self.assertTrue(any("一" <= ch <= "鿿" for ch in name), name)
            self.assertIn(name, sourced)
        source = (ROOT / "scripts" / "names.py").read_text()
        for name in set(CITY_NAMES["de"]) - {row["nz"] for row in table.values()}:
            row = next(line for line in source.splitlines() if f'"{name}"' in line)
            if name in {c[0] for c in self.de.urban_elsewhere_cities}:
                self.assertRegex(row, r"# Q\d+ ")

    def test_switches_name_only_known_cities(self):
        known = {c[0] for c in self.de.cities} | {c[0] for c in self.de.urban_elsewhere_cities} | {self.de.elsewhere}
        self.assertLessEqual(set(ENDPOINT_CITIES["de"]), known)
        self.assertLessEqual(set(process_europe.ONE_COPY_LEFT_OUT["de"]), known)
        # Heilbronn's S4 shares Karlsruhe's track: switched on it would join Karlsruhe's endpoint group
        self.assertNotIn("海尔布隆", ENDPOINT_CITIES["de"])

    def test_each_real_city_has_its_reviewed_switches(self):
        import line_bundles
        split = [c[0] for c in self.de.urban_elsewhere_cities]
        endpoint = set(ENDPOINT_CITIES["de"]) & set(split)
        self.assertEqual(set(split) - endpoint, {"海尔布隆", "科特布斯", "马格德堡"})
        # endpoint ordering in these cities closes up branch stubs too (their pinches 10 -> 6)
        self.assertLessEqual(endpoint, set(line_bundles.BRANCH_STUB_CITIES))
        self.assertEqual(set(process_europe.ONE_COPY_LEFT_OUT["de"]) & set(split), {"乌尔姆", "马格德堡"})


if __name__ == "__main__":
    unittest.main()
