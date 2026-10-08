"""Japan: how a track's tags become a line, its company and its colour (scripts/process_jp.py)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from process_jp import colour_of, company, geometry, known_colour, plain_name, readable_on_dark, shown_name
from process_jp import KNOWN_LINE_FIRM, OTHER, merge_short_connectors, jkind, metro_jk


def luminance(col):
    r, g, b = (int(col[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


class GeneratedJapanDataTest(unittest.TestCase):
    def test_generated_stations_are_scoped_to_japan(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / "data" / "jp_stations.geojson").read_text())
        self.assertTrue(data["features"])
        self.assertTrue(all(f["properties"].get("g") == "jp" for f in data["features"]))

    def test_generated_lines_are_scoped_to_japan_and_classified(self):
        # the page shows a Japanese layer only for features marked g = "jp" with a class of that layer
        root = Path(__file__).resolve().parents[1]
        for name, kinds in (("jp_rail.geojson", {"shinkansen", "jr", "private_big", "third_sector", "private_local", "unknown"}),
                            ("jp_metro.geojson", {"subway", "urban"})):
            features = json.loads((root / "data" / name).read_text())["features"]
            self.assertTrue(features, name)
            self.assertEqual({f["properties"].get("g") for f in features}, {"jp"}, name)
            self.assertLessEqual({f["properties"].get("jk") for f in features}, kinds, name)

    def test_generated_lines_are_not_coloured_by_company(self):
        # company colours were dropped: a line the source gives no colour is neutral, wherever it is
        root = Path(__file__).resolve().parents[1]
        features = json.loads((root / "data" / "jp_rail.geojson").read_text())["features"]
        colours = lambda name: {f["properties"]["lc"] for f in features if f["properties"]["n"] == name}
        for name in ("九州新幹線", "西九州新幹線", "北海道新幹線"):
            self.assertEqual(colours(name), {OTHER}, name)
        self.assertNotIn(OTHER, colours("東北新幹線") | colours("東海道新幹線") | colours("山陽新幹線"))
        self.assertEqual(len(colours("北陸新幹線")), 2)
        self.assertFalse((root / "data" / "jp_operators.json").exists())

    def test_generated_taxonomy_has_no_missing_or_conflicting_classification(self):
        root = Path(__file__).resolve().parents[1]
        audit = json.loads((root / "data" / "jp_taxonomy_audit.json").read_text())
        self.assertEqual(audit["unclassified_lines"], {"rail": 0, "metro": 0})
        self.assertEqual(audit["conflicting_lines"], {"rail": [], "metro": []})


class JapanTest(unittest.TestCase):
    def test_the_jr_companies_are_known_under_every_spelling(self):
        self.assertEqual(company("東日本旅客鉄道")[0], "JR東日本")
        self.assertEqual(company("東海旅客鉄道 (JR Central)")[0], "JR東海")
        self.assertEqual(company("JR West")[0], "JR西日本")
        self.assertEqual(company("東日本旅客鉄道;東京地下鉄")[0], "JR東日本")       # the first of several
        self.assertEqual({company(o)[1] for o in ("九州旅客鉄道", "JR北海道")}, {"JR"})

    def test_another_company_keeps_its_name_and_may_have_a_short_one(self):
        self.assertEqual(company("近畿日本鉄道"), ("近畿日本鉄道", "近鉄"))
        self.assertEqual(company("東京急行電鉄")[0], "東急電鉄")
        self.assertEqual(company("株式会社ゆりかもめ")[0], "ゆりかもめ")
        self.assertEqual(company("沖縄都市モノレール (Okinawa City Monorail)")[0], "沖縄都市モノレール")
        self.assertEqual(company(None), (None, ""))

    def test_the_shinkansen_take_the_line_colours_the_source_lists(self):
        self.assertEqual(known_colour("東海道新幹線", "JR東海"), known_colour("山陽新幹線", "JR西日本"))      # both blue
        self.assertEqual(known_colour("東北新幹線", "JR東日本"), known_colour("上越新幹線", "JR東日本"))      # both green
        self.assertNotEqual(known_colour("北陸新幹線", "JR東日本"), known_colour("北陸新幹線", "JR西日本"))   # changes with the company
        self.assertEqual(known_colour("北陸新幹線", "JR西日本"), known_colour("山陽新幹線", "JR西日本"))

    def test_a_line_without_a_colour_of_its_own_gets_none_from_its_company(self):
        for name, firm in (("九州新幹線", "JR九州"), ("西九州新幹線", "JR九州"), ("北海道新幹線", "JR北海道"), ("JR函館本線", "JR北海道")):
            self.assertIsNone(known_colour(name, firm), name)

    def test_a_tracks_name_is_reduced_to_the_name_of_its_line(self):
        self.assertEqual(plain_name("JR東北本線"), "東北本線")
        self.assertEqual(plain_name("沖縄都市モノレール線 (ゆいレール)"), "沖縄都市モノレール線")
        self.assertEqual(plain_name("山陽新幹線;相生トンネル"), "山陽新幹線")
        self.assertEqual(plain_name("海峡線・北海道新幹線"), "北海道新幹線")
        self.assertEqual(plain_name("京王電鉄相模原線", "京王電鉄"), "相模原線")
        self.assertEqual(plain_name("名古屋鉄道名古屋本線", "名古屋市"), "名鉄名古屋本線")
        self.assertEqual(plain_name("京王電鉄", "京王電鉄"), "京王電鉄")                  # a line named like its company stays

    def test_a_tunnel_or_bridge_named_for_itself_is_no_line(self):
        self.assertEqual(plain_name("榛名トンネル"), "")
        self.assertEqual(plain_name("第一只見川橋梁"), "")

    def test_lines_are_called_as_people_call_them(self):
        self.assertEqual(shown_name("山手線", "JR東日本", "JR"), "JR山手線")
        self.assertEqual(shown_name("大阪線", "近畿日本鉄道", "近鉄"), "近鉄大阪線")
        self.assertEqual(shown_name("京王線", "京王電鉄", "京王"), "京王線")              # already says whose it is
        self.assertEqual(shown_name("東北新幹線", "JR東日本", "JR"), "東北新幹線")
        self.assertEqual(shown_name("しなの鉄道線", "しなの鉄道", "しなの"), "しなの鉄道線")   # no short name in use: left alone

    def test_colours_are_read_in_the_ways_they_are_written(self):
        self.assertEqual(colour_of("#F39700"), "#f39700")
        self.assertEqual(colour_of("#abc"), "#aabbcc")
        self.assertEqual(colour_of("red"), "#ff0000")
        self.assertIsNone(colour_of("ゴールド"))
        self.assertIsNone(colour_of(None))

    def test_a_dark_colour_is_lifted_and_keeps_its_hue(self):
        lifted = readable_on_dark("#0000ff")
        self.assertGreaterEqual(luminance(lifted), 0.4)
        r, g, b = (int(lifted[i:i + 2], 16) for i in (1, 3, 5))
        self.assertTrue(b > r and b > g)
        self.assertEqual(readable_on_dark("#f39700"), "#f39700")



    def test_short_connector_between_two_points_of_parent_folds_into_parent(self):
        # 千駄ケ谷: a short piece named differently runs between two points of the parent line.
        # production track keys are the shown_name values (JR-prefixed), not the raw OSM names
        parent = ("rail", "JR東日本", "JR中央緩行線")
        piece = ("rail", "JR東日本", "JR中央・総武緩行線")
        ways = {
            1: (None, [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]),
            2: (None, [[0.0, 0.0], [0.01, 0.0]]),   # stub A: touches parent at x=0
            3: (None, [[2.0, 0.0], [2.01, 0.0]]),   # stub B: touches parent at x=2
        }
        tracks = {parent: [1], piece: [2, 3]}
        line_of = {1: parent, 2: piece, 3: piece}
        length = {1: 52.0, 2: 0.01, 3: 0.01}   # the connector piece is short, the parent is a long main line
        moved = merge_short_connectors(tracks, ways, length, line_of=line_of)
        self.assertNotIn(piece, tracks)                      # the异名 group no longer drawn alone
        self.assertEqual(set(tracks[parent]), {1, 2, 3})    # its geometry kept, reclassified into parent
        # line_of must follow: every way now resolves to a key that still exists in tracks
        for w, k in line_of.items():
            self.assertIn(k, tracks, f"way {w} line_of points at a popped key")
        self.assertEqual({line_of[2], line_of[3]}, {parent})   # the moved ways now belong to the parent
        self.assertEqual(tracks.keys(), set(line_of.values()))  # no orphan key, no key with no ways

    def test_single_end_siding_is_kept_as_its_own_line(self):
        # a branch touching the parent only at one end must NOT be folded in (real branch / siding)
        parent = ("rail", "JR東日本", "総武本線")
        branch = ("rail", "JR東日本", "越中島支線")
        ways = {
            1: (None, [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]),
            2: (None, [[0.0, 0.0], [0.0, 0.5]]),   # touches parent only at x=0, other end free
        }
        tracks = {parent: [1], branch: [2]}
        length = {w: 1.0 for w in ways}
        merge_short_connectors(tracks, ways, length)
        self.assertIn(branch, tracks)             # the branch survives on its own

    def test_double_ended_connector_not_on_the_whitelist_keeps_its_own_name(self):
        # a short piece that touches a long parent at both ends but is NOT a confirmed alias keeps
        # its own identity (e.g. an independent line / unverified candidate must not be auto-renamed)
        parent = ("rail", "JR東海", "東海道本線")
        branch = ("rail", "JR東海", "御殿場線")
        ways = {
            1: (None, [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]),
            2: (None, [[0.0, 0.0], [0.01, 0.0]]),
            3: (None, [[2.0, 0.0], [2.01, 0.0]]),
        }
        tracks = {parent: [1], branch: [2, 3]}
        length = {1: 304.0, 2: 0.01, 3: 0.01}
        merge_short_connectors(tracks, ways, length)
        self.assertIn(branch, tracks)          # not in the whitelist: stays its own line

    def test_two_short_yard_tracks_touching_each_other_do_not_merge(self):
        # 1番線 and 2番線 are parallel yard tracks that touch each other at both ends; neither is a
        # long main line, so they must stay as their own lines (not folded into each other).
        a = ("rail", "JR東日本", "1番線")
        b = ("rail", "JR東日本", "2番線")
        ways = {
            1: (None, [[0.0, 0.0], [0.01, 0.0]]),
            2: (None, [[0.0, 0.0], [0.01, 0.001]]),   # parallel to 1番線, same two ends
        }
        tracks = {a: [1], b: [2]}
        length = {1: 0.01, 2: 0.01}
        merge_short_connectors(tracks, ways, length)
        self.assertIn(a, tracks)
        self.assertIn(b, tracks)

    def test_sections_are_deduplicated_when_one_line_aggregates_several_track_keys(self):
        # 北陸 / 九州: several operators map onto one shown line; the same verified source must
        # not be appended once per track key.
        spec = {"from": "盛岡", "to": "新青森", "design": 260, "ref": "R", "title": "T", "publisher": "P", "quote": "Q", "note": "N"}
        rows = {}
        for track_key in [("rail", "JR東日本", "東北新幹線"), ("rail", "JR北海道", "東北新幹線")]:
            row = rows.setdefault(track_key[2], {"sections": []})
            sig = (spec.get("from"), spec.get("to"), spec.get("design"), spec.get("ref"))
            if sig in row.setdefault("_sec_seen", set()):
                continue
            row["_sec_seen"].add(sig)
            row["sections"].append({k: spec.get(k) for k in ("from", "to", "design", "ref", "title", "quote", "note")})
        row = rows["東北新幹線"]
        self.assertEqual(len(row["sections"]), 1)
        self.assertEqual(row["sections"][0]["design"], 260)


class JapanKindTest(unittest.TestCase):
    """jk: Japan-only taxonomy, not China's 高铁/普速/地铁 (operator + name, per audit JSON)."""

    def test_shinkansen_is_by_name_not_speed(self):
        self.assertEqual(jkind("東北新幹線", "JR東日本"), "shinkansen")
        self.assertEqual(jkind("秋田新幹線", "JR東日本"), "jr")       # 1066mm conventional, not design-speed
        self.assertEqual(jkind("山形新幹線", "JR東日本"), "jr")

    def test_jr_companies_are_jr(self):
        for firm in ("JR北海道", "JR東日本", "JR東海", "JR西日本", "JR四国", "JR九州", "JR貨物"):
            self.assertEqual(jkind("山手線", firm), "jr", firm)

    def test_big_private_third_sector_local_are_split(self):
        self.assertEqual(jkind("近鉄奈良線", "近畿日本鉄道"), "private_big")      # 大手16
        self.assertEqual(jkind("京成成田空港線", "成田空港高速鉄道"), "private_big")
        self.assertEqual(jkind("あいの風とやま鉄道線", "あいの風とやま鉄道"), "third_sector")   # 三セク
        self.assertEqual(jkind("弘南線", "弘南鉄道"), "private_local")           # 地方中小民鉄
        self.assertEqual(jkind("神鉄三田線", None), "private_local")

    def test_operatorless_is_unknown_not_private(self):
        self.assertEqual(jkind("R久留里線", None), "unknown")

    def test_verified_line_identity_can_override_a_misleading_infrastructure_owner(self):
        self.assertEqual(KNOWN_LINE_FIRM["山田線"], "JR東日本")

    def test_metro_infra_buckets(self):
        from collections import Counter
        self.assertEqual(metro_jk(Counter({"subway": 10})), "subway")
        self.assertEqual(metro_jk(Counter({"monorail": 5, "subway": 1})), "urban")
        self.assertEqual(metro_jk(Counter({"light_rail": 5, "subway": 1})), "urban")

    def test_metro_line_rows_carry_jk_and_audit_keeps_feature_vs_line(self):
        # The lines tab filters by line jk, so every metro line row must carry it; the audit must
        # report feature count AND line count separately (feature sum is NOT the line count).
        from collections import Counter
        rows = [{"n": "G", "col": "#000", "jk": "subway"}, {"n": "M", "col": "#111", "jk": "urban"}]
        for r in rows:
            self.assertIn(r["jk"], ("subway", "urban"))
        line = Counter(r["jk"] for r in rows)
        self.assertEqual(sum(line.values()), len(rows))
        self.assertEqual(line["subway"], 1)


if __name__ == "__main__":
    unittest.main()
