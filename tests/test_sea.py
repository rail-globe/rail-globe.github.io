"""South-East Asia (scripts/process_sea.py): the clip to a country's own land, the join to a
neighbour's line end, and Laos's written layers."""
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import process_sea  # noqa: E402

HAN = re.compile(r"[一-鿿]")
SQUARE = {"relation": 1, "iso": "XX", "name": "Square", "polygons": [[[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]]}


def extract(ways, stations=()):
    return {"ways": ways, "stations": list(stations), "relations": [], "places": [], "named": [], "territory": SQUARE}


class Clip(unittest.TestCase):
    def test_a_way_across_the_border_keeps_only_its_own_part(self):
        with mock.patch.object(process_sea, "neighbour_ends", return_value=[]):
            ex = process_sea.clip(extract([(7, {"railway": "rail"}, [(0.5, 0.5), (0.5, 1.5)])]), "la")
        self.assertEqual(ex["ways"], [(7, {"railway": "rail"}, [(0.5, 0.5), (0.5, 1.0)])])

    def test_the_piece_runs_on_to_a_neighbours_line_end_on_its_own_way(self):
        # the neighbour's line ends at a vertex of the same way 0.0003 degrees (33 m) beyond the border
        ends = [("rail_conv", (0.5, 1.0003))]
        with mock.patch.object(process_sea, "neighbour_ends", return_value=ends):
            joins = []
            ex = process_sea.clip(extract([(7, {}, [(0.5, 0.5), (0.5, 1.0003), (0.5, 1.5)])]), "la", joins)
        self.assertEqual(ex["ways"][0][2][-1], (0.5, 1.0003))
        self.assertEqual(len(joins), 1)
        self.assertLess(joins[0]["beyond_border_m"], 40)

    def test_a_line_end_far_beyond_the_border_is_not_reached(self):
        with mock.patch.object(process_sea, "neighbour_ends", return_value=[("rail_conv", (0.5, 1.01))]):
            ex = process_sea.clip(extract([(7, {}, [(0.5, 0.5), (0.5, 1.01), (0.5, 1.5)])]), "la")
        self.assertEqual(ex["ways"][0][2][-1], (0.5, 1.0))

    def test_only_stations_on_the_land_and_their_names_without_chinese(self):
        stations = [({"name": "ວຽງຈັນ 万象"}, 0.5, 0.5), ({"name": "Nong Khai"}, 0.5, 1.5)]
        with mock.patch.object(process_sea, "neighbour_ends", return_value=[]):
            ex = process_sea.clip(extract([], stations), "la")
        self.assertEqual([t["name"] for t, _, _ in ex["stations"]], ["ວຽງຈັນ"])

    def test_a_name_all_in_chinese_stays(self):
        self.assertEqual(process_sea.without_han("中老昆万线"), "中老昆万线")
        self.assertEqual(process_sea.without_han("ທາງລົດໄຟ ລາວ-ຈີນ 磨万铁路"), "ທາງລົດໄຟ ລາວ-ຈີນ")
        self.assertEqual(process_sea.without_han("ທາງລົດໄຟ ລາວ-ຈີນ (中老铁路)"), "ທາງລົດໄຟ ລາວ-ຈີນ")
        self.assertEqual(process_sea.without_han("BU 11 (Bandar Utama 11)"), "BU 11 (Bandar Utama 11)")
        self.assertEqual(process_sea.without_han("ปาดังเบซาร์ (ไทย)"), "ปาดังเบซาร์ (ไทย)")


@unittest.skipUnless((ROOT / "data" / "la_rail.geojson").exists(), "Laos not written")
class Laos(unittest.TestCase):
    def load(self, name):
        return json.loads((ROOT / "data" / name).read_text())

    def test_the_china_laos_railway_is_160_with_its_source(self):
        rows = [r for r in self.load("la_lines.json") if r["n"] == "ທາງລົດໄຟ ລາວ-ຈີນ"]
        self.assertEqual([(r["jk"], r["c"], r["d"], r["nz"]) for r in rows], [("fast", "hsr160", 160, "中老铁路")])
        self.assertIn("napstic.cn", rows[0]["ref"])

    def test_it_meets_chinas_line_at_its_end(self):
        # (the stretch from 磨憨 to the border is drawn at 160 since 2026-10-19, so in rail_hsr)
        china = [f for name in ("rail_conv.geojson", "rail_hsr.geojson") for f in self.load(name)["features"]
                 if f["properties"].get("n") == "中老昆万线"]
        parts = lambda f: f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]]
        ends = {tuple(round(v, 5) for v in co) for f in china for part in parts(f) for co in (part[0], part[-1])}
        lao = [f for f in self.load("la_rail.geojson")["features"] if f["properties"]["n"] == "ທາງລົດໄຟ ລາວ-ຈີນ"]
        lao_ends = {tuple(co) for f in lao for co in (f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][-1])}
        self.assertTrue(ends & lao_ends, (ends, lao_ends))

    def test_the_metre_gauge_line_is_a_branch(self):
        rows = {r["n"]: r for r in self.load("la_lines.json")}
        self.assertEqual(rows["สายตะวันออกเฉียงเหนือ"]["jk"], "branch")

    def test_no_chinese_in_n_and_chinese_only_from_the_table(self):
        table = {(r.split("\t")[1]) for r in (ROOT / "data" / "la_names.tsv").read_text().splitlines()[1:]}
        for name in ("la_stations.geojson", "la_rail.geojson", "la_depots.geojson"):
            for f in self.load(name)["features"]:
                p = f["properties"]
                self.assertFalse(HAN.search(p.get("n", "")), p)
                if "nz" in p:
                    self.assertIn(p["n"], table, p)


def load(name):
    return json.loads((ROOT / "data" / name).read_text())


def line_ends(name, line=None):
    out = set()
    for f in load(name)["features"]:
        if line is not None and f["properties"].get("n") != line:
            continue
        geom = f["geometry"]
        for co in geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]:
            out |= {tuple(round(v, 5) for v in co[0]), tuple(round(v, 5) for v in co[-1])}
    return out


def metro_lines(g):
    return {(c["n"], l["n"]): l for c in load(f"{g}_metro_cities.json") for l in c["lines"]}


@unittest.skipUnless((ROOT / "data" / "my_rail.geojson").exists(), "Malaysia not written")
class Malaysia(unittest.TestCase):
    def test_the_west_coast_line_is_main_and_neutral(self):
        rows = {r["n"]: r for r in load("my_lines.json")}
        west = rows["KTM Laluan kereta api Pantai Barat"]
        self.assertEqual((west["jk"], west.get("lc"), west.get("nz")), ("main", None, "西海岸铁路线"))
        self.assertFalse([r for r in load("my_lines.json") if "lc" in r or "d" in r])

    def test_the_ecrl_is_being_built_at_160_with_its_source(self):
        ecrl = [f["properties"] for f in load("my_build.geojson")["features"] if f["properties"]["n"] == "East Coast Rail Link"]
        self.assertEqual([(p["d"], p["jk"], "e" in p) for p in ecrl], [(160, "fast", False)])
        self.assertIn("nst.com.my", ecrl[0]["ref"])

    def test_komuter_and_the_airport_lines_are_kuala_lumpurs_metro_lines(self):
        lines = metro_lines("my")
        for name in ("Seremban Line", "Port Klang Line", "KLIA Ekspres", "KLIA Transit", "Laluan Kajang"):
            self.assertEqual(lines[("吉隆坡", name)]["jk"], "subway", name)
        self.assertEqual(lines[("吉隆坡", "Kelana Jaya Line")]["jk"], "urban")
        self.assertIn(("槟城", "Butterworth–Ipoh"), lines)
        self.assertFalse([k for k in lines if re.search("Skypark|Aerotrain", k[1])])


@unittest.skipUnless((ROOT / "data" / "sg_rail.geojson").exists(), "Singapore not written")
class Singapore(unittest.TestCase):
    def test_the_causeway_line_meets_malaysias_at_the_border(self):
        self.assertTrue(line_ends("sg_rail.geojson") & line_ends("my_rail.geojson", "KTM Laluan kereta api Pantai Barat"))
        self.assertEqual([(r["n"], r["jk"]) for r in load("sg_lines.json")], [("KTM Laluan kereta api Pantai Barat", "main")])

    def test_three_light_rail_lines_and_no_airport_skytrain(self):
        lines = metro_lines("sg")
        self.assertEqual(sorted(n for (_, n), l in lines.items() if l["jk"] == "urban"),
                         ["LRT Bukit Panjang Line", "LRT Punggol Line", "LRT Sengkang Line", "Sentosa Express"])
        self.assertFalse([k for k in lines if "Skytrain" in k[1]])

    def test_station_names_from_the_lta(self):
        rows = {r.split("\t")[1]: r.split("\t") for r in (ROOT / "data" / "sg_names.tsv").read_text().splitlines()[1:]}
        self.assertEqual(rows["Dhoby Ghaut"][4:6], ["多美歌", "O"])
        self.assertEqual(rows["Tuas West Road"][4], "大士西路")
        nz = {f["properties"]["n"]: f["properties"].get("nz") for f in load("sg_stations.geojson")["features"]}
        self.assertEqual(nz["Dhoby Ghaut"], "多美歌")


@unittest.skipUnless((ROOT / "data" / "th_rail.geojson").exists(), "Thailand not written")
class Thailand(unittest.TestCase):
    def test_lines_not_open_are_being_built(self):
        rail = {r["n"] for r in load("th_lines.json")}
        build = {f["properties"]["n"]: f["properties"] for f in load("th_build.geojson")["features"]}
        for name in ("สายเด่นชัย–เชียงราย–เชียงของ", "รถไฟความเร็วสูง สายกรุงเทพฯ-นครราชสีมา"):
            self.assertNotIn(name, rail)
            self.assertIn(name, build)
        hsr = build["รถไฟความเร็วสูง สายกรุงเทพฯ-นครราชสีมา"]
        self.assertEqual((hsr["d"], hsr["e"], hsr["jk"]), (250, 1, "hs"))

    def test_four_trunk_lines_main_the_rest_branch(self):
        kinds = {r["n"]: r["jk"] for r in load("th_lines.json")}
        for name in ("สายเหนือ", "สายตะวันออกเฉียงเหนือ", "สายตะวันออก", "สายใต้"):
            self.assertEqual(kinds[name], "main")
        self.assertEqual(kinds["สายกาญจนบุรี"], "branch")

    def test_bangkoks_lines(self):
        lines = metro_lines("th")
        self.assertEqual(len(lines), 10)
        self.assertEqual(lines[("曼谷", "รถไฟฟ้าสายสีทอง")]["jk"], "urban")
        for name in ("รถไฟฟ้าเชื่อมท่าอากาศยานสุวรรณภูมิ", "สายสีแดงเข้ม", "สายสีแดงอ่อน"):
            self.assertEqual(lines[("曼谷", name)]["jk"], "subway")

    def test_it_meets_laos_on_the_friendship_bridge_and_malaysia_at_padang_besar(self):
        self.assertTrue(line_ends("th_rail.geojson") & line_ends("la_rail.geojson"))
        self.assertTrue(line_ends("th_rail.geojson") & line_ends("my_rail.geojson"))


@unittest.skipUnless((ROOT / "data" / "id_rail.geojson").exists(), "Indonesia not written")
class Indonesia(unittest.TestCase):
    def test_whoosh_is_350_by_design(self):
        rows = [r for r in load("id_lines.json") if r["jk"] == "hs"]
        self.assertEqual([(r["n"], r["d"], "e" in r) for r in rows], [("Jalur Kereta Cepat Jakarta–Bandung", 350, False)])
        self.assertIn("chinadaily", rows[0]["ref"])
        self.assertEqual(load("id_facts.json")["bands"], ["hsr350"])

    def test_krl_and_the_airport_trains_are_commuter_lines(self):
        lines = metro_lines("id")
        for name in ("Lin Bogor", "Lin Lingkar Cikarang", "Lin Rangkasbitung", "Lin Tangerang", "Lin Tanjung Priuk", "Lin Soekarno Hatta"):
            self.assertEqual(lines[("雅加达", name)]["jk"], "commuter", name)
        self.assertEqual(lines[("雅加达", "MRT North-South Line")]["jk"], "subway")
        self.assertFalse([k for k in lines if re.search("Kalayang|Aeromovel", k[1])])

    def test_no_railway_takes_a_trains_colour(self):
        self.assertFalse([r["n"] for r in load("id_lines.json") if "lc" in r])


@unittest.skipUnless((ROOT / "vendor" / "glyphs" / "sans" / "3584-3839.pbf").exists(), "glyphs not made")
class Glyphs(unittest.TestCase):
    def test_thai_and_lao_glyphs_with_their_sources(self):
        made = json.loads((ROOT / "vendor" / "glyphs" / "sans" / "3584-3839.json").read_text())
        self.assertEqual([f["file"] for f in made["fonts"]], ["NotoSansThai-Regular.ttf", "NotoSansLao-Regular.ttf"])
        self.assertTrue(all("Open Font License" in f["license"] for f in made["fonts"]))
        self.assertEqual(made["glyphs"], 170)
        self.assertIn("3584-3839", load("glyphs.json"))
        self.assertTrue((ROOT / "vendor" / "glyphs" / "sans" / "OFL-NotoSans.txt").exists())


if __name__ == "__main__":
    unittest.main()
