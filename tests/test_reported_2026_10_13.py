"""Two faults readers reported on 2026-10-13, checked on the generated data.

1. A route from 臺北 to 臺南 changed trains at 新市, where the 台灣高速鐵路 only runs past.
2. 横浜's blue line had no track between センター北 and センター南.
"""
import json
import math
import unittest
from collections import defaultdict
from pathlib import Path

from shapely.geometry import Point, shape

DATA = Path(__file__).resolve().parents[1] / "data"


def metres(a, b):
    return math.hypot((a[0] - b[0]) * math.cos(math.radians(a[1])), a[1] - b[1]) * 111320


class PassingFastLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        graph = json.loads((DATA / "graph.json").read_text())
        cls.lines, edges = graph["lines"], graph["edges"]
        cls.at, cls.links, cls.walks = defaultdict(set), defaultdict(set), defaultdict(set)
        for k in range(0, len(edges), 5):
            u, v, li = edges[k:k + 3]
            kind = cls.lines[li][1]
            if kind in ("x", "y"):
                cls.links[u].add(v)
            elif kind == "w":
                cls.walks[u].add(v)
                cls.walks[v].add(u)
            else:
                cls.at[u].add(cls.lines[li][0])
                cls.at[v].add(cls.lines[li][0])
        cls.stations = json.loads((DATA / "stations.geojson").read_text())["features"]

    def station(self, name, near):
        found = [f for f in self.stations if f["properties"]["n"] == name and metres(f["geometry"]["coordinates"], near) < 2000]
        self.assertEqual(len(found), 1, name)
        return found[0]["properties"]

    def lines_of(self, props):
        return set().union(*(self.at[node] for node in self.links[props["g"]]))

    def test_the_fast_line_runs_past_xinshi(self):
        xinshi = self.station("新市", (120.2897, 23.0682))
        self.assertIn("縱貫線", self.lines_of(xinshi))
        self.assertNotIn("台灣高速鐵路", self.lines_of(xinshi))
        self.assertNotIn("h", xinshi)

    def test_the_fast_line_still_stops_at_its_own_stations(self):
        for name, near in (("台南", (120.2864, 22.9247)), ("新竹", (121.0402, 24.8083)), ("台中", (120.6159, 24.1121))):
            station = self.station(name, near)
            self.assertIn("台灣高速鐵路", self.lines_of(station), name)
            self.assertIn("h", station, name)

    def test_the_station_beside_a_fast_lines_station_is_a_walk_away(self):
        for name, near in (("六家", (121.0394, 24.8071)), ("沙崙", (120.2863, 22.9239))):
            station = self.station(name, near)
            self.assertNotIn("台灣高速鐵路", self.lines_of(station), name)
            self.assertTrue(self.walks[station["g"]], name)


class YokohamaBlueLine(unittest.TestCase):
    def test_track_between_center_kita_and_center_minami(self):
        blue = [shape(f["geometry"]) for f in json.loads((DATA / "jp_metro.geojson").read_text())["features"]
                if f["properties"]["n"] in ("横浜市営1号線", "横浜市営3号線")]
        self.assertTrue(blue)
        south, north = (139.5746, 35.5453), (139.5786, 35.5533)       # センター南, センター北
        for i in range(1, 8):
            at = (south[0] + (north[0] - south[0]) * i / 8, south[1] + (north[1] - south[1]) * i / 8)
            nearest = min(g.distance(Point(at)) for g in blue) * 111320
            self.assertLess(nearest, 150, f"no blue line within 150 m of {at}")


if __name__ == "__main__":
    unittest.main()
