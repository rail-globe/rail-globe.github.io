"""Bends are drawn as curves: a line shows no angle at its vertices and does not leave the track."""
import math
import sys
import unittest
from pathlib import Path

from shapely.geometry import LineString, Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from single_track import curved

R, CENTRE = 0.06, (116.0, 40.0)          # an arc of about 7 km radius
K = math.cos(math.radians(40))


def on_arc(angle):
    return (CENTRE[0] + R * math.cos(math.radians(angle)) / K, CENTRE[1] + R * math.sin(math.radians(angle)))


def turns(co):
    for a, b, c in zip(co, co[1:], co[2:]):
        u, v = ((b[0] - a[0]) * K, b[1] - a[1]), ((c[0] - b[0]) * K, c[1] - b[1])
        n = math.hypot(*u) * math.hypot(*v)
        yield math.degrees(math.acos(max(-1, min(1, (u[0] * v[0] + u[1] * v[1]) / n)))) if n else 0


class CurvedTest(unittest.TestCase):
    def setUp(self):
        self.arc = [on_arc(a) for a in range(0, 71, 7)]               # chords turning 7 degrees each
        self.lead_in = (self.arc[0][0], self.arc[0][1] - 0.05)        # 5.5 km of straight, tangent to the arc
        self.line = [self.lead_in] + self.arc
        self.out = curved(self.line)

    def test_every_vertex_is_kept_so_nothing_attached_comes_loose(self):
        self.assertTrue(all(p in self.out for p in self.line))
        self.assertEqual(self.out[0], self.line[0])
        self.assertEqual(self.out[-1], self.line[-1])

    def test_the_angle_at_each_vertex_is_gone(self):
        self.assertAlmostEqual(max(turns(self.line)), 7.0, places=1)
        self.assertLess(max(turns(self.out)), 3.5)

    def test_the_curve_is_closer_to_the_true_arc_than_the_chords_were(self):
        # between vertices that have a neighbour on both sides; the last chord before the end of
        # a line has nothing beyond it to lean on and is only checked against the chords themselves
        start, last = self.out.index(self.arc[0]), self.out.index(self.arc[-2])
        off = [abs(math.hypot((x - CENTRE[0]) * K, y - CENTRE[1]) - R) for x, y in self.out[start:]]
        chords = R * (1 - math.cos(math.radians(3.5)))
        self.assertLess(max(off[:last - start + 1]), chords / 2)
        self.assertLess(max(off), chords)

    def test_a_long_straight_beside_a_curve_stays_straight(self):
        straight = LineString([(self.lead_in[0] * K, self.lead_in[1]), (self.arc[0][0] * K, self.arc[0][1])])
        start = self.out.index(self.arc[0])
        off = max(straight.distance(Point(x * K, y)) for x, y in self.out[:start + 1])
        self.assertLess(off * 111000, 5)                              # metres

    def test_the_curve_stays_within_the_tolerance_the_line_was_simplified_with(self):
        # three stretches of a kilometre, turning 20 degrees left and then 20 degrees right: left
        # alone, the curve swings well away from the straight line between two vertices
        step = 0.01
        bend = (step * math.cos(math.radians(20)), step * math.sin(math.radians(20)))
        line = [(116.0, 40.0), (116.0 + step / K, 40.0), (116.0 + (step + bend[0]) / K, 40.0 + bend[1]),
                (116.0 + (2 * step + bend[0]) / K, 40.0 + bend[1])]
        chord = LineString([(line[1][0] * K, line[1][1]), (line[2][0] * K, line[2][1])])

        def widest(out):
            return max(chord.distance(Point(x * K, y)) for x, y in out[out.index(line[1]):out.index(line[2]) + 1])
        tolerance = 0.00005
        self.assertGreater(widest(curved(line, 3, 8, 0.00005)), 2 * tolerance)
        self.assertLessEqual(widest(curved(line, 3, 8, 0.00005, within=tolerance)), tolerance + 1e-9)

    def test_a_straight_line_gets_no_points(self):
        self.assertEqual(curved([(0, 0), (1, 0), (2, 0)]), [(0, 0), (1, 0), (2, 0)])

    def test_a_real_corner_is_left_alone(self):
        self.assertEqual(curved([(0, 0), (1, 0), (1, 1)]), [(0, 0), (1, 0), (1, 1)])


if __name__ == "__main__":
    unittest.main()
