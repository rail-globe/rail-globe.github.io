import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_tiles


class TileParallelPropertiesTest(unittest.TestCase):
    def test_single_unseated_service_keeps_source_identity(self):
        feature = {
            "type": "Feature",
            "properties": {"g": "be", "ct": "列日", "n": "Tram T1",
                           "network": "TECL", "rid": "18173306,18173307",
                           "col": "#abcdef", "jk": "urban"},
            "geometry": {"type": "LineString", "coordinates": [[5.57, 50.63], [5.58, 50.64]]},
        }
        with patch.object(build_tiles, "features", side_effect=lambda layer, country:
                          [feature] if layer == "metro" else []):
            text, layers = build_tiles.tippecanoe_input("be")
        self.assertEqual(layers, ["metro"])
        properties = json.loads(text)["properties"]
        self.assertEqual(properties["network"], "TECL")
        self.assertEqual(properties["rid"], "18173306,18173307")
        self.assertNotIn("off", properties)

    def test_parallel_identity_survives_the_tile_input_in_every_line_layer(self):
        marks = {"off": 0, "sh": 1, "bn": 3, "lead": 0}
        feature = {
            "type": "Feature",
            "properties": {"n": "shared route", "c": "main", **marks, "ref": "source kept in GeoJSON"},
            "geometry": {"type": "LineString", "coordinates": [[140, 39], [140.01, 39]]},
        }
        layers = {"hsr", "conv", "shared", "metro"}
        with patch.object(build_tiles, "features", side_effect=lambda layer, country: [feature] if layer in layers else []):
            text, present = build_tiles.tippecanoe_input("cn")
        self.assertEqual(set(present), layers)
        rows = [json.loads(line) for line in text.splitlines()]
        self.assertEqual(len(rows), len(layers))
        for row in rows:
            self.assertEqual({k: row["properties"].get(k) for k in marks}, marks, row["tippecanoe"]["layer"])
            self.assertNotIn("ref", row["properties"])

    def test_cross_category_component_and_unfinished_speed_survive_tile_input(self):
        def feature(layer, country):
            p = {"n": "example", "c": "build", "goff": -.25, "ap": 1, "d": 320, "ud": 320, "ue": "A~B", "de": "A~B"}
            return [{"type": "Feature", "properties": p,
                     "geometry": {"type": "LineString", "coordinates": [[140, 39], [140.01, 39]]}}] if layer in {"metro", "conv", "build"} else []
        with patch.object(build_tiles, "features", side_effect=feature):
            text, _ = build_tiles.tippecanoe_input("jp")
        rows = {r["tippecanoe"]["layer"]: r["properties"] for r in map(json.loads, text.splitlines())}
        self.assertEqual(rows["metro"]["goff"], -.25)
        self.assertEqual(rows["metro"]["ap"], 1)
        self.assertEqual(rows["conv"]["goff"], -.25)
        self.assertEqual(rows["conv"]["ud"], 320)
        self.assertEqual(rows["build"]["d"], 320)
        self.assertEqual(rows["build"]["de"], "A~B")


if __name__ == "__main__":
    unittest.main()
