"""Regression for differing speed tags on two tracks of one physical line."""
import contextlib
import io
import json
import pickle
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import country
from process_europe import COUNTRIES
from europe_urban_policy import POLICY_TAGS
from process_jp import km
from rail_sections import adopt_track_gaps, draw_sections, prune_parallel_stubs, source_sections


class RailSourceSectionsTest(unittest.TestCase):
    def test_only_a_bounded_same_line_gap_receives_a_name(self):
        ways = {90: ({}, [(8, 47), (8.01, 47)]),
                91: ({}, [(8.04, 47), (8.05, 47)]),
                3: ({}, [(8.01, 47), (8.02, 47)]),
                1: ({}, [(8.02, 47), (8.03, 47)]),
                2: ({}, [(8.03, 47), (8.04, 47)])}
        key = ("rail", None, "A")
        line_of = {90: key, 91: key}
        self.assertEqual(adopt_track_gaps(line_of, [1, 2, 3], ways), [])
        self.assertEqual({line_of[w] for w in (1, 2, 3)}, {key})
        line_of = {90: key, 91: ("rail", None, "B")}
        self.assertEqual(adopt_track_gaps(line_of, [1, 2, 3], ways), [1, 2, 3])
        self.assertEqual(set(line_of), {90, 91})

    def test_a_branching_unnamed_network_is_not_named_by_its_neighbour(self):
        ways = {10: ({}, [(8, 47), (8.01, 47)]),
                1: ({}, [(8.01, 47), (8.02, 47)]),
                2: ({}, [(8.02, 47), (8.03, 47)]),
                3: ({}, [(8.02, 47), (8.02, 47.01)])}
        line_of = {10: ("rail", None, "A")}
        self.assertEqual(adopt_track_gaps(line_of, [1, 2, 3], ways), [1, 2, 3])
        self.assertEqual(set(line_of), {10})

    def test_parallel_tracks_with_different_speeds_are_drawn_once_in_actual_pipeline(self):
        co = [(8 + i * .001, 47) for i in range(51)]
        parallel = [(x, y + .00005) for x, y in co]
        tags = {"railway": "rail", "name": "Test Line", "usage": "main"}
        extract = {"ways": [(1, dict(tags, maxspeed="160"), co),
                            (2, dict(tags, maxspeed="200"), parallel)],
                   "relations": [], "stations": [({"name": "Start"}, *co[0])],
                   "relation_tag_schema": list(POLICY_TAGS)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "extract_ch.pkl").write_bytes(pickle.dumps(extract))
            with patch.object(country, "RAW", root), patch.object(country, "OUT", root), \
                    patch.object(country, "write_yards"), contextlib.redirect_stdout(io.StringIO()):
                country.run(COUNTRIES["ch"])
            features = json.loads((root / "ch_rail.geojson").read_text())["features"]
            length = sum(km(f["geometry"]["coordinates"]) for f in features)
            self.assertAlmostEqual(length / km(co), 1, places=4)
            self.assertEqual({f["properties"]["source_way_ids"] for f in features}, {"1"})
            self.assertTrue(all(f["properties"]["osm_maxspeed"] == 160 for f in features))
            self.assertTrue(all("d" not in f["properties"] for f in features))
            rows = json.loads((root / "ch_lines.json").read_text())
            self.assertEqual(len([r for r in rows if not r.get("st")]), 1)

    def test_native_rail_rebuild_matches_full_stage_and_keeps_urban_products(self):
        co = [(8 + i * .001, 47) for i in range(51)]
        extract = {"ways": [(1, {"railway":"rail","name":"Test Line","usage":"main","maxspeed":"200"},co)],
                   "relations":[],"stations":[],"relation_tag_schema":list(POLICY_TAGS)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "extract_ch.pkl").write_bytes(pickle.dumps(extract))
            with patch.object(country,"RAW",root), patch.object(country,"OUT",root), \
                    patch.object(country,"write_yards"), contextlib.redirect_stdout(io.StringIO()):
                country.run(COUNTRIES["ch"])
                products = {p.name:p.read_bytes() for p in root.glob("ch_*")}
                country.run(COUNTRIES["ch"],rail_only=True)
                self.assertEqual({p.name:p.read_bytes() for p in root.glob("ch_*")},products)

    def test_longitudinal_evidence_change_keeps_exact_shared_boundary_and_own_sources(self):
        ways = {1: ({}, [(8, 47), (8.01, 47)]), 2: ({}, [(8.01, 47), (8.02, 47)])}
        keys = {1: ("rail", "low", "A"), 2: ("rail", "high", "A")}
        pieces, sources = source_sections([LineString([(8, 47), (8.01, 47), (8.02, 47)])],
                                          ways, ways, keys)
        self.assertEqual(sources, {keys[1]: {1}, keys[2]: {2}})
        self.assertEqual(list(pieces[keys[1]][0].coords)[-1],
                         list(pieces[keys[2]][0].coords)[0])

    def test_junction_restore_does_not_draw_the_discarded_direction_again(self):
        ways = {
            1: ({}, [(8, 47), (8.1, 47)]),
            2: ({}, [(8, 47.0002), (8.059, 47.0002), (8.06, 47)]),
            3: ({}, [(8.04, 47.01), (8.04, 47.0002)]),
        }
        keys = {1: ("rail", "low", "A"), 2: ("rail", "high", "A"),
                3: ("rail", "branch", "B")}
        tracks = {key: [wid] for wid, key in keys.items()}
        once, sources, closed = draw_sections(tracks, ways, keys)
        self.assertGreater(closed, 0)  # This genuinely exercises the restoration.
        line_a = [g for key, (_, geoms) in once.items() if key[2] == "A" for g in geoms]
        self.assertAlmostEqual(sum(g.length for g in line_a), .1, places=7)
        self.assertEqual(set().union(*(ids for key, ids in sources.items() if key[2] == "A")), {1})
        self.assertTrue(any(key[2] == "B" for key in once))

    def test_real_separate_branch_is_kept_after_duplicate_cleanup(self):
        ways = {
            1: ({}, [(8, 47), (8.1, 47)]),
            2: ({}, [(8.04, 47), (8.04, 47.02)]),
        }
        key = ("rail", "low", "A")
        once, sources, _ = draw_sections({key: [1, 2]}, ways, {1: key, 2: key})
        drawn = [g for _, rows in once.values() for g in rows]
        self.assertAlmostEqual(sum(g.length for g in drawn), .12)
        self.assertEqual(sources[key], {1, 2})

    def test_short_fully_parallel_terminal_path_is_removed(self):
        main = LineString([(8, 47), (8.02, 47)])
        duplicate = LineString([(8.002, 47.0002), (8.018, 47.0002)])
        self.assertEqual(prune_parallel_stubs([main, duplicate]), [main])

    def test_short_branch_that_turns_away_is_retained(self):
        main = LineString([(8, 47), (8.02, 47)])
        branch = LineString([(8.01, 47), (8.011, 47.001), (8.011, 47.006)])
        self.assertEqual(prune_parallel_stubs([main, branch]), [main, branch])

    def test_short_parallel_approach_that_leaves_corridor_is_retained(self):
        main = LineString([(8, 47), (8.02, 47)])
        branch = LineString([(8.002, 47.0002), (8.01, 47.0002), (8.018, 47.003)])
        self.assertEqual(prune_parallel_stubs([main, branch]), [main, branch])

    def test_same_railway_in_separate_parallel_tubes_is_drawn_once(self):
        tags = {"railway": "rail", "tunnel": "yes", "name": "Same railway"}
        ways = {1: (tags, [(8, 47), (8.1, 47)]),
                2: (tags, [(8, 47.0009), (8.1, 47.0009)])}
        key = ("rail", "same", "Same railway")
        once, sources, _ = draw_sections({key: [1, 2]}, ways, {1: key, 2: key})
        self.assertAlmostEqual(sum(g.length for _, rows in once.values() for g in rows), .1)
        self.assertEqual(sources[key], {1})

    def test_synthetic_join_never_inherits_speed_from_nearby_source(self):
        ways = {1: ({}, [(8, 47), (8.01, 47)]),
                2: ({}, [(8.01, 47.00005), (8.02, 47.00005)])}
        keys = {1: ("rail", "low", "A"), 2: ("rail", "high", "A")}
        path = LineString([(8, 47), (8.01, 47), (8.01, 47.00005), (8.02, 47.00005)])
        pieces, sources = source_sections([path], ways, ways, keys)
        self.assertIn(None, pieces)
        self.assertNotIn(None, sources)
        self.assertEqual(list(pieces[None][0].coords), [(8.01, 47), (8.01, 47.00005)])

    def test_reverse_path_and_way_input_order_keep_source_scope(self):
        ways = {2: ({}, [(8.01, 47), (8.02, 47)]), 1: ({}, [(8, 47), (8.01, 47)])}
        keys = {1: ("rail", "low", "A"), 2: ("rail", "high", "A")}
        path = LineString([(8.02, 47), (8.01, 47), (8, 47)])
        pieces, sources = source_sections([path], ways, ways, keys)
        self.assertEqual(sources, {keys[2]: {2}, keys[1]: {1}})
        self.assertAlmostEqual(sum(g.length for rows in pieces.values() for g in rows), path.length)

    def test_path_beginning_with_an_unattributed_link_keeps_both_link_endpoints(self):
        ways = {1: ({}, [(8, 47), (8.01, 47)])}
        keys = {1: ("rail", "known", "A")}
        path = LineString([(8, 47.00005), (8, 47), (8.01, 47)])
        pieces, sources = source_sections([path], ways, ways, keys)
        self.assertEqual(list(pieces[None][0].coords), [(8, 47.00005), (8, 47)])
        self.assertEqual(sources, {keys[1]: {1}})
        self.assertAlmostEqual(sum(g.length for rows in pieces.values() for g in rows), path.length)


if __name__ == "__main__":
    unittest.main()
