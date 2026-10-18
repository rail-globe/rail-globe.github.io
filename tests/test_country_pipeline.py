"""Synthetic source-to-property contracts. No extracts, layout or generated files are used."""
import json
import sys
import unittest
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from country import (line_colours, railway_properties, railway_tracks, urban_groups,
                     whole_line_rows)
from process_europe import COUNTRIES
from process_jp import adopt_unnamed
from process_kr import KR
from process_uk import UK


def legacy_tracks(cfg, ways, length):
    """The baseline 56011d9 identity/adoption algorithm, without any pipeline entry point."""
    running = [wid for wid, (tags, _) in ways.items() if tags.get("railway") in cfg.rail
               and not tags.get("service") and tags.get("usage") not in cfg.skip_usage]
    named_km = Counter()
    for wid in running:
        named_km[cfg.plain_name(ways[wid][0].get("name"))] += length[wid]
    line_of, unnamed = {}, []
    for wid in running:
        name = cfg.plain_name(ways[wid][0].get("name"))
        if name and named_km[name] >= cfg.minor_km:
            line_of[wid] = ("rail", cfg.stretch_of(name, *ways[wid]), name)
        else:
            unnamed.append((wid, name))
    name_of = dict(unnamed)
    unnamed = [(wid, name_of[wid]) for wid in adopt_unnamed(line_of, list(name_of), ways)]
    for wid, name in unnamed:
        if name:
            line_of[wid] = ("rail", cfg.stretch_of(name, *ways[wid]), name)
    tracks = defaultdict(list)
    for wid, key in line_of.items():
        tracks[key].append(wid)
    return tracks, line_of, unnamed


def index_rows(cfg, tracks, ways, length, name_refs):
    rows = []
    track_km = Counter()
    for key, wids in tracks.items():
        props, _ = railway_properties(cfg, key, wids, ways, length, name_refs=name_refs)
        co = [point for wid in wids for point in ways[wid][1]]
        row = dict(props, bbox=[min(p[0] for p in co), min(p[1] for p in co),
                               max(p[0] for p in co), max(p[1] for p in co)],
                   tk=round(sum(length[wid] for wid in wids)))
        rows.append(row)
        track_km[key[2]] += sum(length[wid] for wid in wids)
    return whole_line_rows(cfg, rows, track_km)


class EuropeanPipelineContractTest(unittest.TestCase):
    def test_low_speed_unnamed_approach_keeps_identity_not_a_neighbours_band(self):
        ways = {
            # the physical line is a listed new-build line (only those are high-speed, 2026-10-18)
            1: ({"railway": "rail", "name": "Physical line", "usage": "main",
                 "maxspeed:design": "300", "maxspeed": "250", "_hsr_state": "new_build", "_hsr_ids": "test-00"}, [(0, 0), (1, 0)]),
            2: ({"railway": "rail", "usage": "main", "maxspeed": "80"}, [(1, 0), (2, 0)]),
            3: ({"railway": "rail", "name": "Physical line", "usage": "main",
                 "maxspeed": "200", "_hsr_state": "new_build", "_hsr_ids": "test-00"}, [(2, 0), (3, 0)]),
            4: ({"railway": "rail", "usage": "main"}, [(3, 0), (4, 0)]),
        }
        length = {1: 80, 2: 2, 3: 8, 4: 1}
        for cfg in COUNTRIES.values():
            with self.subTest(country=cfg.code):
                tracks, line_of, lost, refs = railway_tracks(cfg, ways, {}, length)
                self.assertEqual(lost, [(4, "")])
                self.assertEqual(set(line_of), set(ways))
                self.assertEqual({line_of[wid][2] for wid in (1, 2, 3)}, {"Physical line"})
                self.assertEqual(line_of[4][2], "")  # a dead end has no second identity boundary
                self.assertEqual(len(tracks), 4)
                props = {wid: railway_properties(cfg, line_of[wid], [wid], ways, length)[0]
                         for wid in ways}
                self.assertEqual((props[1]["c"], props[1]["d"]), ("hsr300", 300))
                self.assertNotIn("e", props[1])
                self.assertEqual((props[2]["jk"], props[2]["c"]), ("main", "main"))
                self.assertNotIn("d", props[2])
                self.assertEqual(props[2]["osm_maxspeed"], 80)
                self.assertEqual((props[3]["c"], props[3]["d"], props[3]["e"]), ("hsr200", 200, 1))
                self.assertNotIn("d", props[4])
                self.assertEqual(props[4]["speed_basis"], "unknown")
                rows = index_rows(cfg, tracks, ways, length, refs)
                selectable = [row for row in rows if not row.get("st")]
                self.assertEqual(len(selectable), 1)
                whole = selectable[0]
                self.assertEqual(whole["bbox"], [0, 0, 3, 0])
                self.assertEqual(whole["tk"], 90)
                self.assertEqual(whole["kinds"], ["hs", "main"])
                self.assertNotIn("d", whole)
                self.assertNotIn("design", whole)     # operating values must not be labelled design
                self.assertEqual(len(whole["speed_sections"]), 3)
                self.assertTrue(all(row["n"] == whole["n"] and row["g"] == whole["g"] for row in rows))

    def test_whole_line_track_km_is_rounded_once_not_per_short_stretch(self):
        cfg = COUNTRIES["de"]
        ways = {1: ({"railway": "rail", "maxspeed": "200"}, [(0, 0), (1, 0)]),
                2: ({"railway": "rail", "maxspeed": "80"}, [(1, 0), (2, 0)])}
        relations = {10: ({"type": "route", "route": "railway", "name": "Short line"}, [("w", 1), ("w", 2)])}
        length = {1: 0.4, 2: 0.4}
        tracks, _, _, refs = railway_tracks(cfg, ways, relations, length)
        whole = next(row for row in index_rows(cfg, tracks, ways, length, refs) if not row.get("st"))
        self.assertEqual(whole["tk"], 1)

    def test_railway_relation_fills_names_but_train_service_never_does(self):
        ways = {
            1: ({"railway": "rail", "usage": "main"}, [(0, 0), (1, 0)]),
            2: ({"railway": "rail", "name": "Tunnel", "usage": "main"}, [(1, 0), (2, 0)]),
            3: ({"railway": "rail", "name": "Own line", "usage": "main"}, [(10, 0), (11, 0)]),
            4: ({"railway": "rail", "usage": "main"}, [(20, 0), (21, 0)]),
            5: ({"railway": "rail", "service": "yard"}, [(2, 0), (3, 0)]),
            6: ({"railway": "construction", "construction": "rail"}, [(3, 0), (4, 0)]),
        }
        relations = {
            11: ({"type": "route", "route": "railway", "name": "Entity railway"},
                 [("w", wid) for wid in (1, 2, 3, 5, 6)]),
            12: ({"type": "route", "route": "train", "name": "TGV Paris - Lyon"},
                 [("w", 1), ("w", 3), ("w", 4)]),
        }
        length = dict.fromkeys(ways, 10)
        for cfg in COUNTRIES.values():
            with self.subTest(country=cfg.code):
                tracks, line_of, lost, refs = railway_tracks(cfg, ways, relations, length)
                self.assertEqual(line_of[1][2], "Entity railway")
                self.assertEqual(line_of[2][2], "Entity railway")
                self.assertEqual(line_of[3][2], "Own line")
                self.assertEqual(line_of[4][2], "")
                self.assertEqual(lost, [(4, "")])
                self.assertFalse(set(line_of) & {5, 6})
                self.assertEqual(refs, {1: {11}, 2: {11}})
                props, _ = railway_properties(cfg, line_of[1], tracks[line_of[1]], ways, length, name_refs=refs)
                self.assertEqual(props["name_ref"], "https://www.openstreetmap.org/relation/11#name")
                self.assertNotIn("TGV", json.dumps(props))

    def test_unique_relation_evidence_preserves_a_short_entity(self):
        cfg = COUNTRIES["de"]
        ways = {1: ({"railway": "rail"}, [(0, 0), (1, 0)]),
                2: ({"railway": "rail", "name": "Trunk"}, [(1, 0), (2, 0)])}
        relation = {10: ({"type": "route", "route": "railway", "name": "Named chord"}, [("w", 1)])}
        _, line_of, _, _ = railway_tracks(cfg, ways, relation, {1: 0.2, 2: 20})
        self.assertEqual(line_of[1][2], "Named chord")
        self.assertEqual(line_of[2][2], "Trunk")

    def test_conflicting_physical_relations_are_not_resolved_by_voting_or_adoption(self):
        cfg = COUNTRIES["fr"]
        ways = {1: ({"railway": "rail"}, [(0, 0), (1, 0)]),
                2: ({"railway": "rail", "name": "A"}, [(1, 0), (2, 0)])}
        relations = {10: ({"type": "route", "route": "railway", "name": "A"}, [("w", 1)]),
                     11: ({"type": "route", "route": "railway", "name": "B"}, [("w", 1)]),
                     12: ({"type": "route", "route": "railway", "name": "A"}, [("w", 1)])}
        _, line_of, lost, refs = railway_tracks(cfg, ways, relations, {1: 5, 2: 10})
        self.assertEqual(line_of[1][2], "")
        self.assertEqual(lost, [(1, "")])
        self.assertFalse(refs)

    def test_suburban_infrastructure_is_railway_not_an_unverified_city_service(self):
        for cfg, name in ((COUNTRIES["de"], "S-Bahn"), (COUNTRIES["fr"], "RER"),
                          (COUNTRIES["es"], "Cercanías"), (COUNTRIES["ch"], "S-Bahn")):
            with self.subTest(country=cfg.code):
                ways = {1: ({"railway": "rail", "usage": "main", "maxspeed": "120"}, [(0, 0), (1, 0)])}
                rels = {1: ({"type": "route", "route": "railway", "name": "Infrastructure"}, [("w", 1)]),
                        2: ({"type": "route", "route": "train", "name": name, "colour": "#ff0000"}, [("w", 1)])}
                tracks, line_of, _, refs = railway_tracks(cfg, ways, rels, {1: 10})
                props, _ = railway_properties(cfg, line_of[1], tracks[line_of[1]], ways, {1: 10}, name_refs=refs)
                self.assertEqual((props["n"], props["jk"]), ("Infrastructure", "main"))
                self.assertNotIn("train", cfg.urban)
                self.assertFalse(line_colours([("Company", "#ff0000", name)], many=cfg.many_colours))

    def test_suburban_track_with_only_train_relations_remains_unnamed_railway_coverage(self):
        for cfg, name in ((COUNTRIES["de"], "S-Bahn S1"), (COUNTRIES["fr"], "RER A"),
                          (COUNTRIES["es"], "Cercanías C-1"), (COUNTRIES["ch"], "S-Bahn S2")):
            with self.subTest(country=cfg.code):
                ways = {1: ({"railway": "rail", "usage": "main", "maxspeed": "120"}, [(0, 0), (1, 0)])}
                rels = {2: ({"type": "route", "route": "train", "name": name, "colour": "#ff0000"}, [("w", 1)])}
                tracks, line_of, unresolved, refs = railway_tracks(cfg, ways, rels, {1: 10})
                self.assertEqual(set(line_of), {1})
                props, _ = railway_properties(cfg, line_of[1], tracks[line_of[1]], ways, {1: 10}, name_refs=refs)
                self.assertEqual((props["n"], props["jk"], props["unnamed"]), ("", "main", 1))
                self.assertEqual(props["source_way_ids"], "1")
                self.assertFalse(refs)
                self.assertEqual(unresolved, [(1, "")])
                self.assertFalse(index_rows(cfg, tracks, ways, {1: 10}, refs))
                self.assertNotIn("lc", props)
                self.assertNotIn("name_ref", props)

    def test_unlabelled_components_are_kept_separate_and_speed_scopes_are_not_inherited(self):
        cfg = COUNTRIES["de"]
        ways = {3: ({"railway": "rail", "maxspeed": "80"}, [(10, 0), (11, 0)]),
                2: ({"railway": "rail", "maxspeed": "80"}, [(1, 0), (2, 0)]),
                1: ({"railway": "rail", "maxspeed": "300"}, [(0, 0), (1, 0)])}
        length = dict.fromkeys(ways, 1)
        tracks, line_of, _, _ = railway_tracks(cfg, ways, {}, length)
        self.assertEqual(len(tracks), 3)
        self.assertTrue(line_of[1][1].startswith("unnamed:w1:"))
        self.assertTrue(line_of[2][1].startswith("unnamed:w1:"))
        self.assertTrue(line_of[3][1].startswith("unnamed:w3:"))
        self.assertEqual(line_of, railway_tracks(cfg, dict(reversed(list(ways.items()))), {}, length)[1])
        low, _ = railway_properties(cfg, line_of[2], [2], ways, length)
        self.assertNotIn("d", low)
        self.assertEqual(low["osm_maxspeed"], 80)

    def test_europe_does_not_merge_distinct_city_lines_by_network_or_colour(self):
        for cfg in COUNTRIES.values():
            self.assertFalse(cfg.rail_seats)
            for col in (None, "#112233"):
                routes = {("Metro", "Line 1", col): {"ways": {1}},
                          ("Metro", "Line 2", col): {"ways": {2}}}
                groups = urban_groups(cfg, routes)
                self.assertEqual(len(groups), 2)
                self.assertEqual({parts[0][0] for parts in groups.values()}, {"Line 1", "Line 2"})


class LegacyCountryCompatibilityTest(unittest.TestCase):
    def test_opt_in_defaults_leave_uk_and_kr_unchanged(self):
        for cfg in (UK, KR):
            self.assertFalse(cfg.railway_relation_names)
            self.assertFalse(cfg.track_stretches)
            self.assertTrue(cfg.rail_seats)
            self.assertFalse(cfg.keep_unnamed_rail)
            self.assertIsNone(cfg.rail_properties)
            self.assertIsNone(cfg.urban_line_of)
            self.assertTrue(cfg.merge_urban_by_colour)
            self.assertEqual(cfg.many_colours, 5)
            rows = [{"n": "A", "g": cfg.code, "st": "part"}]
            self.assertIs(whole_line_rows(cfg, rows), rows)

    def test_default_identity_keys_adoption_and_order_match_baseline(self):
        ways = {
            1: ({"railway": "rail", "name": "A", "usage": "main"}, [(0, 0), (1, 0)]),
            2: ({"railway": "rail", "usage": "main"}, [(1, 0), (2, 0)]),
            3: ({"railway": "rail", "name": "A", "usage": "main"}, [(2, 0), (3, 0)]),
            4: ({"railway": "rail", "name": "Tiny chord"}, [(3, 0), (4, 0)]),
            5: ({"railway": "rail"}, [(10, 0), (11, 0)]),
            6: ({"railway": "rail", "service": "siding", "name": "A"}, [(0, 0), (0, 1)]),
            7: ({"railway": "rail", "usage": "main", "name": "동해선"}, [(0, 35.5), (1, 35.5)]),
            8: ({"railway": "rail", "usage": "main", "name": "동해선"}, [(1, 35.6), (2, 35.6)]),
        }
        length = {1: 10, 2: 1, 3: 10, 4: 0.2, 5: 10, 6: 10, 7: 5, 8: 5}
        relations = {1: ({"type": "route", "route": "railway", "name": "Must not fill defaults"}, [("w", 5)])}
        for cfg in (UK, KR):
            with self.subTest(country=cfg.code):
                expected = legacy_tracks(cfg, ways, length)
                actual = railway_tracks(cfg, ways, relations, length)
                self.assertEqual(list(actual[0].items()), list(expected[0].items()))
                self.assertEqual(list(actual[1].items()), list(expected[1].items()))
                self.assertEqual(actual[2], expected[2])
                self.assertFalse(actual[3])

    def test_default_properties_keep_baseline_values_and_json_key_order(self):
        for cfg, name, expected in (
            (UK, "High Speed 1", {"c": "hsr300", "n": "High Speed 1", "g": "uk", "jk": "hs",
                                 "d": 300, "ref": "https://en.wikipedia.org/wiki/High_Speed_1", "e": 1}),
            (KR, "경부고속선", {"c": "hsr350", "n": "경부고속선", "g": "kr", "jk": "hs",
                             "d": 350, "ref": "https://en.wikipedia.org/wiki/Gyeongbu_high-speed_railway"}),
            (UK, "Ordinary", {"c": "main", "n": "Ordinary", "g": "uk", "jk": "main", "lc": "#112233"}),
        ):
            ways = {1: ({"railway": "rail", "usage": "main"}, [(0, 0), (1, 0)])}
            props, _ = railway_properties(cfg, ("rail", None, name), [1], ways, {1: 10}, "#112233")
            self.assertEqual(json.dumps(props), json.dumps(expected))

    def test_default_urban_network_merging_including_no_colour_is_preserved(self):
        for cfg in (UK, KR):
            routes = {("Metro", "A", None): {"ways": {1}},
                      ("Metro", "B", None): {"ways": {2}},
                      ("DLR", "A", "#112233"): {"ways": {3}},
                      ("DLR", "B", "#112233"): {"ways": {4}}}
            groups = urban_groups(cfg, routes)
            self.assertEqual(list(groups), [("Metro", None), ("DLR", "#112233")])
            self.assertEqual(groups[("DLR", "#112233")], [("A", routes[("DLR", "A", "#112233")]),
                                                       ("B", routes[("DLR", "B", "#112233")])])


if __name__ == "__main__":
    unittest.main()
