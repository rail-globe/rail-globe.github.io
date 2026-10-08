"""A line follows its own curve through a junction: where it comes onto another line's path and
where it leaves it are found to a few metres, and its own track is brought over to meet the path."""
import math
import sys
import unittest
from pathlib import Path

from shapely.geometry import LineString, Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from along import FINE, TRACK, beside, exactly, meeting, settled
from metro_fit import fit
from single_track import eased

M = 0.00001          # about a metre


def turning_off(at=0.002, radius=0.00025, sweep=90, side=1):
    """A line along the x axis that turns off it at x = `at` on a curve of `radius` (about 25 m)."""
    co = [(0.0, 0.0), (at, 0.0)]
    for a in range(5, sweep + 1, 5):
        r = math.radians(a)
        co.append((at + radius * math.sin(r), side * radius * (1 - math.cos(r))))
    last = co[-1]
    r = math.radians(sweep)
    co.append((last[0] + 0.002 * math.cos(r), last[1] + side * 0.002 * math.sin(r)))
    return LineString(co)


STRAIGHT = LineString([(0.0, 0.0), (0.006, 0.0)])


class AlongTest(unittest.TestCase):
    def test_beside_is_near_and_going_the_same_way(self):
        other_track = LineString([(0.0, 5 * M), (0.006, 5 * M)])
        self.assertTrue(beside(other_track, 0.003, STRAIGHT, TRACK))
        crossing = LineString([(0.003, -0.001), (0.003, 0.001)])
        self.assertFalse(beside(crossing, 0.001, STRAIGHT, TRACK))
        street_away = LineString([(0.0, 40 * M), (0.006, 40 * M)])
        self.assertFalse(beside(street_away, 0.003, STRAIGHT, TRACK))

    def test_a_line_is_not_beside_a_path_it_has_gone_on_past(self):
        short = LineString([(0.0, 0.0), (0.002, 0.0)])
        self.assertTrue(beside(STRAIGHT, 0.0019, short, TRACK))
        self.assertFalse(beside(STRAIGHT, 0.0021, short, TRACK))

    def test_the_place_a_line_turns_off_is_found_to_a_few_metres(self):
        line = turning_off(at=0.002)
        # the samples had the line on the path as far as 0.0016 and missed where it leaves
        lo, hi = exactly(line, STRAIGHT, 0.0004, 0.0016, TRACK, 0.0, line.length)
        self.assertAlmostEqual(lo, 0.0, delta=FINE)
        self.assertGreater(hi, 0.002 - FINE)
        lo, hi = settled(line, STRAIGHT, lo, hi)
        self.assertAlmostEqual(hi, 0.002, delta=4 * FINE)                # about 20 m
        self.assertLess(STRAIGHT.distance(line.interpolate(hi)), 2 * M)  # still on the path there

    def test_samples_beyond_the_turn_are_drawn_back(self):
        line = turning_off(at=0.002)
        lo, hi = exactly(line, STRAIGHT, 0.0004, 0.0026, TRACK, 0.0, line.length)   # 0.0026 is round the bend
        self.assertLess(hi, 0.0023)

    def test_a_line_that_is_nowhere_beside_the_path_has_no_stretch(self):
        crossing = LineString([(0.003, -0.001), (0.003, 0.001)])
        self.assertIsNone(exactly(crossing, STRAIGHT, 0.0008, 0.0012, TRACK, 0.0, crossing.length))

    def test_the_second_track_counts_as_the_path_until_it_leaves(self):
        # the line runs on the track 5 m beside the path, then turns away from it
        line = LineString([(x, y + 5 * M) for x, y in turning_off(at=0.002).coords])
        lo, hi = settled(line, STRAIGHT, *exactly(line, STRAIGHT, 0.0004, 0.0016, TRACK, 0.0, line.length))
        self.assertAlmostEqual(hi, 0.002, delta=4 * FINE)

    def test_own_track_is_brought_over_to_meet_the_paths_at_its_ends(self):
        before = LineString([(-0.003, 0.0), (0.0, 0.0)])
        curve = LineString([(x, y + 5 * M) for x, y in turning_off(at=0.0002).coords])       # starts 5 m to the side
        met = meeting(curve, before, None)
        self.assertLess(Point(met.coords[0]).distance(Point(0.0, 0.0)), 0.2 * M)             # starts on the path
        self.assertEqual(met.coords[-1], curve.coords[-1])                                   # the far end stays
        self.assertLess(max(curve.distance(Point(c)) for c in met.coords), 5.1 * M)          # never further than the step
        self.assertLess(curve.distance(Point(met.interpolate(0.0006).coords[0])), 0.2 * M)   # and back on its track within 60 m

    def test_own_track_already_on_the_path_is_left_alone(self):
        before = LineString([(-0.003, 0.0), (0.0, 0.0)])
        curve = turning_off(at=0.0002)
        self.assertEqual(list(meeting(curve, before, None).coords), list(curve.coords))


class EasedTest(unittest.TestCase):
    def test_parallel_ends_abreast_are_joined_at_a_slant(self):
        a = [(0.0, 0.0), (0.004, 0.0)]
        b = [(0.004, 10 * M), (0.008, 10 * M)]
        left, right = eased(a, b)
        self.assertLess(left[-1][0], 0.004)
        self.assertGreater(right[0][0], 0.004)

    def test_the_legs_of_a_junction_are_not_cut_back(self):
        a = [(0.0, 0.0), (0.004, 0.0)]
        b = [(0.004, 10 * M), (0.004, 0.004)]          # turns off at a right angle
        self.assertEqual(eased(a, b, bends=True), (a, b))
        self.assertNotEqual(eased(a, b), (a, b))       # the railway layers keep the cut-back join

    def test_a_step_narrower_than_asked_is_left(self):
        a = [(0.0, 0.0), (0.004, 0.0)]
        b = [(0.004, 4 * M), (0.008, 4 * M)]
        self.assertEqual(eased(a, b), (a, b))
        left, _ = eased(a, b, least=2 * M)
        self.assertLess(left[-1][0], 0.004)


def feature(name, coords, region="81"):
    return {"type": "Feature", "properties": {"r": region, "n": name}, "geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]}}


class FitTest(unittest.TestCase):
    KEY = ("81", "A")
    TRACK_CO = [(0.0, 0.0), (0.01, 0.0), (0.01, 0.01)]         # a line with a corner

    def test_a_line_drawn_on_its_track_fits(self):
        report = fit([feature("A", self.TRACK_CO)], {self.KEY: [self.TRACK_CO]}, {self.KEY: [LineString(self.TRACK_CO)]}, light={self.KEY})
        self.assertEqual(report, {"astray": [], "undrawn": []})

    def test_a_corner_cut_across_is_drawn_away_from_the_track(self):
        cut = [(0.0, 0.0), (0.007, 0.0), (0.01, 0.003), (0.01, 0.01)]
        report = fit([feature("A", cut)], {self.KEY: [self.TRACK_CO]}, {self.KEY: [LineString(self.TRACK_CO)]}, light={self.KEY})
        self.assertEqual(len(report["astray"]), 1)
        self.assertEqual(report["astray"][0]["line"], "A")

    def test_a_line_that_stops_short_leaves_track_undrawn(self):
        short = [(0.0, 0.0), (0.01, 0.0), (0.01, 0.007)]       # 300 m short of the terminus
        report = fit([feature("A", short)], {self.KEY: [self.TRACK_CO]}, {self.KEY: [LineString(self.TRACK_CO)]}, light={self.KEY})
        self.assertEqual(report["astray"], [])
        self.assertEqual(len(report["undrawn"]), 1)

    def test_a_railway_scale_line_may_lie_a_corridor_away(self):
        beside = [(0.0, 0.0005), (0.01, 0.0005), (0.0105, 0.01)]         # 55 m to the side
        report = fit([feature("A", beside)], {self.KEY: [self.TRACK_CO]}, {self.KEY: [LineString(self.TRACK_CO)]})
        self.assertEqual(report, {"astray": [], "undrawn": []})


if __name__ == "__main__":
    unittest.main()
