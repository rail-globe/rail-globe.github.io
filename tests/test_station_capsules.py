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


class ShortLineTests(unittest.TestCase):
    """2026-10-19: Rotterdam Centraal's capsule listed Tram 5, whose drawn line ends 15 m short of the
    station, in the middle of the bundle: the capsule, drawn across its outermost members, missed it."""

    def setUp(self):
        self.station={'type':'Feature','properties':{'n':'Interchange','m':1,'g':'nl'},
                      'geometry':{'type':'Point','coordinates':[6,46]}}
        self.routes={'routes':{1:[('n',11,'stop')],2:[('n',12,'stop')],3:[('n',13,'stop')]},
                     'nodes':{11:({'name':'Interchange'},6,46),12:({'name':'Interchange'},6,46.00005),
                              13:({'name':'Interchange'},6.0002,46.0001)},
                     'platforms':{},'areas':{}}

    def capsule(self, lines):
        result=annotate([self.station],lines,stopping=self.routes)[0]
        return json.loads(result['properties']['cp']) if 'cp' in result['properties'] else None

    def test_the_capsule_moves_to_where_every_member_is_drawn(self):
        # C starts about 15 m east of the station, between A and B on the one side and nothing on the other
        lines=[line('A',1,[[5.999,46],[6.001,46]]),line('C',3,[[6.0002,46.0001],[6.001,46.0001]]),
               line('B',2,[[5.999,46.0002],[6.001,46.0002]])]
        cp=self.capsule(lines)
        self.assertEqual(len(cp['m']),3)
        xs={round(m['a'][0],5) for m in cp['m']}
        self.assertEqual(len(xs),1)                          # one cross line
        self.assertGreater(min(xs),6.0002)                   # past C's end, on C
        self.assertEqual(self.station['geometry']['coordinates'],[6,46])

    def test_a_member_with_no_stretch_in_common_leaves_the_capsule(self):
        # B ends at the station from the west, C starts 15 m east of it: no cross line has both
        lines=[line('A',1,[[5.999,46],[6.001,46]]),line('B',2,[[5.999,46.00005],[6,46.00005]]),
               line('C',3,[[6.0002,46.0001],[6.001,46.0001]])]
        cp=self.capsule(lines)
        self.assertEqual([m['id'] for m in cp['m']],[m for m in [json.dumps([None,None,None,None,'1','A',None,None,None],separators=(',',':')),
                                                                 json.dumps([None,None,None,None,'2','B',None,None,None],separators=(',',':'))]])

    def test_members_drawn_across_the_station_keep_their_capsule_unchanged(self):
        lines=[line('A',1,[[5.999,46],[6.001,46]]),line('B',2,[[5.999,46.0001],[6.001,46.0001]])]
        self.routes['nodes'][12]=({'name':'Interchange'},6,46.0001)
        cp=self.capsule(lines)
        self.assertEqual({round(m['a'][0],7) for m in cp['m']},{6.0})


class TwinStationTests(unittest.TestCase):
    """2026-10-19: Manchester's St Peter's Square is two same-named nodes 30 m apart, each with a capsule
    ("同名站合并成一个胶囊"); and a station far from its capsule has its name beside it ("站名挪到胶囊旁")."""

    def setUp(self):
        self.routes={'routes':{1:[('n',11,'stop')],2:[('n',12,'stop')]},
                     'nodes':{11:({'name':'Square'},6,46),12:({'name':'Square'},6,46.00005)},
                     'platforms':{},'areas':{}}
        self.lines=[line('A',1,[[5.997,46],[6.003,46]]),line('B',2,[[5.997,46.00005],[6.003,46.00005]])]

    def station(self, x, y, name='Square'):
        return {'type':'Feature','properties':{'n':name,'m':1,'g':'uk'},'geometry':{'type':'Point','coordinates':[x,y]}}

    def test_same_named_platforms_are_one_capsule_between_them(self):
        stations=[self.station(5.9998,46),self.station(6.0002,46.00005)]      # about 30 m apart
        out=annotate(stations,self.lines,stopping=self.routes)
        drawn=[f for f in out if 'cp' in f['properties']]
        self.assertEqual(len(drawn),1)
        self.assertEqual(sum(1 for f in out if f['properties'].get('hd')),1)
        members=json.loads(drawn[0]['properties']['cp'])['m']
        self.assertAlmostEqual(members[0]['a'][0],6.0,places=6)             # worked out between the two
        self.assertEqual(drawn[0]['properties'].get('lf'),2)               # its name beside the capsule, near or far
        self.assertEqual([f['geometry'] for f in out],[f['geometry'] for f in stations])
        self.assertEqual(out,annotate(out,self.lines,stopping=self.routes))  # idempotent

    def test_far_apart_or_other_lines_stay_two(self):
        far=[self.station(5.9985,46),self.station(6.0015,46.00005)]          # about 230 m apart
        self.assertEqual(sum(1 for f in annotate(far,self.lines,stopping=self.routes) if 'cp' in f['properties']),2)

    def test_a_station_far_from_its_capsule_has_its_name_beside_it(self):
        out=annotate([self.station(6,46.0004)],self.lines,stopping=self.routes)   # about 40 m north of the lines
        self.assertIn('cp',out[0]['properties'])
        self.assertEqual(out[0]['properties'].get('lf'),2)                  # trams alone: shown from the trams' zoom


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
