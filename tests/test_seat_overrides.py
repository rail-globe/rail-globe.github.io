import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import seat_overrides as S

LAT = 40.0
DEG = 1 / S.M                           # a metre of latitude, in degrees
EAST = DEG / 0.7660444431189780         # a metre of longitude at LAT


def at(x, y):
    """x metres east and y metres north of a corner."""
    return [116.0 + x * EAST, LAT + y * DEG]


def track(x, y_from=0, y_to=10000, step=500):
    """A track running north, x metres east of the corner."""
    return [at(x, y) for y in range(y_from, y_to + (1 if y_to > y_from else -1), step if y_to > y_from else -step)]


def line(name, coords, **props):
    return {"type": "Feature", "properties": {"n": name, **props}, "geometry": {"type": "LineString", "coordinates": coords}}


def listed(seats, **more):
    row = {"name": "走廊", "country": "cn", "spine": "主线", "from": at(0, 0), "to": at(0, 10000), "reach_m": 100, "ramp_m": 600,
           "seats": seats, "why": "测试", "asked": "测试", **more}
    path = Path(tempfile.mkdtemp()) / "seats.json"
    path.write_text(json.dumps({"corridors": [row]}, ensure_ascii=False), encoding="utf-8")
    return path


SPINE = line("主线", track(0), c="hsr350")


def seats_along(features, name):
    """[(metres north, seat)] of the pieces of a line, in order."""
    rows = []
    for f in features:
        if f["properties"]["n"] != name:
            continue
        g = f["geometry"]
        for co in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]):
            rows.append((round((co[0][1] - LAT) / DEG), round((co[-1][1] - LAT) / DEG), f["properties"].get("off")))
    return sorted(rows, key=lambda r: min(r[0], r[1]))


def seat_at(features, name, north):
    """The seat of a line where it is `north` metres north of the corner (None: none)."""
    for a, b, seat in seats_along(features, name):
        if min(a, b) <= north <= max(a, b):
            return seat
    raise AssertionError(f"{name} is not drawn at {north}")


class Seats(unittest.TestCase):
    def apply(self, features, seats, urban=False, **more):
        corridors = S.corridors("cn", [SPINE] + features, listed(seats, **more))
        return S.apply(features, corridors, urban=urban)

    def test_a_line_takes_its_seat_between_the_places_listed(self):
        other = line("旁线", track(-20), c="main")
        out, receipt = self.apply([other], {"旁线": [{"at": at(0, 2000), "seat": -1}, {"at": at(0, 8000), "seat": None}]})
        self.assertEqual([seat_at(out, "旁线", y) for y in (1000, 2400, 5000, 7600, 9000)], [None, -1, -1, -1, None])
        # it comes to its seat on the way in and gives it up on the way out, a step in 600 m
        self.assertTrue(-0.5 < seat_at(out, "旁线", 1600) < 0)
        self.assertTrue(-0.5 < seat_at(out, "旁线", 8400) < 0)
        self.assertEqual({row["line"] for row in receipt}, {"旁线"})

    def test_a_change_of_seat_is_made_in_eighths(self):
        other = line("旁线", track(-20), c="main")
        out, _ = self.apply([other], {"旁线": [{"at": at(0, 2000), "seat": -1}]})
        steps = [seat for a, b, seat in seats_along(out, "旁线") if seat is not None]
        self.assertTrue(all(abs(seat * 8 - round(seat * 8)) < 1e-9 for seat in steps))
        self.assertTrue(all(abs(a - b) <= 0.125 + 1e-9 for a, b in zip(steps, steps[1:])))

    def test_a_line_written_against_the_spine_is_seated_on_the_same_side(self):
        north = line("旁线", track(-20), c="main")
        south = line("旁线", track(-20)[::-1], c="main")
        seats = {"旁线": [{"at": at(0, 2000), "seat": -1}]}
        a = {seat for _, _, seat in seats_along(self.apply([north], seats)[0], "旁线") if seat is not None and abs(seat) == 1}
        b = {seat for _, _, seat in seats_along(self.apply([south], seats)[0], "旁线") if seat is not None and abs(seat) == 1}
        self.assertEqual((a, b), ({-1}, {1}))            # to the left of the spine either way

    def test_a_line_not_named_and_the_spine_are_left_as_they_are(self):
        other, third = line("旁线", track(-20), c="main"), line("别的线", track(30), c="main")
        out, _ = self.apply([SPINE, other, third], {"旁线": [{"at": at(0, 2000), "seat": -1}]})
        self.assertIn(SPINE, out)
        self.assertIn(third, out)

    def test_a_line_that_leaves_sideways_keeps_its_seat_in_the_corridor_and_fades_out_of_it(self):
        leaving = line("旁线", track(-20, 0, 5000) + [at(-600, 5600), at(-3000, 8000)], c="main")
        out, _ = self.apply([leaving], {"旁线": [{"at": at(0, 1000), "seat": -2}]})
        rows = [(min(a, b), seat or 0) for a, b, seat in seats_along(out, "旁线")]
        steps = [seat for _, seat in rows]
        self.assertEqual(seat_at(out, "旁线", 4500), -2)                  # in full while it runs along the spine
        self.assertTrue(all(abs(a - b) <= 0.125 + 1e-9 for a, b in zip(steps, steps[1:])), steps)
        self.assertEqual(steps[-1], 0)

    def test_a_seat_fades_on_into_the_piece_of_the_line_that_follows(self):
        first = line("旁线", track(-20, 0, 5000), c="main")
        then = line("旁线", [at(-20, 5000), at(-1500, 6500), at(-4000, 9000)], c="main")
        out, _ = self.apply([first, then], {"旁线": [{"at": at(0, 1000), "seat": -1}]})
        tail = [f["properties"].get("off") for f in out if f["geometry"]["coordinates"][0][1] > LAT + 5000 * DEG - 1e-9
                or (f["geometry"]["type"] == "MultiLineString")]
        moved = [f for f in out if f["properties"].get("off") and min(p[0] for p in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "LineString" else f["geometry"]["coordinates"][0])) < 116.0 - 100 * EAST]
        self.assertTrue(moved)                                           # the second piece starts with what the first ends with

    def test_a_line_that_only_crosses_is_not_seated(self):
        crossing = line("旁线", [at(-3000, 5000), at(3000, 5000)], c="main")
        out, receipt = self.apply([crossing], {"旁线": [{"at": at(0, 1000), "seat": -1}]})
        self.assertEqual(out, [crossing])
        self.assertEqual(receipt, [])

    def test_an_urban_line_carries_the_move_as_goff(self):
        pair = line("地铁", track(-30), r="11", jk="subway", off=0.5)
        out, _ = self.apply([pair], {"地铁": [{"at": at(0, 1000), "seat": -2}]}, urban=True)
        full = [f["properties"] for f in out if f["properties"].get("off") == -2]
        self.assertTrue(full)
        self.assertEqual(full[0]["goff"], -2.5)          # what the page takes off again when zoomed in: back to 0.5

    def test_a_suburban_service_starts_from_the_step_it_is_drawn_at(self):
        guest = line("市郊", track(0), r="11", k="s", jk="suburban")
        out, _ = self.apply([guest], {"市郊": [{"at": at(0, 2000), "seat": 2}]}, urban=True)
        steps = [seat for _, _, seat in seats_along(out, "市郊") if seat is not None]
        self.assertEqual(max(steps), 2)
        self.assertGreater(min(steps), 1)                # from one step, not from none
        self.assertTrue(all("goff" not in f["properties"] for f in out))

    def test_a_line_joining_from_another_corridor_comes_with_its_seat(self):
        corridor = S.corridors("cn", [SPINE], listed({"旁线": [{"at": at(0, 2000), "seat": -2, "before": -1}]}))[0]
        self.assertEqual(corridor.seat("旁线", 1500), (0.0, 0.0))             # before the join the other corridor seats it
        seat, share = corridor.seat("旁线", 1760)
        self.assertEqual(share, 1.0)                                          # it comes in at one step, not from none
        self.assertAlmostEqual(seat, -1.1, places=1)
        self.assertEqual(corridor.seat("旁线", 2500), (-2, 1.0))

    def test_a_corridor_must_say_who_asked_and_why(self):
        with self.assertRaises(ValueError):
            S.corridors("cn", [SPINE], listed({"旁线": [{"at": at(0, 2000), "seat": -1}]}, why=""))

    def test_a_spine_that_is_not_on_the_map_is_an_error(self):
        with self.assertRaises(ValueError):
            S.corridors("cn", [line("别的线", track(0))], listed({"旁线": [{"at": at(0, 2000), "seat": -1}]}))


class TheList(unittest.TestCase):
    def test_every_corridor_listed_names_lines_and_places(self):
        rows = json.loads(S.FILE.read_text(encoding="utf-8"))["corridors"]
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row["why"] and row["asked"], row["name"])
            for name, steps in row["seats"].items():
                self.assertTrue(steps and all(len(step["at"]) == 2 for step in steps), (row["name"], name))


if __name__ == "__main__":
    unittest.main()
