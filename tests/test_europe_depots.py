"""Depot names on buildings: source extraction, ground containment, and legacy scope."""
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import depots
from extract_osm import named_ground


def coords(east, north):
    return (8.52 + east / (111320 * math.cos(math.radians(47.37))),
            47.37 + north / 111320)


def source(file_path):
    rows = ['<osm version="0.6">']
    node_id = 0
    for way_id, name, east in (
            (101, "Tramdepot Kalkbreite (Elisabethenstrasse)", 0),
            (102, "Tramdepot ohne Gleise", 2000),
            (103, "Bus Depot", 0),
            (104, "Feuerwehrdepot Oerlikon", 0),
            (105, "Office", 0),
            (106, "Dépot du M2", 2000)):
        refs = []
        for x, y in ((east - 10, -10), (east + 410, -10),
                     (east + 410, 60), (east - 10, 60)):
            node_id += 1
            lon, lat = coords(x, y)
            rows.append(f'<node id="{node_id}" lon="{lon}" lat="{lat}" version="1"/>')
            refs.append(node_id)
        rows.append(f'<way id="{way_id}" version="1">')
        rows.extend(f'<nd ref="{n}"/>' for n in refs + refs[:1])
        rows.append(f'<tag k="building" v="industrial"/><tag k="name" v="{name}"/></way>')
    rows.append('</osm>')
    file_path.write_text("\n".join(rows))


class EuropeanDepotBuildingsTest(unittest.TestCase):
    def test_actual_building_name_reaches_label_only_on_its_yard_track(self):
        with tempfile.TemporaryDirectory() as folder:
            file_path = Path(folder) / "buildings.osm"
            source(file_path)
            objects = named_ground(str(file_path), "ch")
        self.assertEqual({o["osm"] for o in objects}, {"w101", "w102", "w106"})
        self.assertTrue(all(o["form"] == "building=industrial" for o in objects))
        tracks = [[coords(0, y), coords(400, y)] for y in range(0, 40, 5)]
        labels, _ = depots.labels("ch", tracks, objects)
        self.assertEqual([row[0] for row in labels],
                         ["Tramdepot Kalkbreite (Elisabethenstrasse)"])
        self.assertEqual(labels[0][-1], "ground")

    def test_legacy_extraction_does_not_gain_unrequested_building_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            file_path = Path(folder) / "buildings.osm"
            source(file_path)
            self.assertEqual(named_ground(str(file_path), "uk"), [])

    def test_explicit_metro_depot_building_can_stand_by_its_running_line(self):
        tracks = [[coords(0, y), coords(400, y)] for y in range(0, 40, 5)]
        building = {"form": "building=transportation", "osm": "w1", "name": "Dépot du M2",
                    "key": "name", "at": coords(200, 700),
                    "ring": [[coords(190, 690), coords(210, 690), coords(210, 710),
                              coords(190, 710), coords(190, 690)]]}
        running = [[coords(0, 900), coords(400, 900)]]
        labels, _ = depots.labels("ch", tracks, [building], running=running)
        self.assertEqual([row[0] for row in labels], ["Dépot du M2"])
        self.assertEqual(depots.labels("ch", tracks, [building])[0], [])

    def test_german_betriebshof_requires_rail_track_and_bus_compounds_are_rejected(self):
        # Actual OSM naming patterns from the Marzahn and Möhringen depot audit.
        name = "Straßenbahn Betriebshof Marzahn"
        self.assertTrue(depots.worth_keeping("de", name, "landuse=industrial"))
        self.assertFalse(depots.names_a_depot("de", name, "landuse=industrial", share=0))
        self.assertTrue(depots.names_a_depot("de", name, "landuse=industrial", share=0.8))
        for bus in ("SSB Busbetriebshof Zentrum BF7", "Buswerkstatt Heerdt", "Omnibus Betriebshof"):
            self.assertFalse(depots.worth_keeping("de", bus, "landuse=industrial"), bus)
        self.assertFalse(depots.worth_keeping("uk", name, "landuse=industrial"))

    def test_french_technical_centre_uses_its_source_name_only_on_rail_tracks(self):
        # Actual OSM w1097984884 and w493690708, at the Nantes and Angers tram depots.
        for name in ("Centre Technique et d'Exploitation de Babinière",
                     "Centre technique des Transports Raymond Perron"):
            self.assertTrue(depots.worth_keeping("fr", name, "landuse=industrial"))
            self.assertFalse(depots.names_a_depot("fr", name, "landuse=industrial", share=0))
            self.assertTrue(depots.names_a_depot("fr", name, "landuse=industrial", share=0.8))
            self.assertFalse(depots.worth_keeping("uk", name, "landuse=industrial"))
        self.assertFalse(depots.worth_keeping("fr", "Centre technique des autobus", "landuse=industrial"))

    def test_belgian_stelplaats_is_retained_but_needs_a_rail_track_fan(self):
        # Actual OSM w64038826: landuse=industrial, operator=De Lijn.
        name = "Stelplaats Deurne (Tram)"
        self.assertTrue(depots.worth_keeping("be", name, "landuse=industrial"))
        self.assertFalse(depots.names_a_depot("be", name, "landuse=industrial", share=0))
        self.assertTrue(depots.names_a_depot("be", name, "landuse=industrial", share=0.8))


if __name__ == "__main__":
    unittest.main()
