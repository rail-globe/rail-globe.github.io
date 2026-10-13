import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import station_links as sl

M = 1 / 111320.0          # a metre, in degrees of latitude
X0, Y0 = 120.0, 0.0       # on the equator, where a degree of longitude is as long


def line(y_m, x_from=-3000, x_to=3000, step=100):
    """A track running east-west, y_m metres north of the station."""
    return [(X0 + x * M, Y0 + y_m * M) for x in range(x_from, x_to + 1, step)]


def siding(y_m, at=0):
    """A short track that leaves the line at `at` metres east: a turnout there."""
    return [(X0 + at * M, Y0 + y_m * M), (X0 + (at + 100) * M, Y0 + (y_m + 5) * M), (X0 + (at + 300) * M, Y0 + (y_m + 5) * M)]


OLD = ("main", "old line", line(0))


class Passing(unittest.TestCase):
    def passed(self, stations, ways, extra=(), timetable=()):
        turn = sl.turnouts([co for _, _, co in ways] + list(extra))
        return sl.passing(stations, ways, turn, timetable)

    def test_a_fast_line_on_plain_track_beside_the_station_runs_past(self):
        skip, rows = self.passed([("新市", X0, Y0)], [OLD, ("hsr350", "fast line", line(250))])
        self.assertEqual(skip, {0: {"fast line"}})
        self.assertEqual(rows[0]["passes"], "no turnout by the station")

    def test_a_fast_line_with_station_tracks_stops(self):
        skip, _ = self.passed([("两场", X0, Y0)], [OLD, ("hsr350", "fast line", line(250))], extra=[siding(250)])
        self.assertEqual(skip, {})

    def test_the_station_on_the_fast_line_takes_it_from_the_one_beside(self):
        stations = [("六家", X0, Y0), ("高鐵新竹", X0 + 100 * M, Y0 + 150 * M)]
        skip, rows = self.passed(stations, [OLD, ("hsr350", "fast line", line(150))], extra=[siding(150)])
        self.assertEqual(skip, {0: {"fast line"}})
        self.assertIn("高鐵新竹 is nearer", rows[0]["passes"])

    def test_a_dot_on_the_fast_line_is_its_station_without_any_turnout(self):
        skip, _ = self.passed([("乘降所", X0, Y0)], [OLD, ("hsr350", "fast line", line(40))])
        self.assertEqual(skip, {})

    def test_a_conventional_line_is_never_judged(self):
        skip, _ = self.passed([("站", X0, Y0)], [OLD, ("main", "freight line", line(300))])
        self.assertEqual(skip, {})

    def test_the_last_line_stays(self):
        skip, _ = self.passed([("孤站", X0, Y0)], [("hsr350", "fast line", line(300))])
        self.assertEqual(skip, {})

    def test_no_fast_train_stops_by_the_timetable(self):
        ways = [OLD, ("hsr350", "passenger line", line(30)), ("hsr200", "mixed line", line(-30))]
        skip, rows = self.passed([("大庆", X0, Y0)], ways, timetable=[("大庆", X0, Y0, False)])
        self.assertEqual(skip, {0: {"passenger line"}})          # trains of every kind run on the mixed line
        self.assertEqual(rows[0]["passes"], "no fast train stops here by the timetable")

    def test_track_and_timetable_disagreeing_leaves_the_station_as_it_was(self):
        ways = [OLD, ("hsr350", "fast line", line(250))]
        skip, rows = self.passed([("咸阳", X0, Y0)], ways, timetable=[("咸阳", X0, Y0, True)])
        self.assertEqual(skip, {})
        self.assertIn("kept", rows[0])

    def test_a_station_looked_up_loses_its_fast_lines_whatever_the_timetable_says(self):
        ways = [OLD, ("hsr350", "fast line", line(250))]
        turn = sl.turnouts([co for _, _, co in ways])
        skip, rows = sl.passing([("咸阳", X0, Y0)], ways, turn, [("咸阳", X0, Y0, True)], listed=[("咸阳", X0, Y0)])
        self.assertEqual(skip, {0: {"fast line"}})
        self.assertEqual(rows[0]["passes"], "looked up: no fast line stops here")

    def test_a_listed_station_that_is_not_on_the_map_is_an_error(self):
        with self.assertRaises(ValueError):
            sl.passing([("咸阳", X0, Y0)], [OLD], set(), listed=[("咸阳西", X0, Y0)])

    def test_a_timetable_stop_of_the_same_name_far_away_is_another_station(self):
        ways = [OLD, ("hsr350", "passenger line", line(30))]
        skip, _ = self.passed([("新市", X0, Y0)], ways, timetable=[("新市", X0 + 1.0, Y0, False)])
        self.assertEqual(skip, {})


class Turnouts(unittest.TestCase):
    def test_two_pieces_of_one_track_meeting_end_to_end_are_no_turnout(self):
        a, b = line(0, -1000, 0), line(0, 0, 1000)
        self.assertEqual(sl.turnouts([a, b]), set())

    def test_a_track_leaving_inside_another_is_a_turnout(self):
        self.assertEqual(sl.turnouts([line(0), siding(0)]), {sl.pack((X0, Y0))})


class FastStops(unittest.TestCase):
    def test_kinds_of_train_per_stop(self):
        index = {"stops": [{"name": "甲", "lon": 1, "lat": 2}, {"name": "乙", "lon": 3, "lat": 4}, {"name": "丙", "lon": 5, "lat": 6}],
                 "trips": [{"type": "G", "stops": [[0, 0, 0, None]]}, {"type": "K", "stops": [[0, 0, 0, None], [1, 0, 0, None]]}]}
        self.assertEqual(sl.fast_stops(index), [("甲", 1, 2, True), ("乙", 3, 4, False)])


if __name__ == "__main__":
    unittest.main()
