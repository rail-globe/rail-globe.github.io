import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import design_speeds as D


def piece(x_from, x_to, **props):
    return {"type": "Feature", "properties": {"n": "line", "r": "hsr250", **props},
            "geometry": {"type": "LineString", "coordinates": [[116.0 + x_from, 40.0], [116.0 + x_to, 40.0]]}}


TOLD = dict(c="hsr200", d=200.0, dn="section", de="A~B", ref="https://example.org", db="infrastructure")


class Tails(unittest.TestCase):
    def test_the_end_of_a_line_takes_what_the_stretch_it_ends_has(self):
        drawn, changed = D.tails([piece(0, 0.002, c="hsr250", e=1), piece(0.002, 0.3, **TOLD)])
        self.assertEqual(changed, 1)
        self.assertEqual({k: drawn[0]["properties"].get(k) for k in ("c", "d", "de", "e")},
                         {"c": "hsr200", "d": 200.0, "de": "A~B", "e": None})

    def test_a_piece_between_two_stretches_is_not_a_tail(self):
        drawn, changed = D.tails([piece(0, 0.1, **TOLD), piece(0.1, 0.11, c="hsr250", e=1), piece(0.11, 0.3, **{**TOLD, "c": "hsr300", "d": 300})])
        self.assertEqual(changed, 0)
        self.assertEqual(drawn[1]["properties"]["c"], "hsr250")

    def test_a_hole_in_one_stretch_is_filled(self):
        drawn, changed = D.tails([piece(0, 0.1, **TOLD), piece(0.1, 0.11, c="hsr250", e=1), piece(0.11, 0.3, **TOLD)])
        self.assertEqual(changed, 1)
        self.assertEqual(drawn[1]["properties"]["c"], "hsr200")

    def test_a_long_piece_is_a_stretch_of_its_own(self):
        drawn, changed = D.tails([piece(0, 0.05, c="hsr250", e=1), piece(0.05, 0.3, **TOLD)])
        self.assertEqual(changed, 0)

    def test_a_tail_in_two_pieces_takes_them_one_after_the_other(self):
        drawn, changed = D.tails([piece(0, 0.001, c="hsr250", e=1), piece(0.001, 0.002, c="hsr250", e=1), piece(0.002, 0.3, **TOLD)])
        self.assertEqual(changed, 2)
        self.assertEqual([f["properties"]["c"] for f in drawn], ["hsr200"] * 3)

    def test_a_line_with_nothing_documented_is_left_as_it_is(self):
        drawn, changed = D.tails([piece(0, 0.002, c="hsr250", e=1), piece(0.002, 0.3, c="hsr250", e=1)])
        self.assertEqual(changed, 0)


class DepotTracks(unittest.TestCase):
    def cut(self, name, nominal):
        from shapely.geometry import LineString
        g = LineString([(116.0, 40.0), (116.1, 40.0)])
        return list(D.split_part(g, [], {"n": name, "c": nominal}))[0]["properties"]

    def test_the_way_into_a_depot_is_a_branch_whatever_its_track_says(self):
        for name in ("京南至动车段A线", "丰台动车走行B线", "某某动车所出入线"):
            props = self.cut(name, "hsr250")
            self.assertEqual((props["c"], props.get("e")), ("branch", None), name)

    def test_any_other_fast_line_without_a_reference_keeps_its_band(self):
        props = self.cut("某某联络线", "hsr250")
        self.assertEqual((props["c"], props.get("e")), ("hsr250", 1))


if __name__ == "__main__":
    unittest.main()
