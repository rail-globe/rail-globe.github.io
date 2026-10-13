import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import yards as Y

M = 1 / 111320.0          # a metre, in degrees of latitude
X0, Y0 = 120.0, 0.0       # on the equator, where a degree of longitude is as long


def at(x, y):
    return [X0 + x * M, Y0 + y * M]


def track(y, x_from=0, x_to=3000, step=50):
    """A track running east, y metres north."""
    return [at(x, y) for x in range(x_from, x_to + 1, step)]


LINE = track(0)


class OffTheLine(unittest.TestCase):
    def test_a_crossover_between_two_lines_is_not_drawn(self):
        other = track(12)
        crossover = [at(1000, 0), at(1100, 12)]
        self.assertEqual(Y.off_the_line([crossover], [LINE, other]), [False])

    def test_a_passing_loop_beside_the_line_is_not_drawn(self):
        loop = [at(800, 0), at(900, 6)] + track(6, 950, 1800) + [at(1900, 0)]
        self.assertEqual(Y.off_the_line([loop], [LINE]), [False])

    def test_the_tracks_of_a_station_are_drawn_whole(self):
        ladder = [at(800, 0), at(1000, 40)]                     # the tracks branch off one another
        near, far = track(8, 850, 1800), track(40, 1000, 1800)
        near[0] = at(840, 8)                                    # leaves the ladder
        self.assertEqual(Y.off_the_line([ladder, near, far], [LINE]), [True, True, True])

    def test_a_loop_is_judged_apart_from_a_yard_it_does_not_touch(self):
        loop = [at(100, 0), at(150, 6), at(400, 6), at(450, 0)]
        yard = [at(2000, 0), at(2200, 60), at(2800, 60)]
        self.assertEqual(Y.off_the_line([loop, yard], [LINE]), [False, True])

    def test_a_degree_of_longitude_is_measured_as_it_is_long(self):
        lat = 60.0                                              # half as long as on the equator
        north = lambda x, y: [X0 + x * M / 0.5, lat + y * M]
        line = [north(0, y) for y in range(0, 3001, 50)]        # running north
        beside = [north(20, y) for y in range(500, 1501, 50)]   # 20 m east of it
        apart = [north(40, y) for y in range(500, 1501, 50)]    # 40 m east of it
        self.assertEqual(Y.off_the_line([beside, apart], [line]), [False, True])

    def test_a_named_yard_along_its_line_keeps_its_tracks(self):
        loop = [at(800, 0), at(900, 6)] + track(6, 950, 1800) + [at(1900, 0)]
        other = [at(2300, 0), at(2400, 6), at(2800, 6), at(2900, 0)]
        self.assertEqual(Y.off_the_line([loop, other], [LINE], named_at=[tuple(at(1300, 40))]), [True, False])

    def test_nothing_drawn_leaves_the_yard_track_as_it_is(self):
        self.assertEqual(Y.off_the_line([track(5)], []), [True])


if __name__ == "__main__":
    unittest.main()
