"""single_track.one_copy: a city line drawn out on one track of a double track and back on the other
is kept once (Budapest 59B, Vienna 27, Bremen 1: 2026-10-22)."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from shapely.geometry import LineString, Point

from single_track import folds, one_copy

LAT = 47.5
K = math.cos(math.radians(LAT)) * 111320.0


def run(metres):
    """a run given in metres east and north of a point at LAT"""
    return LineString([(19.0 + x / K, LAT + y / 111320.0) for x, y in metres])


class OneCopyTest(unittest.TestCase):
    def test_out_and_back_is_kept_once_with_its_turning_loop(self):
        # out 2 km on the upper track, round a loop of radius 20 m, back 2 km on the lower track 4 m away
        out = [(float(x), 4.0) for x in range(0, 2001, 50)]
        turn = [(2000 + 20 * math.sin(a), 22 - 18 * math.cos(a)) for a in (2 * math.pi * k / 40 for k in range(1, 40))]
        back = [(float(x), 0.0) for x in range(2000, -1, -50)]
        g = run(out + turn + back)
        self.assertTrue(folds(g))
        kept = one_copy([g])
        self.assertEqual(len(kept), 1)
        self.assertLess(kept[0].length, 0.6 * g.length)          # one copy and the loop, not two copies
        top = Point(19.0 + 2000 / K, LAT + 40 / 111320.0)
        self.assertLess(kept[0].distance(top), 3 / 111320)        # the loop is still drawn

    def test_a_line_without_a_doubled_stretch_comes_back_unchanged(self):
        pieces = [run([(float(x), 0.0) for x in range(0, 3001, 100)]), run([(0.0, 50.0), (0.0, 2000.0)])]
        self.assertIs(one_copy(pieces), pieces)

    def test_two_streets_apart_are_kept(self):
        # a one-way pair 30 m apart: two streets, not the two tracks of one
        out = [(float(x), 30.0) for x in range(0, 2001, 50)]
        back = [(float(x), 0.0) for x in range(2000, -1, -50)]
        pieces = [run(out + [(2010.0, 15.0)] + back)]
        self.assertIs(one_copy(pieces), pieces)


if __name__ == "__main__":
    unittest.main()
