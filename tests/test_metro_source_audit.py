import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from metro_source_audit import audit

def feature(rid,coordinates):
    return dict(type='Feature',properties=dict(g='test',network='X',n='A',rid=str(rid),ct='City',jk='urban'),
                geometry=dict(type='LineString',coordinates=coordinates))

class OwnServiceSource(unittest.TestCase):
    def setUp(self):
        self.a=[(0.,0.),(.01,0.)]
        self.b=[(0.,.002),(.01,.002)]
        self.extract=dict(ways=[(1,{'railway':'tram'},self.a),(2,{'railway':'tram'},self.b)],
                          relations=[(10,{},[('w',1)]),(20,{},[('w',2)])])
    def test_a_real_track_of_another_service_is_not_source_proof(self):
        row=audit([feature(10,self.b)],self.extract)['rows'][0]
        self.assertEqual(row['status'],'review_candidate')
        self.assertEqual(row['display_to_source']['coverage'],0)
    def test_exact_service_and_near_direction_track_are_preserved(self):
        self.assertEqual(audit([feature(10,self.a)],self.extract)['rows'][0]['status'],'within_retained_source_tolerance')
        nearby=[(0.,.0001),(.01,.0001)]
        self.assertEqual(audit([feature(10,nearby)],self.extract)['rows'][0]['status'],'within_retained_source_tolerance')
    def test_missing_identity_is_explicit_not_a_pass(self):
        row=audit([feature(99,self.a)],self.extract)['rows'][0]
        self.assertEqual(row['status'],'insufficient_relation_source')
        self.assertNotIn('source_to_display',row)
    def test_auditor_uses_the_same_explicit_passenger_track_exception(self):
        leg=[(.01,0.),(.011,0.)]
        self.extract['ways'].append((3,{'railway':'tram','service':'siding'},leg))
        self.extract['relations'][0][2].append(('w',3))
        display=[feature(10,self.a+leg[1:])]
        self.assertEqual(audit(display,self.extract)['rows'][0]['status'],'review_candidate')
        allowed=lambda code,rid,wid,ways,relations:(code,rid,wid)==('test',10,3)
        self.assertEqual(audit(display,self.extract,approved_service_way=allowed)['rows'][0]['status'],
                         'within_retained_source_tolerance')
