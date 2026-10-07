"""Lines are moved to a side only where they are drawn along one path, and move over gradually."""
import sys
import unittest
from pathlib import Path

from shapely.geometry import LineString, Point, shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from side_by_side import GRAIN, side_by_side


def feature(name, colour, coords, **props):
    return {"type": "Feature", "properties": {"r": "00", "n": name, "col": colour, **props},
            "geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]}}


def pieces(features, name):
    """[(slot, LineString)] of one line, in the order the line is travelled from its first point."""
    out = []
    for f in features:
        if f["properties"]["n"] == name:
            g = shape(f["geometry"])
            out += [(f["properties"].get("off", 0), part) for part in (g.geoms if hasattr(g, "geoms") else [g])]
    return out


def slot_at(features, name, x, y):
    return min(pieces(features, name), key=lambda p: p[1].distance(Point(x, y)))[0]


# A runs west to east; B joins its path between x = 0.01 and x = 0.03 and leaves again
A = [(0, 0), (0.04, 0)]
B = [(0.005, 0.004), (0.01, 0), (0.03, 0), (0.035, 0.004)]


class SideBySideTest(unittest.TestCase):
    def test_a_line_alone_stays_on_its_track(self):
        out = side_by_side([feature("A", "#ff0000", A)])
        self.assertEqual(len(out), 1)
        self.assertNotIn("off", out[0]["properties"])

    def test_lines_are_apart_on_the_shared_path_and_on_their_track_elsewhere(self):
        out = side_by_side([feature("A", "#ff0000", A), feature("B", "#0000ff", B)])
        a, b = slot_at(out, "A", 0.02, 0), slot_at(out, "B", 0.02, 0)
        self.assertEqual(sorted((a, b)), [-0.5, 0.5])
        for name, x, y in (("A", 0.001, 0), ("A", 0.039, 0), ("B", 0.006, 0.0032), ("B", 0.034, 0.0032)):
            self.assertEqual(slot_at(out, name, x, y), 0, (name, x))

    def test_the_line_moves_over_in_small_steps_and_keeps_its_length(self):
        out = side_by_side([feature("A", "#ff0000", A), feature("B", "#0000ff", B)])
        for name, coords in (("A", A), ("B", B)):
            parts = pieces(out, name)
            self.assertAlmostEqual(sum(g.length for _, g in parts), LineString(coords).length, places=5)
            start = Point(coords[0])
            ordered = sorted(parts, key=lambda p: LineString(coords).project(p[1].interpolate(0.5, normalized=True)))
            self.assertEqual(ordered[0][1].distance(start), 0)
            for (s1, g1), (s2, g2) in zip(ordered, ordered[1:]):
                self.assertLess(g1.distance(g2), 1e-6)                  # no gap in the line
                self.assertLessEqual(abs(s1 - s2), GRAIN + 1e-9)        # no sideways jump

    def test_a_line_running_the_other_way_still_gets_its_own_side(self):
        out = side_by_side([feature("A", "#ff0000", A), feature("B", "#0000ff", B[::-1])])
        a, b = slot_at(out, "A", 0.02, 0), slot_at(out, "B", 0.02, 0)
        # the map shifts a line to the right of its own direction: opposite directions, same sign
        self.assertEqual(abs(a), 0.5)
        self.assertEqual(a, b)

    def test_a_crossing_line_is_not_company(self):
        out = side_by_side([feature("A", "#ff0000", A), feature("C", "#0000ff", [(0.02, -0.01), (0.02, 0.01)])])
        self.assertTrue(all("off" not in f["properties"] for f in out))

    def test_one_colour_is_one_line(self):
        out = side_by_side([feature("A", "#ff0000", A), feature("A east", "#ff0000", B)])
        self.assertTrue(all("off" not in f["properties"] for f in out))

    def test_three_lines_take_three_slots(self):
        out = side_by_side([feature("A", "#ff0000", A), feature("B", "#0000ff", B),
                            feature("C", "#00aa00", [(0.012, -0.004), (0.016, 0), (0.024, 0), (0.028, -0.004)])])
        self.assertEqual(sorted(slot_at(out, n, 0.02, 0) for n in "ABC"), [-1, 0, 1])

    def test_suburban_services_are_left_alone(self):
        feats = [feature("A", "#ff0000", A), feature("S", "#0000ff", A, k="s")]
        out = side_by_side(feats)
        self.assertTrue(all("off" not in f["properties"] for f in out))


if __name__ == "__main__":
    unittest.main()
