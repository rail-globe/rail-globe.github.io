"""The names on the yards and depots layer (scripts/depots.py): which named thing in OSM labels
which depot, and what the written depots files must hold to."""
import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import depots as D

ROOT = Path(__file__).resolve().parents[1]
LON, LAT = 116.0, 35.0                       # where the made-up yards below lie
M_LAT = 1 / 111320                           # a metre north, in degrees
M_LON = 1 / (111320 * math.cos(math.radians(LAT)))


def at(east, north):
    """A point so many metres east and north of (LON, LAT)."""
    return (LON + east * M_LON, LAT + north * M_LAT)


def fan(east, north, tracks=8, length=400, apart=5):
    """A fan of yard track: so many parallel tracks, west to east, its south-west corner at the point."""
    return [[at(east, north + k * apart), at(east + length, north + k * apart)] for k in range(tracks)]


def area(east, north, width, height):
    """The outline of a rectangle, as an object's ring."""
    return [[at(east, north), at(east + width, north), at(east + width, north + height), at(east, north + height), at(east, north)]]


def ground(name, ring, form="landuse=railway"):
    return {"form": form, "osm": "w1", "name": name, "key": "name", "at": ring[0][0], "ring": ring}


def point(name, where, form="railway=yard"):
    return {"form": form, "osm": "n1", "name": name, "key": "name", "at": where, "ring": None}


def feature(name, where, origin="object"):
    return {"type": "Feature", "properties": {"n": name, "from": origin}, "geometry": {"type": "Point", "coordinates": list(where)}}


def metres(a, b):
    return math.hypot((a[0] - b[0]) / M_LON, (a[1] - b[1]) / M_LAT)


class NameTest(unittest.TestCase):
    def test_never_a_depot(self):
        for g, name in (("cn", "联合检修库"), ("cn", "施工廠區一區"), ("cn", "仕佳興業辦公室"), ("cn", "人民公园停车场"), ("cn", "都江堰轨道交通有限责任公司"),
                        ("cn", "长途客运站"), ("cn", "540卸矿站"), ("cn", "武汉客运段职教基地"), ("cn", "深圳地铁松岗车辆段左侧车库3"),
                        ("uk", "New Palace Yard Vent Shaft"),
                        ("jp", "（株）横浜シーサイドライン"), ("jp", "岩見沢操車場跡地"), ("kr", "공영주차장"),
                        ("uk", "Station Road"), ("uk", "Bus Depot"), ("uk", "Brick Works"), ("uk", "Former Langley Green Marshalling Yard")):
            self.assertTrue(D.not_a_depot(g, name), name)

    def test_a_place_or_a_company_in_the_name_of_a_depot(self):
        for g, name in (("cn", "南京地铁二桥公园车辆段"), ("cn", "郑州北货车车辆段"), ("cn", "坪山云巴中心公园停车场"), ("cn", "上海铁路客技站"),
                        ("cn", "大朗客运整备所"), ("cn", "彰化扇形車庫"), ("jp", "阪急電鉄株式会社 正雀工場"), ("kr", "광주차량사업소"),
                        ("uk", "Barton Mill Carriage Servicing Depot"), ("uk", "Wolverhampton Steel Terminal"), ("uk", "Beckton Depot Docklands Light Railway")):
            self.assertFalse(D.not_a_depot(g, name), name)

    def test_a_name_that_says_only_what_the_thing_is(self):
        for g, name in (("uk", "Railway Yard"), ("uk", "TMD"), ("uk", "Engine Shed"), ("uk", "HST Stabling Sidings"), ("cn", "上行调车场"),
                        ("cn", "III- 下行编发场"), ("cn", "IV场（到达）"), ("cn", "存车Ⅰ场"), ("jp", "SL第2検修庫"), ("jp", "第二操車場"), ("kr", "기지")):
            self.assertTrue(D.generic(g, name), name)
        for g, name in (("uk", "Cheddleton MPD"), ("uk", "Alstom Traincare"), ("cn", "上海南车辆段"), ("cn", "昆明机务段"), ("jp", "梅小路蒸気機関車庫"), ("kr", "고모보수기지")):
            self.assertFalse(D.generic(g, name), name)

    def test_what_an_object_of_each_kind_needs_to_name_a_depot(self):
        self.assertTrue(D.names_a_depot("uk", "Anything At All", "railway=yard"))
        self.assertFalse(D.names_a_depot("uk", "Chrysalis Rail Services", "railway=workshop"))      # a shed named for a company
        self.assertTrue(D.names_a_depot("uk", "Cheddleton MPD", "railway=workshop"))
        self.assertTrue(D.names_a_depot("cn", "某某车辆段", "landuse=railway"))
        self.assertFalse(D.names_a_depot("cn", "某某货运中心", "landuse=railway"))
        # ground that is not railway ground: a car park unless it holds the tracks, a depot word that can mean nothing else anywhere
        self.assertFalse(D.names_a_depot("cn", "某某停车场", "landuse=industrial", share=0.0))
        self.assertTrue(D.names_a_depot("cn", "某某停车场", "landuse=industrial", share=0.5))
        self.assertTrue(D.names_a_depot("cn", "广清城际龙塘动车运用所", "landuse=industrial", share=0.0))

    def test_the_name_an_object_is_known_by(self):
        self.assertEqual(D.name_of({"name": "屯門車廠 Tuen Mun Depot", "name:zh": "屯門車廠"}, "landuse=railway", "cn"), ("屯門車廠", "name:zh"))
        self.assertEqual(D.name_of({"name:en": "X Depot"}, "railway=depot", "uk"), ("X Depot", "name:en"))
        self.assertEqual(D.name_of({"operator": "某某地铁"}, "landuse=railway", "cn"), ("某某地铁", "operator"))
        self.assertEqual(D.name_of({"operator": "某某公司"}, "landuse=industrial", "cn"), ("", ""))


class FansTest(unittest.TestCase):
    def test_a_fan_is_many_tracks_side_by_side(self):
        yards = D.Fans(fan(0, 0) + [[at(0, 2000), at(2000, 2000)]], "cn")         # and one long track on its own
        self.assertEqual(len(yards.cells), 1)
        f = next(iter(yards.cells))
        self.assertAlmostEqual(yards.km[f], 3.2, delta=0.2)
        self.assertEqual(yards.near(*at(200, 20)), {f: yards.near(*at(200, 20))[f]})
        self.assertIsNone(yards.to_track(*at(200, 700)))

    def test_fans_close_together_are_one_depot(self):
        yards = D.Fans(fan(0, 0) + fan(600, 0) + fan(1500, 0), "cn")              # 200 m and 500 m apart
        depots = {yards.depot[f] for f in yards.cells}
        self.assertEqual(len(yards.cells), 3)
        self.assertEqual(len(depots), 2)


class LabelTest(unittest.TestCase):
    def labels(self, lines, named, table=(), g="cn"):
        found, notes = D.labels(g, lines, named, table)
        return {name: ((lon, lat), origin) for name, lon, lat, origin in found}, notes

    def test_a_ground_s_name_stands_on_its_tracks_and_an_object_inside_it_is_the_same_depot(self):
        lines = fan(0, 0)
        found, _ = self.labels(lines, [ground("测试车辆段", area(-300, -300, 1000, 640)), point("测试存车场", at(100, 10))])
        self.assertEqual(set(found), {"测试车辆段"})
        where, origin = found["测试车辆段"]
        self.assertEqual(origin, "ground")
        self.assertLess(metres(where, at(200, 17)), 60)              # on the tracks, not the middle of the area

    def test_an_area_mostly_inside_another_and_next_to_its_name_is_the_same_depot(self):
        lines = fan(0, 0)
        found, _ = self.labels(lines, [ground("测试车辆段", area(-50, -50, 500, 135)), ground("测试车辆段检修区", area(-20, -20, 300, 80))])
        self.assertEqual(set(found), {"测试车辆段"})

    def test_a_large_fan_holds_more_than_one_depot(self):
        lines = fan(0, 0, length=2000)                                  # one fan, two kilometres long
        found, _ = self.labels(lines, [ground("西头车辆段", area(-20, -20, 600, 80)), ground("东头机务段", area(1400, -20, 620, 80)),
                                       point("中间编组场", at(1000, 10))])
        self.assertEqual(set(found), {"西头车辆段", "东头机务段", "中间编组场"})

    def test_a_plain_name_gives_way_to_a_particular_one(self):
        lines = fan(0, 0)
        found, _ = self.labels(lines, [ground("上行调车场", area(-20, -20, 440, 80)), point("测试车辆段", at(300, 10))])
        self.assertEqual(set(found), {"测试车辆段"})
        found, _ = self.labels(lines, [ground("上行调车场", area(-20, -20, 440, 80))])
        self.assertEqual(set(found), {"上行调车场"})                    # where nothing more particular names the fan

    def test_one_point_object_names_a_fan_a_yard_object_first(self):
        lines = fan(0, 0)
        found, _ = self.labels(lines, [point("测试机务段", at(150, 10), "railway=workshop"), point("测试车辆段", at(390, 10), "railway=depot")])
        self.assertEqual(set(found), {"测试车辆段"})

    def test_ground_that_is_not_railway_ground_has_to_hold_the_tracks(self):
        lines = fan(0, 0)
        self.assertEqual(self.labels(lines, [ground("测试停车场", area(800, 0, 200, 200), "landuse=industrial")])[0], {})
        found, _ = self.labels(lines, [ground("测试停车场", area(-20, -20, 440, 80), "landuse=industrial")])
        self.assertEqual(set(found), {"测试停车场"})

    def test_a_point_far_from_yard_track_is_no_label(self):
        self.assertEqual(self.labels(fan(0, 0), [point("测试车辆段", at(200, 700))])[0], {})

    def test_a_metro_depot_whose_tracks_are_not_drawn_stands_by_its_line(self):
        line = [[at(-2000, 900), at(2000, 900)]]                       # a metro line drawn 200 m from the depot
        found, _ = D.labels("cn", fan(0, 0), [point("测试车辆段", at(200, 700)), point("测试机务段", at(300, 750))], (), line)
        self.assertEqual({name for name, *_ in found}, {"测试车辆段"})    # a railway's 机务段 does not stand by a metro line
        a = D.audit("cn", fan(0, 0), [feature("测试车辆段", at(200, 700))], running=line)
        self.assertEqual(a["far"], [])
        self.assertEqual(D.audit("cn", fan(0, 0), [feature("测试车辆段", at(200, 700))])["far"], ["测试车辆段"])

    def test_the_table_names_only_what_osm_does_not(self):
        lines = fan(0, 0) + fan(3000, 0)
        row = lambda name, where: {"g": "cn", "at": list(where), "n": name, "source": "https://example.org"}
        found, notes = self.labels(lines, [ground("测试车辆段", area(-20, -20, 440, 80))],
                                   [row("表里的车辆段", at(3200, 15)), row("另一个名字", at(200, 15)), row("没有这个车辆段", at(9000, 0))])
        self.assertEqual(found["表里的车辆段"][1], "table")
        self.assertNotIn("另一个名字", found)
        self.assertEqual(notes["osm_differs"], [("另一个名字", "测试车辆段")])
        self.assertEqual(notes["no_depot"], ["没有这个车辆段"])


class AuditTest(unittest.TestCase):
    def test_what_the_check_finds(self):
        lines = fan(0, 0) + fan(3000, 0)
        depots = [feature("测试车辆段", at(200, 15), "ground"), feature("测试停车场", at(250, 15)), feature("另一个停车场", at(300, 15)),
                  feature("远处车辆段", at(200, 900)), feature("联合检修库", at(3200, 15))]
        a = D.audit("cn", lines, depots, [{"g": "cn", "at": list(at(9000, 0)), "n": "x"}], metro_lines=fan(3000, 0))
        self.assertEqual(a["far"], ["远处车辆段"])
        self.assertEqual(a["doubled"], [["另一个停车场", "测试停车场"]])        # a ground's own name is not counted
        self.assertEqual(a["never"], ["联合检修库"])
        self.assertEqual(a["rows_lost"], ["x"])
        self.assertEqual(a["unnamed_metro"], [])                        # the metro fan is labelled, though by a junk name
        a = D.audit("cn", lines, depots[:3], metro_lines=fan(3000, 0))
        self.assertEqual(len(a["unnamed_metro"]), 1)

    def test_a_ground_names_both_of_its_fans(self):
        lines = fan(0, 0) + fan(800, 0)
        named = [ground("测试车辆段", area(-20, -20, 1240, 80))]
        a = D.audit("cn", lines, [feature("测试车辆段", at(200, 15), "ground")], metro_lines=lines, named=named)
        self.assertEqual(a["unnamed_metro"], [])
        self.assertEqual([row[3] for row in a["held"]], ["测试车辆段"])


class GeneratedDepotsTest(unittest.TestCase):
    """The depots files as written: no junk, no label away from the tracks, the names table used."""

    def test_china_s_fixed_cases(self):
        names = {f["properties"]["n"] for f in json.loads((ROOT / "data" / "depots.geojson").read_text())["features"]}
        there, gone = D.FIXED["cn"]
        for name in there:
            self.assertIn(name, names)
        for name in gone:
            self.assertNotIn(name, names)
        self.assertFalse([n for n in names if D.not_a_depot("cn", n)])

    def test_abroad(self):
        for g in ("jp", "kr", "uk"):
            parts = lambda f: f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiLineString" else [f["geometry"]["coordinates"]]
            lines = [co for f in json.loads((ROOT / "data" / f"{g}_yards.geojson").read_text())["features"] for co in parts(f)]
            depots = json.loads((ROOT / "data" / f"{g}_depots.geojson").read_text())["features"]
            a = D.audit(g, lines, depots, D.table_rows(g), running=D.running_lines(g, ROOT / "data"))
            for key in ("far", "doubled", "never", "rows_lost", "rows_doubled"):
                self.assertEqual(a[key], [], (g, key))
            self.assertTrue(all(f["properties"].get("g") == g and f["properties"].get("from") for f in depots), g)

    def test_every_row_of_the_names_table_has_a_source(self):
        rows = json.loads(D.TABLE.read_text())
        self.assertTrue(rows)
        for row in rows:
            self.assertIn(row["g"], ("cn", "jp", "kr", "uk"))
            self.assertTrue(row["n"] and row["source"], row)
            self.assertEqual(len(row["at"]), 2)


if __name__ == "__main__":
    unittest.main()
