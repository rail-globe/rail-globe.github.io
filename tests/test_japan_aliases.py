import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from process_jp import adopt_aliases


def track(x_from, x_to, kind="subway"):
    return ({"railway": kind}, [(float(x_from), 0.0), (float(x_to), 0.0)])


class Aliases(unittest.TestCase):
    """One urban line whose track carries several names (横浜's blue line, 2026-10-13)."""

    def setUp(self):
        # 3号線 0..10, then two ways under other names 10..11..12, then 3号線 again 12..20
        self.ways = {1: track(0, 10), 2: track(10, 11), 3: track(11, 12), 4: track(12, 20), 5: track(30, 31)}
        self.line_of = {1: ("metro", None, "3号線"), 2: ("metro", None, "ブルーライン"), 3: ("metro", None, "地下鉄ブルーライン"),
                        4: ("metro", None, "3号線"), 5: ("metro", None, "園内線")}
        self.length = {1: 10.0, 2: 1.0, 3: 1.0, 4: 8.0, 5: 1.0}
        self.blue = [(7, {"route": "subway"}, [("w", 1), ("w", 2), ("w", 3), ("w", 4)])]

    def test_a_stretch_under_other_names_joins_the_line_on_both_sides(self):
        moved = adopt_aliases(self.line_of, self.ways, self.blue, self.length, 4.0)
        self.assertEqual({self.line_of[w][2] for w in (1, 2, 3, 4)}, {"3号線"})
        self.assertEqual(dict(moved), {("ブルーライン", "3号線"): 1.0, ("地下鉄ブルーライン", "3号線"): 1.0})

    def test_a_short_line_that_meets_no_longer_line_keeps_its_name(self):
        adopt_aliases(self.line_of, self.ways, self.blue, self.length, 4.0)
        self.assertEqual(self.line_of[5][2], "園内線")

    def test_no_route_over_both_means_two_lines(self):
        apart = [(7, {"route": "subway"}, [("w", 1), ("w", 4)]), (8, {"route": "subway"}, [("w", 2), ("w", 3)])]
        self.assertFalse(adopt_aliases(self.line_of, self.ways, apart, self.length, 4.0))
        self.assertEqual(self.line_of[2][2], "ブルーライン")

    def test_a_name_with_enough_track_is_a_line_of_its_own(self):
        self.length[2] = self.length[3] = 5.0
        self.assertFalse(adopt_aliases(self.line_of, self.ways, self.blue, self.length, 4.0))

    def test_tram_track_is_left_to_the_tramways(self):
        self.ways[2] = track(10, 11, "tram")
        self.ways[3] = track(11, 12, "tram")
        self.assertFalse(adopt_aliases(self.line_of, self.ways, self.blue, self.length, 4.0))

    def test_the_result_does_not_depend_on_the_order_of_the_ways(self):
        again = dict(reversed(list(self.line_of.items())))
        adopt_aliases(self.line_of, self.ways, self.blue, self.length, 4.0)
        adopt_aliases(again, self.ways, self.blue, self.length, 4.0)
        self.assertEqual(self.line_of, again)


if __name__ == "__main__":
    unittest.main()
