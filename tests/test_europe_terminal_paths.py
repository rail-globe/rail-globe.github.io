"""Pure, exact-source terminal APIs preserve unknown/default paths and real gaps."""
import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
from shapely.geometry import LineString
from shapely.ops import unary_union
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import europe_terminal_paths as ep
class TerminalTests(unittest.TestCase):
 def setUp(self):
  self.ways={11:({'railway':'tram'},[(8,47),(8.001,47)]),12:({'railway':'tram'},[(8.01,47),(8.011,47)]),13:({'railway':'tram'},[(8.011,47.0001),(8.01,47.0001)]),14:({'railway':'construction','construction':'tram'},[(8.001,47),(8.01,47)])}
  self.rels={1:({'type':'route','route':'tram','description':'native policy evidence'},[('w',11),('w',12),('w',14),('w',99)]),2:({'type':'route','route':'tram'},[('w',13)]),3:({'type':'route_master','name':'M'},[('r',1),('r',2)])}
  self.default=[LineString([(8,47),(8.011,47)])]
  self.profile={'country':'xx','network':'N','name':'S','rids':[1,2],'railway':['tram'],'required_way_ids':[11,12,13],'extra_relations':[],'fingerprint':ep.source_fingerprint((1,2),self.ways,self.rels)}
 def call(self,**kw):
  with patch.object(ep,'PROFILES',{('xx','N','S',(1,2)):self.profile}):return ep.terminal_paths(kw.get('code','xx'),kw.get('network','N'),kw.get('name','S'),kw.get('rids',(1,2)),kw.get('ways',self.ways),kw.get('relations',self.rels),self.default)
 def test_complete_per_direction_native_runs_keep_gap(self):
  out=self.call();self.assertIsNot(out,self.default);self.assertEqual(len(out),3);self.assertTrue(unary_union(out).equals(unary_union([LineString(self.ways[w][1]) for w in (11,12,13)])))
  self.assertLess(sum(g.length for g in out),.004)
 def test_unknown_and_duplicate_identity_returns_exact_default(self):
  for args in ({'code':'yy'},{'network':'N '},{'name':'Other'},{'rids':(1,)},{'rids':(1,2,4)},{'rids':(1,1,2)},{'rids':(None,)},{'rids':(1.0,2)},{'rids':(True,2)},{'rids':('01','2')}):self.assertIs(self.call(**args),self.default)
 def test_hsr_internal_tags_only_are_ignored(self):
  w=copy.deepcopy(self.ways);r=copy.deepcopy(self.rels);w[11][0]['_hsr_state']='unresolved';r[1][0]['_hsr_internal']='x';self.assertIsNot(self.call(ways=w,relations=r),self.default)
  for key,value in [('usage','tourism'),('service','siding'),('description','changed'),('_other_internal','x')]:
   w=copy.deepcopy(self.ways);w[11][0][key]=value;self.assertIs(self.call(ways=w),self.default)
 def test_original_policy_relation_tags_and_parent_tags_bound(self):
  for rid,key,value in [(1,'description','different'),(1,'usage','tourism'),(3,'name','Other')]:
   r=copy.deepcopy(self.rels);r[rid][0][key]=value;self.assertIs(self.call(relations=r),self.default)
  r=copy.deepcopy(self.rels);del r[1][0]['description'];self.assertIs(self.call(relations=r),self.default)
 def test_member_order_missing_members_new_ancestor_fail_closed(self):
  r=copy.deepcopy(self.rels);r[1][1].reverse();self.assertIs(self.call(relations=r),self.default)
  r=copy.deepcopy(self.rels);r[3][1].append(('r',4));self.assertIs(self.call(relations=r),self.default)
  r=copy.deepcopy(self.rels);r[4]=({'type':'network'},[('r',3)]);self.assertIs(self.call(relations=r),self.default)
  w=copy.deepcopy(self.ways);w[99]=({'railway':'platform'},[(8,47),(8.001,47)]);self.assertIs(self.call(ways=w),self.default)
  w=copy.deepcopy(self.ways);del w[12];self.assertIs(self.call(ways=w),self.default)
 def test_coordinate_change_and_reversal_fail_closed(self):
  w=copy.deepcopy(self.ways);w[11][1][0]=(8.000001,47);self.assertIs(self.call(ways=w),self.default)
  w=copy.deepcopy(self.ways);w[11][1].reverse();self.assertIs(self.call(ways=w),self.default)
 def test_unbacked_run_chord_fails_closed(self):
  with patch.object(ep,'runs_of',return_value=self.default):self.assertIs(self.call(),self.default)
 def test_input_and_points_not_mutated_and_repeat_stable(self):
  before=copy.deepcopy((self.ways,self.rels));a=self.call();b=self.call();self.assertEqual((self.ways,self.rels),before);self.assertEqual([g.wkb for g in a],[g.wkb for g in b])
 def test_malformed_source_returns_default(self):
  w=copy.deepcopy(self.ways);w[11]=(None,w[11][1]);self.assertIs(self.call(ways=w),self.default)
 def vitoria(self):
  rid1,rid2,wid,stop=6679948,6679966,454555501,8441145335
  ways={wid:({'railway':'tram','service':'siding'},[(0,0),(0,.001)])};rels={r:({'type':'route','route':'tram'},[('n',stop),('w',wid)]) for r in (rid1,rid2)}
  proof={'rids':[rid1,rid2],'stop_node':stop,'native_way':{'id':wid,'tags':{'service':'siding'},'nodes':[stop,4511040192]},'stop_area':{'id':10711667,'members':[['n',stop,'stop']]}}
  profile={'country':'es','network':'Euskotren Tranbia','name':'T2','rids':[rid1,rid2],'railway':['tram'],'required_way_ids':[wid],'extra_relations':[10711667],'fingerprint':ep.source_fingerprint((rid1,rid2),ways,rels,(10711667,)),'service_way_proofs':{str(wid):proof},'native_relations':{str(r):{'members':[('n',stop,'stop'),('w',wid,'')]} for r in (rid1,rid2)},'provenance':{'extract_sha256':'bound','pbf_sha256':'bound'}}
  return ways,rels,profile
 def test_only_exact_vitoria_passenger_siding_is_approved(self):
  w,r,p=self.vitoria();before=copy.deepcopy((w,r));key=('es',p['network'],p['name'],tuple(p['rids']))
  with patch.object(ep,'PROFILES',{key:p}):
   for rid in p['rids']:self.assertTrue(ep.approved_service_way('es',rid,454555501,w,r))
   for code,rid,wid in [('it',6679948,454555501),('es',1,454555501),('es',6679948,175397771),('es',6679948,583172550)]:self.assertFalse(ep.approved_service_way(code,rid,wid,w,r))
   self.assertIsNot(ep.terminal_paths(*key,w,r,self.default),self.default)
  self.assertEqual((w,r),before)
 def test_missing_or_changed_stoparea_evidence_fails_whole_profile(self):
  w,r,p=self.vitoria();key=('es',p['network'],p['name'],tuple(p['rids']))
  for mutation in ('no-proof','wrong-area','missing-stop','wrong-vertex'):
   q=copy.deepcopy(p);proof=q['service_way_proofs']['454555501']
   if mutation=='no-proof':q['service_way_proofs']={}
   elif mutation=='wrong-area':proof['stop_area']['id']=999
   elif mutation=='missing-stop':proof['stop_area']['members']=[]
   else:proof['native_way']['nodes']=[1,2]
   with patch.object(ep,'PROFILES',{key:q}):self.assertFalse(ep.approved_service_way('es',6679948,454555501,w,r));self.assertIs(ep.terminal_paths(*key,w,r,self.default),self.default)
 def test_json_member_arrays_keep_native_identity_semantics(self):
  import json
  w,r,p=self.vitoria();r={k:json.loads(json.dumps(v)) for k,v in r.items()};key=('es',p['network'],p['name'],tuple(p['rids']))
  with patch.object(ep,'PROFILES',{key:p}):self.assertTrue(ep.approved_service_way('es',6679948,454555501,w,r));self.assertIsNot(ep.terminal_paths(*key,w,r,self.default),self.default)
 def test_fractional_native_ids_cannot_be_truncated_into_approval(self):
  w,r,p=self.vitoria();key=('es',p['network'],p['name'],tuple(p['rids']))
  with patch.object(ep,'PROFILES',{key:p}):self.assertFalse(ep.approved_service_way('es',6679948.0,454555501,w,r));self.assertFalse(ep.approved_service_way('es',6679948,454555501.0,w,r))
 def test_new_live_stop_area_changes_bound_absence(self):
  w,r,p=self.vitoria();r[10711667]=({'type':'public_transport','public_transport':'stop_area'},[('n',8441145335)])
  with patch.object(ep,'PROFILES',{('es',p['network'],p['name'],tuple(p['rids'])):p}):self.assertFalse(ep.approved_service_way('es',6679948,454555501,w,r))
if __name__=='__main__':unittest.main()
