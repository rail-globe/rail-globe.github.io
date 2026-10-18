import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from station_provenance import classify,display_plan,apply_display_plan,match_extract,same_name_pairs
from extract_osm import station_tags


def feature(at):
    return {'type':'Feature','properties':{'n':'Same name','m':1},'geometry':{'type':'Point','coordinates':at}}


class StationProvenanceTests(unittest.TestCase):
    def test_same_name_different_station_stays_without_native_duplicate_proof(self):
        a={'type':'n','id':1,'tags':{'railway':'station'},'at':[2,48]}
        b={'type':'n','id':2,'tags':{'railway':'station'},'at':[2.0002,48]}
        self.assertFalse(classify(a,b,[])['safe_merge'])
        self.assertFalse(classify(a,None,[])['safe_merge'])

    def test_opposite_platforms_stay_even_with_same_explicit_station_group(self):
        a={'type':'n','id':1,'tags':{'railway':'tram_stop','public_transport':'platform'},'at':[2,48]}
        b={'type':'n','id':2,'tags':{'railway':'tram_stop','public_transport':'platform'},'at':[2.0002,48]}
        area={'id':10,'members':[('n',1,'platform'),('n',2,'platform')]}
        result=classify(a,b,[area])
        self.assertEqual(result['class'],'distinct_platforms')
        self.assertFalse(result['safe_merge'])
        self.assertEqual(result['common_stop_areas'],[10])

    def test_bidirectional_class_requires_reversed_native_route_endpoints(self):
        a={'type':'n','id':1,'tags':{'railway':'tram_stop'},'route_memberships':[
            {'rid':100,'tags':{'route':'tram','ref':'T1','network':'N','from':'A','to':'B'}}]}
        b={'type':'n','id':2,'tags':{'railway':'tram_stop'},'route_memberships':[
            {'rid':101,'tags':{'route':'tram','ref':'T1','network':'N','from':'B','to':'A'}}]}
        result=classify(a,b,[])
        self.assertEqual(result['class'],'bidirectional_platforms')
        self.assertFalse(result['safe_merge'])
        self.assertEqual(result['opposite_route_pairs'],[[100,101]])
        b['route_memberships'][0]['tags']['ref']='T2'
        self.assertEqual(classify(a,b,[])['class'],'distinct_platforms')

    def test_outline_node_duplicate_requires_common_native_area_and_containment(self):
        a={'type':'n','id':1,'tags':{'railway':'station'},'at':[2,48]}
        b={'type':'w','id':2,'tags':{'railway':'station'},'at':[2.0001,48],
           'coords':[[1.9999,47.9999],[2.0003,47.9999],[2.0003,48.0001],[1.9999,48.0001],[1.9999,47.9999]]}
        area={'id':10,'members':[('n',1,'stop'),('w',2,'')]}
        self.assertFalse(classify(a,b,[])['safe_merge'])
        self.assertTrue(classify(a,b,[area])['safe_merge'])
        outside=copy.deepcopy(a);outside['at']=[3,48]
        self.assertFalse(classify(outside,b,[area])['safe_merge'])

    def test_plan_keeps_an_original_point_and_repeated_application_is_stable(self):
        fs=[feature([2,48]),feature([2.0001,48])]
        original=copy.deepcopy(fs)
        a={'type':'n','id':1,'tags':{'railway':'station'},'at':[2,48]}
        b={'type':'w','id':2,'tags':{'railway':'station'},'at':[2.0001,48],
           'coords':[[1.9999,47.9999],[2.0003,47.9999],[2.0003,48.0001],[1.9999,48.0001],[1.9999,47.9999]]}
        areas=[{'id':10,'members':[('n',1,'stop'),('w',2,'')]}]
        result=apply_display_plan(fs,display_plan(fs,{0:a,1:b},areas))
        self.assertEqual(result,[fs[0]])
        self.assertEqual(result,apply_display_plan(result,display_plan(result,{0:a},areas)))
        self.assertEqual(fs,original)

    def test_extract_match_uses_exact_generator_point_and_preserves_ambiguity(self):
        f=feature([2,48]);rows=[({'name':'Same name'},2.000004,48),({'name':'Same name'},2.000003,48),({'name':'Same name'},2.0001,48)]
        self.assertEqual(match_extract(f,rows),[0,1])
        self.assertEqual(len(same_name_pairs([f,feature([2.0002,48])])),1)

    def test_future_extract_keeps_native_id_inside_existing_station_tuple_tags(self):
        class Obj:
            id=42
            def is_way(self):return True
        tags=station_tags({'name':'Same name','station':'subway'},Obj(),('name','station'))
        self.assertEqual(tags,{'name':'Same name','station':'subway','_osm_type':'w','_osm_id':42})


if __name__=='__main__':unittest.main()
