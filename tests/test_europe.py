import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from process_europe import (COUNTRIES, kind_of, plain_name, rail_properties, speed,
                            speed_evidence, speed_of, stretch_of, urban_line_of_route)


def tags(*rows):
    return Counter({tuple(sorted(row.items())): length for row, length in rows})


class EuropeanCountryTest(unittest.TestCase):
    def test_all_european_countries_share_the_complete_layer_contract(self):
        # the seven of 2026-10-17, and Austria and Hungary (2026-10-21)
        self.assertEqual(set(COUNTRIES), {"de", "fr", "ch", "es", "nl", "be", "it", "at", "hu"})
        for code, country in COUNTRIES.items():
            self.assertEqual(country.code, code)
            self.assertTrue(country.cities)
            self.assertIn("tram", country.urban)
            self.assertIn("narrow_gauge", country.rail)
            self.assertIn("rail", country.rail)
            self.assertNotIn("train", country.urban)
            self.assertTrue(country.track_stretches)
            self.assertTrue(country.railway_relation_names)
            self.assertTrue(country.keep_unnamed_rail)
            self.assertFalse(country.merge_urban_by_colour)
            self.assertIsNone(country.many_colours)

    def test_track_and_structure_names_do_not_become_lines(self):
        self.assertEqual(plain_name("Gleis 2"), "")
        self.assertEqual(plain_name("Voie 1bis de Chaumont"), "")
        self.assertEqual(plain_name("Tunnel de Marseille"), "")
        self.assertEqual(plain_name("Ligne de Paris à Lyon"), "Ligne de Paris à Lyon")
        self.assertEqual(plain_name("Wanne-Eickel - Hamburg: Gleis 1"),
                         "Wanne-Eickel - Hamburg")
        self.assertEqual(plain_name("Raccordement d'Achères Voie 2A"),
                         "Raccordement d'Achères")
        self.assertEqual(plain_name("Lötschberg-Basistunnel Ostrohr"),
                         "Lötschberg-Basistunnel")
        self.assertEqual(plain_name("Lötschberg-Basistunnel Westrohr"),
                         "Lötschberg-Basistunnel")
        self.assertEqual(plain_name("Verbindungsgleis 1"), "Verbindungsgleis")
        self.assertEqual(plain_name("Verbindungsgleis 2"), "Verbindungsgleis")
        self.assertEqual(plain_name("Allaccio Provvisorio al binario dispari"), "")
        self.assertEqual(plain_name("Ligne 162 Namur - Arlon -"),
                         "Ligne 162 Namur - Arlon -")
        self.assertEqual(plain_name(None), "")
        # Actual Dutch OSM w6304155 and w44288572 are platform track labels.
        for name in ("Spoor 4", "Spoor 5a", "spoor 11"):
            self.assertEqual(plain_name(name), "")

    def test_speed_values_include_mph_and_lists(self):
        self.assertEqual(speed("200; 160"), 200)
        self.assertEqual(speed("125 mph"), 201)
        self.assertIsNone(speed("signals"))
        for value in ("DE:200", "200 @ (wet)", "track 300", "-160", "0", "300;signals"):
            self.assertIsNone(speed(value), value)
        self.assertIsNone(speed_evidence({"maxspeed:design": "300;160"}))
        self.assertIsNone(speed_evidence({"maxspeed": "300;160"}))

    def test_regular_narrow_gauge_is_not_heritage(self):
        vote = tags(({"railway": "narrow_gauge", "usage": "main"}, 10))
        self.assertEqual(kind_of("Rhätische Bahn", vote), "main")

    def test_preserved_track_is_heritage(self):
        vote = tags(({"railway": "rail", "railway:preserved": "yes"}, 10))
        self.assertEqual(kind_of("Museum railway", vote), "heritage")
        self.assertEqual(kind_of("Museum railway", tags(({"railway": "preserved"}, 10))), "heritage")

    def test_class_and_speed_use_uniform_track_evidence_not_majority_votes(self):
        fast = tags(({"railway": "rail", "highspeed": "yes", "maxspeed": "300"}, 8))
        self.assertEqual(kind_of("LGV", fast), "hs")
        self.assertEqual(speed_of("LGV", "hs", fast), (300, True, "OSM:maxspeed"))
        mixed = tags(({"railway": "rail", "highspeed": "yes", "maxspeed": "300"}, 8),
                     ({"railway": "rail", "usage": "main", "maxspeed": "80"}, 2))
        with self.assertRaisesRegex(ValueError, "stretches"):
            kind_of("mixed line", mixed)
        with self.assertRaisesRegex(ValueError, "votes"):
            speed_of("mixed line", "hs", mixed)

    def test_a_fast_name_or_service_is_not_a_speed_standard(self):
        ordinary = tags(({"railway": "rail", "usage": "main", "maxspeed": "80"}, 1))
        for name in ("LGV", "ICE", "TGV", "S-Bahn", "RER A", "Cercanías C-1"):
            self.assertEqual(kind_of(name, ordinary), "main")
            self.assertIsNone(speed_of(name, "main", ordinary))
        unknown = tags(({"railway": "rail", "usage": "main", "highspeed": "yes"}, 1))
        self.assertEqual(kind_of("LGV", unknown), "main")
        self.assertIsNone(speed_of("LGV", "main", unknown))

    def test_design_evidence_is_distinct_from_operating_limit(self):
        row = {"railway": "rail", "maxspeed:design": "300", "maxspeed": "80"}
        vote = tags((row, 1))
        self.assertEqual(kind_of("A", vote), "hs")
        self.assertEqual(speed_of("A", "hs", vote), (300, False, "OSM:maxspeed:design"))
        props = rail_properties({12: row, 9: row})
        self.assertEqual(props["speed_basis"], "osm_design")
        self.assertEqual(props["osm_design_speed"], 300)
        self.assertEqual(props["osm_maxspeed"], 80)
        self.assertEqual(props["ref"], "https://www.openstreetmap.org/way/9#maxspeed:design")
        self.assertEqual(props["maxspeed_ref"], "https://www.openstreetmap.org/way/9#maxspeed")
        self.assertEqual(props["source_way_ids"], "9,12")
        self.assertNotIn("design_unresolved", props)
        self.assertEqual(speed_evidence({"design_speed": "250 km/h", "maxspeed": "160"}), (250, False, "design_speed"))

    def test_conflicting_or_invalid_design_tags_are_not_a_confirmed_standard(self):
        for row in ({"maxspeed:design": "300", "design_speed": "250", "maxspeed": "200"},
                    {"maxspeed:design": "signals", "maxspeed": "200"},
                    {"maxspeed:design": "300;160", "maxspeed": "200"}):
            self.assertEqual(speed_evidence(row), (200, True, "maxspeed"))
            props = rail_properties({42: row})
            self.assertEqual(props["speed_basis"], "osm_maxspeed")
            self.assertEqual(props["design_unresolved"], 1)
            self.assertNotIn("osm_design_speed", props)
            self.assertEqual(props["ref"], "https://www.openstreetmap.org/way/42#maxspeed")
        self.assertEqual(speed_evidence({"maxspeed:design": "300", "design_speed": "300"}), (300, False, "maxspeed:design"))

    def test_explicit_low_speed_fast_track_keeps_its_own_band(self):
        low = tags(({"railway": "rail", "highspeed": "yes", "maxspeed": "120"}, 1))
        self.assertEqual(kind_of("LGV approach", low), "hs")
        self.assertEqual(speed_of("LGV approach", "hs", low), (120, True, "OSM:maxspeed"))
        a = {"railway": "rail", "maxspeed": "300", "highspeed": "yes"}
        b = {"railway": "rail", "maxspeed": "120", "highspeed": "yes"}
        self.assertNotEqual(stretch_of("LGV", a, []), stretch_of("LGV", b, []))
        self.assertEqual(stretch_of("LGV", a, []), stretch_of("LGV", dict(reversed(list(a.items()))), []))

    def test_uncoloured_city_route_ref_is_not_its_network_name(self):
        one = urban_line_of_route({"network": "Metro", "name": "Metro: west", "ref": "1"}, {})
        two = urban_line_of_route({"network": "Metro", "name": "Metro: east", "ref": "2"}, {})
        self.assertEqual(one, ("Metro", "Metro 1", None))
        self.assertNotEqual(one, two)
        self.assertEqual(urban_line_of_route({"network": "Metro", "name": "Metro: west"}, {}),
                         ("Metro", "Metro: west", None))
        self.assertEqual(urban_line_of_route({"network": "Metro", "ref": "2", "colour": "#112233"},
                                            {"name": "Ligne A", "colour": "#abcdef"}),
                         ("Metro", "Ligne A", "#112233"))

    def test_rotterdam_network_does_not_fall_into_overlapping_hague_radius(self):
        city_of = COUNTRIES["nl"].urban_city_of
        for name in ("Metro A", "Metro B", "Metro E", "Tram 1"):
            self.assertEqual(city_of("Rail Rotterdam", name, None, "海牙"), "鹿特丹")
        self.assertEqual(city_of("Rail Haaglanden", "Tram 1", None, "鹿特丹"), "海牙")
        self.assertEqual(city_of("no", "Tram 10", None, "海牙"), "鹿特丹")
        self.assertEqual(city_of("no", "Tourist Tram", None, "海牙"), "海牙")
        self.assertIsNone(COUNTRIES["fr"].urban_city_of)

    def test_lille_metro_edge_fragment_is_not_a_belgian_city_network(self):
        actual = {"network": "Ilévia", "operator": "Keolis Lille Métropole",
                  "name": "Métro Ligne 2 : Saint-Philibert → CH Dron",
                  "ref": "2", "colour": "#ED1D24"}
        self.assertEqual(COUNTRIES["be"].urban_line_of(actual, {}), ("Ilévia", "", None))
        self.assertTrue(COUNTRIES["fr"].urban_line_of(actual, {})[1])

    def test_tenerife_directions_with_and_without_ref_are_the_same_sourced_line(self):
        one = urban_line_of_route({"network": "MetroTenerife", "ref": "T2", "colour": "blue",
                                   "name": "Tranvia Línea 2: Tíncer → La Cuesta"}, {})
        other = urban_line_of_route({"network": "MetroTenerife", "colour": "blue",
                                     "name": "Tranvia Línea 2: La Cuesta → Tincer"}, {})
        self.assertEqual(one, other)
        first = urban_line_of_route({"network": "MetroTenerife",
                                     "name": "Tranvía Línea 1: La Trinidad → Intercambiador"},
                                    {"name": "Tranvía Línea 1"})
        self.assertNotEqual(first[1], one[1])
        self.assertEqual(urban_line_of_route({"name": "Monorraíl T4"}, {})[1], "")

    def test_park_ride_is_excluded_but_public_tram_to_stadium_is_kept(self):
        self.assertEqual(urban_line_of_route(
            {"operator": "Europa-Park Rust", "name": "EP-Express", "ref": "E.P.E."}, {})[1], "")
        self.assertTrue(urban_line_of_route(
            {"operator": "Freiburger Verkehrs AG", "name": "Tram: Europa-Park Stadion", "ref": "SC"}, {})[1])


if __name__ == "__main__":
    unittest.main()
