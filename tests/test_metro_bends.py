"""Fixed-distance checks and source repairs must change the path, not the sampling."""
import math
import sys
import unittest
from pathlib import Path

import numpy as np
from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from check_bends import scan
from metro_bends import refit, restore, trim_unowned_loop, junctions, network_path


def lonlat(co):
    return [(116+x/(111320*math.cos(math.radians(40))), 40+y/110574) for x,y in co]


class MetroBendsTest(unittest.TestCase):
    def test_network_path_can_choose_the_other_parallel_track(self):
        from shapely.geometry import Point
        tracks=[LineString([(0,0),(1000,0)]),LineString([(0,10),(1000,10)])]
        path=network_path(Point(100,3),Point(900,7),tracks)
        self.assertIsNotNone(path)
        self.assertAlmostEqual(path.length,800)
        self.assertEqual(path.coords[0][1],path.coords[-1][1])

    def test_network_path_does_not_connect_disconnected_source_ways(self):
        from shapely.geometry import Point
        tracks=[LineString([(0,0),(200,0)]),LineString([(300,0),(1000,0)])]
        self.assertIsNone(network_path(Point(100,0),Point(900,0),tracks))

    def test_only_source_connections_are_protected_as_junctions(self):
        tracks=[[(0,0),(1,0),(2,0)],[(1,0),(1,1)],[(2,0),(3,0)]]
        self.assertEqual(junctions(tracks),[(1,0)])
    def test_adding_samples_cannot_hide_a_dogleg(self):
        g = LineString(lonlat([(0,0),(100,0),(130,30),(160,0),(300,0)]))
        a, b = scan(g.coords), scan(g.segmentize(.000001).coords)
        self.assertTrue(any(r['reverse_bend'] for r in a))
        self.assertEqual(len(a), len(b))
        self.assertAlmostEqual(max(abs(r['turn_degrees']) for r in a),
                               max(abs(r['turn_degrees']) for r in b), places=5)

    def test_source_restoration_removes_a_wrong_detour(self):
        g = LineString(lonlat([(0,0),(450,0),(500,0),(470,20),(550,0),(1000,0)]))
        tracks = [lonlat([(0,0),(1000,0)])]
        fixed, report = restore([g], tracks)
        self.assertTrue(report)
        self.assertLess(fixed[0].length, g.length)
        self.assertFalse(scan(fixed[0].coords))
        self.assertEqual(fixed[0].coords[0], g.coords[0])
        self.assertEqual(fixed[0].coords[-1], g.coords[-1])

    def test_branch_connection_prevents_replacing_its_bend(self):
        g = LineString(lonlat([(0,0),(450,0),(500,0),(470,20),(550,0),(1000,0)]))
        fixed, report = restore([g], [lonlat([(0,0),(1000,0)])], protected=lonlat([(470,20)]))
        self.assertFalse(report)
        self.assertEqual(list(fixed[0].coords), list(g.coords))

    def test_source_repair_retains_a_branch_on_the_correct_source_path(self):
        co=lonlat([(0,0),(450,0),(500,0),(470,20),(550,0),(1000,0)])
        fixed,report=restore([LineString(co)],[lonlat([(0,0),(1000,0)])],protected=[co[2]])
        self.assertTrue(report)
        self.assertIn(co[2],list(fixed[0].coords))

    def test_actual_small_radius_light_rail_is_retained(self):
        co = lonlat([(25*math.cos(t),25*math.sin(t)) for t in np.linspace(0,math.pi,40)])
        fixed, report = restore([LineString(co)], [co])
        self.assertFalse(report)
        self.assertEqual(list(fixed[0].coords), co)

    def test_small_closed_light_rail_loop_is_retained(self):
        co=lonlat([(25*math.cos(t),25*math.sin(t)) for t in np.linspace(0,2*math.pi,60)])
        co[-1]=co[0]
        fixed,report=restore([LineString(co)],[co])
        self.assertFalse(report)
        self.assertEqual(list(fixed[0].coords),co)

    def test_verified_refit_is_bounded_and_preserves_station_alignment(self):
        g = LineString(lonlat([(-600,0),(-100,0),(0,30),(40,0),(600,0)]))
        fixed = refit(g, lonlat([(0,30)])[0], radius=350, maximum=35, anchors=lonlat([(300,0)]))
        self.assertIsNotNone(fixed)
        self.assertGreaterEqual(fixed[1]['minimum_cubic_radius_m'],350)
        self.assertLessEqual(fixed[1]['maximum_shift_m'],35)
        self.assertFalse(scan(fixed[0].coords))
        self.assertEqual(fixed[0].coords[0],g.coords[0])
        self.assertEqual(fixed[0].coords[-1],g.coords[-1])

    def test_refit_does_not_relax_shift_limit_to_force_a_pass(self):
        g = LineString(lonlat([(-600,0),(-100,0),(0,50),(40,0),(600,0)]))
        self.assertIsNone(refit(g,lonlat([(0,50)])[0],radius=350,maximum=1))

    def test_stationless_loop_outside_route_relation_keeps_its_approach(self):
        co=lonlat([(0,0),(500,0),(500,400),(700,400),(700,0),(500,0)])
        kept, report=trim_unowned_loop(co,[])
        self.assertIsNotNone(report)
        self.assertEqual(kept,co[:2])
        self.assertEqual(trim_unowned_loop(co[::-1],[])[0],co[:2][::-1])

    def test_loop_with_a_passenger_station_is_not_removed(self):
        co=lonlat([(0,0),(500,0),(500,400),(700,400),(700,0),(500,0)])
        kept,report=trim_unowned_loop(co,lonlat([(600,400)]))
        self.assertIsNone(report)
        self.assertEqual(kept,co)
