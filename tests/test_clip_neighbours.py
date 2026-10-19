import json
import sys
import unittest
from pathlib import Path

from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from clip_neighbours import clip


def line(coords, **props):
    return {"type": "Feature", "properties": props, "geometry": {"type": "LineString", "coordinates": coords}}


class ClipNeighbours(unittest.TestCase):
    """2026-10-19: China's extract drew 磨万铁路, station tracks and 磨丁 inside Laos."""

    land = box(1.0, 0.0, 2.0, 1.0)                     # the neighbour, east of x = 1

    def test_a_line_is_cut_at_the_border_and_points_inside_go(self):
        crossing = line([[0.5, 0.5], [1.5, 0.5]], n="A")
        point = {"type": "Feature", "properties": {"n": "B"}, "geometry": {"type": "Point", "coordinates": [1.5, 0.5]}}
        kept, cut, dropped = clip([crossing, point], self.land)
        self.assertEqual((cut, dropped), (1, ["B"]))
        self.assertEqual(kept[0]["geometry"]["coordinates"], [[0.5, 0.5], [1.0, 0.5]])

    def test_parts_away_from_the_border_are_kept_as_they_are(self):
        far = [[0.1, 0.1], [0.2, 0.2], [0.3, 0.1]]
        multi = {"type": "Feature", "properties": {}, "geometry": {"type": "MultiLineString",
                 "coordinates": [far, [[1.2, 0.2], [1.8, 0.2]]]}}
        kept, cut, dropped = clip([multi], self.land)
        self.assertEqual(kept[0]["geometry"]["coordinates"], [far])

    def test_a_sliver_left_at_the_border_is_dropped_and_a_second_run_changes_nothing(self):
        sliver = line([[0.9997, 0.5], [1.5, 0.5]], n="C")          # about 33 m on this side
        kept, cut, dropped = clip([sliver], self.land)
        self.assertEqual(dropped, ["C"])
        once, _, _ = clip([line([[0.5, 0.5], [1.5, 0.5]])], self.land)
        twice, cut2, dropped2 = clip(once, self.land)
        self.assertEqual((json.dumps(twice), cut2, dropped2), (json.dumps(once), 0, []))


if __name__ == "__main__":
    unittest.main()
