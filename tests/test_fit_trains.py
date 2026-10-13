import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fit_trains as F
from build_trains import cumulative_distances, encode_polyline

LAT = 34.0
DEG = 1 / 111195.0                     # a metre of latitude, in degrees (the builder's earth)
EAST = DEG / 0.8290375725550417        # a metre of longitude at LAT


def at(x, y):
    """x metres east and y metres north of a corner."""
    return (round(105.0 + x * EAST, 5), round(LAT + y * DEG, 5))


def graph(edges, cls="hsr350"):
    """A routing network of the given edges, each a list of points, in the format of data/graph.json."""
    nodes, flat_nodes, flat_edges, shapes = {}, [], [], []

    def node(p):
        if p not in nodes:
            nodes[p] = len(nodes)
            flat_nodes.extend([round(p[0] * 1e5), round(p[1] * 1e5)])
        return nodes[p]
    for co in edges:
        u, v = node(co[0]), node(co[-1])
        flat_edges += [u, v, 0, round(cumulative_distances(co)[-1]), len(co) - 2]
        px, py = round(co[0][0] * 1e5), round(co[0][1] * 1e5)
        for x, y in co[1:-1]:
            qx, qy = round(x * 1e5), round(y * 1e5)
            shapes += [qx - px, qy - py]
            px, py = qx, qy
    return {"lines": [["line", cls, "cn"]], "nodes": flat_nodes, "edges": flat_edges, "shapes": shapes}


# a line running east for 30 km that swings 2 km north between 10 and 20 km, in three edges
CURVE = [at(10000, 0), at(12000, 1500), at(15000, 2000), at(18000, 1500), at(20000, 0)]
LINE = [[at(0, 0), at(5000, 0), at(10000, 0)], CURVE, [at(20000, 0), at(25000, 0), at(30000, 0)]]
NET = F.Network(graph(LINE))
CHORD = [at(0, 0), at(5000, 0), at(10000, 0), at(20000, 0), at(25000, 0), at(30000, 0)]     # cuts the swing: up to 2 km off


class Fit(unittest.TestCase):
    def test_a_chord_is_replaced_by_the_line(self):
        new, marks, notes = F.fit(CHORD, NET)
        self.assertEqual(notes["replaced"], 1)
        self.assertLessEqual(float(NET.away(new).max()), F.FAR)        # where it leaves and comes back it is still that near
        self.assertLess(float(sorted(NET.away(new))[-3]), 30)           # and the rest is on the line
        self.assertEqual(new[0], CHORD[0])
        self.assertEqual(new[-1], CHORD[-1])
        self.assertGreater(cumulative_distances(new)[-1], cumulative_distances(CHORD)[-1] + 500)

    def test_a_shape_on_the_line_comes_back_as_it_is(self):
        on = [p for co in LINE for p in co]
        new, marks, notes = F.fit(on, NET)
        self.assertEqual(new, on)
        self.assertFalse(notes["replaced"])

    def test_a_fitted_shape_is_left_alone_the_second_time(self):
        new, _, _ = F.fit(CHORD, NET)
        again, _, notes = F.fit(new, NET)
        self.assertEqual(again, new)
        self.assertFalse(notes["replaced"])

    def test_a_shape_a_little_off_the_line_is_left(self):
        near = [at(0, 100), at(10000, 100)]                      # 100 m aside all the way: what simplifying does
        new, _, notes = F.fit(near, NET)
        self.assertEqual(new, near)

    def test_a_stretch_with_no_line_to_take_is_left_and_counted(self):
        away = [at(0, 0), at(5000, 0), at(7000, 6000), at(9000, 0), at(10000, 0)]      # 12 km out and back: the line is 4 km
        new, _, notes = F.fit(away, NET)
        self.assertEqual(new, away)
        self.assertEqual(notes["the way along the lines is much shorter"], 1)

    def test_a_stretch_that_runs_off_the_end_is_left_and_counted(self):
        off = [at(25000, 0), at(30000, 0), at(33000, 3000)]
        new, _, notes = F.fit(off, NET)
        self.assertEqual(new, off)
        self.assertEqual(notes["runs off the end of the shape"], 1)

    def test_the_line_the_stretch_is_on_is_taken_not_one_that_runs_near(self):
        other = [at(9000, -150), at(21000, -150)]                # a straight line 150 m south of the chord
        net = F.Network(graph(LINE + [other]))
        new, _, notes = F.fit(CHORD, net)                        # the chord is within reach of it all the way
        self.assertFalse(notes["replaced"])
        self.assertEqual(new, CHORD)


class Stops(unittest.TestCase):
    def setUp(self):
        self.new, self.marks, _ = F.fit(CHORD, NET)
        self.old_along = cumulative_distances(CHORD)
        self.new_along = cumulative_distances(self.new)

    def test_a_stop_before_the_stretch_keeps_its_distance(self):
        d = F.moved([5000.0], [at(5000, 0)], CHORD, self.new, self.marks)[0]
        self.assertAlmostEqual(d, 5000.0, delta=2)

    def test_a_stop_after_it_moves_by_what_the_stretch_gained(self):
        gain = self.new_along[-1] - self.old_along[-1]
        d = F.moved([self.old_along[4]], [CHORD[4]], CHORD, self.new, self.marks)[0]
        self.assertAlmostEqual(d, self.old_along[4] + gain, delta=2)

    def test_a_stop_inside_it_is_projected_onto_the_line(self):
        station = at(15000, 2000)                                # at the top of the swing
        d = F.moved([15000.0], [station], CHORD, self.new, self.marks)[0]
        k = min(range(len(self.new)), key=lambda i: abs(self.new_along[i] - d))
        self.assertLess(abs(self.new[k][0] - station[0]) + abs(self.new[k][1] - station[1]), 0.0005)


class Data(unittest.TestCase):
    def data(self, times):
        stops = [{"id": "A", "name": "甲", "lon": CHORD[0][0], "lat": CHORD[0][1]},
                 {"id": "B", "name": "乙", "lon": at(15000, 2000)[0], "lat": at(15000, 2000)[1]},
                 {"id": "C", "name": "丙", "lon": CHORD[-1][0], "lat": CHORD[-1][1]}]
        along = cumulative_distances(CHORD)
        trip = {"id": "t", "number": "G1", "shapeId": "sold", "renderable": True,
                "stops": [[0, times[0], times[0], 0.0], [1, times[1], times[1], 15000.0], [2, times[2], times[2], round(along[-1], 1)]]}
        return {"stops": stops, "trips": [trip]}, {"sold": {"p": encode_polyline(CHORD), "bbox": [0, 0, 0, 0]}}

    def test_the_shape_and_the_stops_of_its_trips_change_together(self):
        index, shapes = self.data([0, 600, 1200])
        notes = F.fit_data(index, shapes, NET, 450.0)
        trip = index["trips"][0]
        self.assertEqual(notes["shapes changed"], 1)
        self.assertEqual(list(shapes), [trip["shapeId"]])
        self.assertNotEqual(trip["shapeId"], "sold")
        points = F.decode_polyline(shapes[trip["shapeId"]]["p"])
        distances = [s[3] for s in trip["stops"]]
        self.assertEqual(distances, sorted(distances))
        self.assertAlmostEqual(distances[-1], cumulative_distances(points)[-1], delta=0.2)

    def test_a_shape_is_left_when_a_trip_would_run_impossibly_fast(self):
        index, shapes = self.data([0, 100, 1200])                # 15 km in 100 s already; longer still on the line
        notes = F.fit_data(index, shapes, NET, 450.0)
        self.assertEqual(list(shapes), ["sold"])
        self.assertEqual(index["trips"][0]["stops"][1][3], 15000.0)
        self.assertEqual(notes["shapes left: a trip's stops would not stay in order"], 1)


class Polyline(unittest.TestCase):
    def test_decoding_gives_back_what_the_builder_encoded(self):
        self.assertEqual(F.decode_polyline(encode_polyline(CHORD)), CHORD)


if __name__ == "__main__":
    unittest.main()
