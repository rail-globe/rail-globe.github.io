import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from shapely.geometry import LineString

from single_track import closed, stitch

M = 1 / 111320.0          # a metre in degrees, near the equator


def ring_cut(step_m, along_m=0.0, radius_m=2000.0, points=400):
    """A circle of track cut open at its easternmost point: it starts there, and its other end
    stops step_m to the side (further out) and along_m short of the start."""
    ring = [(radius_m * math.cos(a) * M, radius_m * math.sin(a) * M) for a in (2 * math.pi * i / points for i in range(points))]
    short = int(along_m / (2 * math.pi * radius_m / points))
    ring = ring[:points - short]
    return ring + [((radius_m + step_m) * M, -along_m * M)]


def turns(co):
    out = []
    for a, b, c in zip(co, co[1:], co[2:]):
        v, w = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
        n = math.hypot(*v) * math.hypot(*w)
        if n:
            out.append(math.degrees(math.acos(max(-1.0, min(1.0, (v[0] * w[0] + v[1] * w[1]) / n)))))
    return out


class Closed(unittest.TestCase):
    """A circle line put together from its own track and a path it shares was left open at one join
    (重庆轨道交通环线 west of 民安大道, 55 m, 2026-10-13)."""

    def test_a_ring_cut_with_its_ends_abreast_is_closed_by_a_slant(self):
        chain = ring_cut(step_m=50, along_m=17)
        out = closed(chain, 130 * M, 6 * M, bends=True)
        self.assertEqual(out[0], out[-1])
        self.assertTrue(LineString(out).is_ring)
        self.assertLess(max(turns(out + out[1:2])), 40)          # no bar across from one track to the other
        self.assertGreater(LineString(out).length, 0.95 * LineString(chain).length)

    def test_ends_further_apart_than_the_gap_stay_open(self):
        chain = ring_cut(step_m=300)
        self.assertEqual(closed(chain, 130 * M), chain)

    def test_a_short_run_is_no_ring(self):
        hook = [(0, 0), (300 * M, 0), (300 * M, 60 * M), (0, 60 * M), (0, 40 * M)]
        self.assertEqual(closed(hook, 130 * M), hook)

    def test_a_ring_already_closed_is_left_alone(self):
        chain = ring_cut(step_m=0)
        chain[-1] = chain[0]
        self.assertEqual(closed(chain, 130 * M), chain)


class Stitched(unittest.TestCase):
    def pieces(self):
        chain = ring_cut(step_m=50, along_m=17)
        return [LineString(chain[:150]), LineString(chain[149:300]), LineString(chain[299:])]

    def test_stitch_closes_a_ring_only_when_asked(self):
        left_open = stitch(self.pieces(), bends=True)
        self.assertEqual(len(left_open), 1)
        self.assertFalse(left_open[0].is_ring)                   # a railway line is never taken for a ring
        ring = stitch(self.pieces(), bends=True, close=130 * M)
        self.assertEqual(len(ring), 1)
        self.assertTrue(ring[0].is_ring)

    def test_one_piece_that_is_a_cut_ring_is_closed_too(self):
        ring = stitch([LineString(ring_cut(step_m=50, along_m=17))], bends=True, close=130 * M)
        self.assertTrue(ring[0].is_ring)


class SlotAtTheSeam(unittest.TestCase):
    """Where a ring begins there is no stretch before it, so a change of slot there had no ramp."""

    def features(self):
        ring = [(3000 * math.cos(a) * M, 3000 * math.sin(a) * M) for a in (2 * math.pi * i / 600 for i in range(600))]
        ring.append(ring[0])
        feature = lambda name, colour, co: {"type": "Feature", "properties": {"r": "X", "n": name, "col": colour},
                                            "geometry": {"type": "LineString", "coordinates": co}}
        return [feature("ring", "#ff0000", ring), feature("other", "#00ff00", ring[:150])]      # company from the ring's very start

    def step(self, out):
        ends, worst = {}, 0.0
        for f in out:
            if f["properties"]["n"] != "ring":
                continue
            g = f["geometry"]
            for co in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]):
                for c in (co[0], co[-1]):
                    k, off = (round(c[0], 6), round(c[1], 6)), f["properties"].get("off", 0)
                    worst = max(worst, abs(ends.get(k, off) - off))
                    ends[k] = off
        return worst

    def test_a_ring_is_written_from_the_middle_of_its_longest_stretch(self):
        from side_by_side import GRAIN, side_by_side
        self.assertGreater(self.step(side_by_side(self.features())), GRAIN)          # as it was: a step to the side at the seam
        self.assertLessEqual(self.step(side_by_side(self.features(), rings=True)), GRAIN)


if __name__ == "__main__":
    unittest.main()
