"""Regression cases for the joins visible on the map, independent of OSM downloads."""
import math
import sys
import unittest
from pathlib import Path

from shapely.geometry import LineString, Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from single_track import bridge, smooth, stitch, unfold
from finish_display import finish_metro


def angles(coords):
    for a, b, c in zip(coords, coords[1:], coords[2:]):
        k = math.cos(math.radians(b[1]))
        u, v = ((b[0] - a[0]) * k, b[1] - a[1]), ((c[0] - b[0]) * k, c[1] - b[1])
        n = math.hypot(*u) * math.hypot(*v)
        if n:
            yield math.degrees(math.acos(max(-1, min(1, (u[0] * v[0] + u[1] * v[1]) / n))))


class DisplayGeometryTest(unittest.TestCase):
    def test_corner_keeps_branch_junction_after_rounding(self):
        for lat in (22, 48):
            with self.subTest(latitude=lat):
                raw = [(114, lat), (114.001, lat), (114.001, lat + .001), (114.002, lat + .001)]
                result = [(round(x, 6), round(y, 6)) for x, y in smooth(raw)]
                self.assertTrue(all(vertex in result for vertex in raw))
                self.assertEqual(Point(raw[1]).distance(LineString(result)), 0)
                self.assertLess(max(angles(result)), 55)

    def test_turnback_spike_does_not_survive(self):
        result = smooth([(114, 22), (114.002, 22), (114.001, 22), (114.003, 22)])
        self.assertEqual(result[0], (114, 22))
        self.assertEqual(result[-1], (114.003, 22))
        self.assertLess(max(angles(result), default=0), 55)

    def test_retained_junction_at_reversal_is_curved(self):
        raw = [(114, 22), (114.01, 22), (114.005, 22), (114.02, 22)]
        result = [(round(x, 6), round(y, 6)) for x, y in smooth(raw, reverse=181)]
        self.assertTrue(all(vertex in result for vertex in raw))
        self.assertLess(max(angles(result)), 55)

    def test_change_of_track_is_a_slant_and_stays_connected(self):
        parts = [LineString([(114, 22), (114.002, 22)]),
                 LineString([(114.002, 22.0001), (114.004, 22.0001)])]
        joined = stitch(parts)
        self.assertEqual(len(joined), 1)
        result = smooth(list(joined[0].coords))
        self.assertLess(max(angles(result)), 55)
        self.assertAlmostEqual(LineString(result).bounds[0], 114)
        self.assertAlmostEqual(LineString(result).bounds[2], 114.004)

    def test_gap_restores_only_existing_source_track(self):
        pieces = {"line": [LineString([(114, 22), (114.001, 22)]),
                           LineString([(114.003, 22), (114.004, 22)])]}
        source = [[(114, 22), (114.004, 22)]]
        self.assertEqual(bridge(pieces, source, joined=.00001, project_ends=True), 1)
        self.assertEqual(len(stitch(pieces["line"])), 1)

    def test_fine_samples_do_not_split_an_ordinary_curve(self):
        g = LineString([(114, 22), (114.001, 22), (114.002, 22.001)])
        self.assertEqual(len(unfold(g, step=.0001, fine=True)), 1)

    def test_real_circular_alignment_is_retained(self):
        co = [(114 + .01 * math.cos(i * 2 * math.pi / 100),
               22 + .01 * math.sin(i * 2 * math.pi / 100)) for i in range(101)]
        parts = unfold(LineString(co), step=.0001, fine=True)
        self.assertEqual(len(parts), 1)
        self.assertAlmostEqual(parts[0].length, LineString(co).length)

    def test_short_terminal_fold_is_detected(self):
        g = LineString([(114, 22), (114.003, 22), (114.00305, 22.00005),
                        (114.003, 22.0001), (114.0026, 22.0001)])
        self.assertGreater(len(unfold(g, step=.0001, fine=True)), 1)

    def test_station_length_doubleback_is_drawn_once(self):
        feature = {"properties": {"n": "test"}, "geometry": {"type": "LineString", "coordinates":
                   [(114, 22), (114.005, 22), (114.005, 22.0001), (114, 22.0001)]}}
        finish_metro([feature], [])
        g = feature["geometry"]
        parts = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
        self.assertLess(sum(LineString(p).length for p in parts), .006)


if __name__ == "__main__":
    unittest.main()
