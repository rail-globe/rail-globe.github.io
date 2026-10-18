import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from station_capsules import annotate
import build_tiles


def line(name,rid,coords,off=0,**props):
    return {'type':'Feature','properties':{'n':name,'rid':str(rid),'off':off,'jk':'urban',**props},
            'geometry':{'type':'LineString','coordinates':coords}}


class StationCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.station={'type':'Feature','properties':{'n':'Interchange','m':1,'g':'ch'},
                      'geometry':{'type':'Point','coordinates':[6,46]}}
        self.routes={'routes':{1:[('n',11,'stop')],2:[('n',12,'stop')]},
                     'nodes':{11:({'name':'Interchange'},6,46),12:({'name':'Interchange'},6,46)},
                     'platforms':{},'areas':{}}
        self.lines=[line('A',1,[[5.999,46],[6.001,46]],-.5,bn=2),line('B',2,[[5.999,46],[6.001,46]],.5,bn=2)]

    def test_shared_lines_source_calls_and_idempotence_leave_authority_untouched(self):
        original=copy.deepcopy(self.station)
        first=annotate([self.station],self.lines,stopping=self.routes)
        self.assertIn('cp',first[0]['properties'])
        self.assertEqual(self.station,original)
        self.assertEqual(first[0]['geometry'],original['geometry'])
        self.assertEqual(first,annotate(first,self.lines,stopping=self.routes))

    def test_nearby_noncalling_line_does_not_make_a_capsule(self):
        self.routes['routes'].pop(2)
        self.assertNotIn('cp',annotate([self.station],self.lines,stopping=self.routes)[0]['properties'])
        self.assertNotIn('cp',annotate([self.station],self.lines)[0]['properties'])

    def test_independent_parallel_tracks_work_without_bn_and_keep_native_anchors(self):
        self.lines=[line('A',1,[[5.999,46],[6.001,46]]),line('B',2,[[5.999,46.0001],[6.001,46.0001]])]
        self.routes['nodes'][12]=({'name':'Interchange'},6,46.0001)
        result=annotate([self.station],self.lines,stopping=self.routes)[0]
        members=json.loads(result['properties']['cp'])['m']
        self.assertNotEqual(members[0]['a'],members[1]['a'])
        self.assertEqual(result['geometry'],self.station['geometry'])

    def test_crossing_routes_and_same_name_distant_station_do_not_join(self):
        self.lines[1]=line('B',2,[[6,45.999],[6,46.001]],.5,bn=2)
        self.assertNotIn('cp',annotate([self.station],self.lines,stopping=self.routes)[0]['properties'])
        self.lines[1]=line('B',2,[[5.999,46],[6.001,46]],.5,bn=2)
        self.routes['nodes'][12]=({'name':'Interchange'},6.01,46)
        self.assertNotIn('cp',annotate([self.station],self.lines,stopping=self.routes)[0]['properties'])

    def test_reversed_geometry_signed_seats_still_binds_two_services(self):
        self.lines[1]['geometry']['coordinates'].reverse()
        self.lines[1]['properties']['off']=-.5
        result=annotate([self.station],self.lines,stopping=self.routes)[0]
        self.assertIn('cp',result['properties'])

    def test_tile_input_and_station_list_keep_cp_without_audit_provenance(self):
        f=annotate([self.station],self.lines,stopping=self.routes)[0]
        with patch.object(build_tiles,'features',side_effect=lambda layer,country:[f] if layer=='metro-stations' else []):
            text,_=build_tiles.tippecanoe_input('ch')
        row=json.loads(text)
        self.assertEqual(row['properties']['cp'],f['properties']['cp'])
        self.assertNotIn('cpe',row['properties'])


class RouteMasterTests(unittest.TestCase):
    """2026-10-18: Manchester's Metrolink lines are drawn under their route masters' names and
    London's trams under the masters' names without the network; their stops had no capsule."""

    def test_a_line_named_after_its_route_master_is_the_masters_routes(self):
        from station_capsules import route_ids
        relations = [
            (10, {'type': 'route_master', 'route_master': 'tram', 'name': 'Metrolink: Altrincham to/from Piccadilly'}, [('r', 1), ('r', 2)]),
            (1, {'type': 'route', 'route': 'tram', 'name': 'Metrolink: Piccadilly => Altrincham'}, []),
            (2, {'type': 'route', 'route': 'tram', 'name': 'Metrolink: Altrincham => Piccadilly'}, []),
            (20, {'type': 'route_master', 'route_master': 'tram', 'name': 'London Trams: Wimbledon - Elmers End'}, [('r', 3)]),
            (30, {'type': 'route_master', 'route_master': 'train', 'name': 'Wimbledon - Elmers End'}, [('r', 4)]),
        ]
        self.assertEqual(route_ids({'n': 'Metrolink: Altrincham to/from Piccadilly'}, relations), {1, 2})
        self.assertEqual(route_ids({'n': 'Wimbledon - Elmers End'}, relations), {3})
        self.assertEqual(route_ids({'n': 'Altrincham'}, relations), set())


class GermanModePrefixTests(unittest.TestCase):
    """2026-10-18: Berlin's S-Bahn stations are named with their modes in front; their routes call
    at the same stop without them, and the capsule needs both names to agree."""

    def test_mode_prefix_is_not_part_of_the_stop_name(self):
        from station_capsules import _stop_name
        self.assertEqual(_stop_name("S Anhalter Bahnhof"), _stop_name("Anhalter Bahnhof"))
        self.assertEqual(_stop_name("S+U Friedrichstraße"), _stop_name("Friedrichstraße"))
        self.assertEqual(_stop_name("U Spittelmarkt"), _stop_name("Spittelmarkt"))
        self.assertNotEqual(_stop_name("Sonnenallee"), _stop_name("onnenallee"))


if __name__ == '__main__':
    unittest.main()
