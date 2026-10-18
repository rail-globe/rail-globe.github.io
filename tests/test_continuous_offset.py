import json
import sys
import unittest
from pathlib import Path
from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from continuous_offset import chains, profile, value_at
from side_by_side import side_by_side as generate


def side_by_side(*args, **kwargs):
    return generate(*args, continuous=True, **kwargs)


def feature(coords, name="A", colour="#ff0000", **props):
    return {"type": "Feature", "properties": {"n": name, "r": "00", "col": colour, **props},
            "geometry": {"type": "LineString", "coordinates": coords}}


class ContinuousOffsetTest(unittest.TestCase):
    def test_same_named_same_colour_basel_services_do_not_merge(self):
        co = [[7.59, 47.55], [7.59, 47.59]]
        out = side_by_side([feature(co, "Tram 8", network="BVB", rid="123"),
                            feature(co, "Tram 8", network="RVL", rid="456")])
        self.assertEqual(len(out), 2)
        self.assertEqual({f["properties"]["network"] for f in out}, {"BVB", "RVL"})
        self.assertEqual(sorted(f["properties"]["off"] for f in out), [-.5, .5])

    def test_reversed_split_retains_vertices_and_has_one_profile_domain(self):
        original = [feature([[0, 0], [.02, 0]], c="main"),
                    feature([[.04, 0], [.02, 0]], c="hsr200"),
                    feature([[.01, 0], [.03, 0]], "B", "#0000ff")]
        out = side_by_side(original)
        for before, after in zip(original, out):
            self.assertEqual(before["geometry"], after["geometry"])
        a, b = (json.loads(f["properties"]["op"]) for f in out[:2])
        self.assertAlmostEqual(value_at(a, .02), -value_at(b, .02))
        self.assertEqual(a["ramps"], b["ramps"])
        self.assertEqual(b["direction"], -a["direction"])

    def test_exact_ports_only_no_nearest_track_bridge(self):
        parts = [("A", "", LineString([[0, 0], [.01, 0]])),
                 ("A", "", LineString([[.01000001, 0], [.02, 0]]))]
        self.assertEqual(len(chains(parts)), 2)

    def test_branch_does_not_guess_continuation(self):
        parts = [("A", "", LineString(co)) for co in (
            [[0, 0], [.01, 0]], [[.01, 0], [.02, 0]], [[.01, 0], [.01, .01]])]
        result = chains(parts)
        self.assertEqual(len(result), 3)
        self.assertEqual(sorted(i for _, members in result for i, _, _ in members), [0, 1, 2])

    def test_periodic_seam_has_equal_value_and_derivative(self):
        p = profile([[0, .01, 0, 1], [.01, .03, 1, 2], [.03, .04, -.5, 2]], .004, True)
        self.assertEqual(value_at(p, 0), value_at(p, .04))
        eps = 1e-7
        left = (value_at(p, .04) - value_at(p, .04 - eps)) / eps
        right = (value_at(p, eps) - value_at(p, 0)) / eps
        self.assertLess(abs(left - right), .02)

    def test_rings_flag_never_rotates_source_start(self):
        ring = [[0, 0], [.02, 0], [.02, .02], [0, .02], [0, 0]]
        other = [[.02, 0], [.02, .02], [0, .02]]
        out = side_by_side([feature(ring), feature(other, "B", "#0000ff")], rings=True)
        self.assertEqual(out[0]["geometry"]["coordinates"], ring)
        p = json.loads(out[0]["properties"]["op"])
        self.assertEqual(value_at(p, 0), value_at(p, .08))


if __name__ == "__main__":
    unittest.main()
