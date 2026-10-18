"""Actual normal-input RET event-service boundary, never synthetic name matching."""
import copy
import pickle
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import country
from process_europe import COUNTRIES
from europe_urban_policy import (load_relations, route_exclusion, RET12_ROUTES,
                                RET12_MASTER, RET12_CONTEXT_SHA256, ret12_context_digest)

class Ret12EventPolicy(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  with (ROOT/'data/raw/extract_nl.pkl').open('rb') as stream: ex=pickle.load(stream)
  with tempfile.TemporaryDirectory() as folder, patch.object(country,'OUT',Path(folder)):
   COUNTRIES['nl'].urban_preflight(ex)
  cls.ways={i:(t,co) for i,t,co in ex['ways']}
  cls.relations=load_relations('nl',ROOT/'data/raw/extract_nl.pkl',{i:(t,m) for i,t,m in ex['relations']},ex.get('relation_tag_schema',()))
  cls.rid=3009640
 def invoke(self,code='nl',rid=None,ways=None,relations=None,tags=None,master=None):
  rid=self.rid if rid is None else rid
  relations=self.relations if relations is None else relations
  ways=self.ways if ways is None else ways
  tags=self.relations[rid][0] if tags is None else tags
  master=self.relations[RET12_MASTER][0] if master is None else master
  return route_exclusion(code,rid,tags,master,ways=ways,relations=relations)
 def test_actual_normal_context_all_four_relations(self):
  self.assertEqual(ret12_context_digest(self.ways,self.relations),RET12_CONTEXT_SHA256)
  for rid in RET12_ROUTES:self.assertEqual(self.invoke(rid=rid),'verified-feyenoord-event-service')
 def test_missing_context_keeps_legacy_call_safe(self):
  self.assertIsNone(route_exclusion('nl',self.rid,self.relations[self.rid][0],self.relations[RET12_MASTER][0]))
 def test_wrong_country_network_or_isolated_tags_never_match(self):
  self.assertIsNone(self.invoke(code='be'))
  for key,value in [('network','Stadsvervoer Amsterdam'),('name','Tram 12'),('operator','Other')]:
   tags=dict(self.relations[self.rid][0]);tags[key]=value;self.assertIsNone(self.invoke(tags=tags))
  master=dict(self.relations[RET12_MASTER][0]);master['name']='Tram 12 changed';self.assertIsNone(self.invoke(master=master))
 def test_family_member_tags_coordinates_and_parent_changes_reject(self):
  for kind in ('member','tag','future-child','new-parent','missing-direction','changed-role-schema'):
   relations=dict(self.relations)
   if kind=='member':
    t,m=relations[self.rid];relations[self.rid]=(dict(t),m[:-1])
   if kind=='tag':
    t,m=relations[5976236];t=dict(t);t['website']='changed';relations[5976236]=(t,m)
   if kind=='future-child':
    t,m=relations[RET12_MASTER];relations[RET12_MASTER]=(dict(t),m+[('r',999999)])
   if kind=='new-parent':relations[999999]=({'type':'route_master'},[('r',self.rid)])
   if kind=='missing-direction':relations.pop(5976237)
   if kind=='changed-role-schema':
    t,m=relations[self.rid];relations[self.rid]=(dict(t),[(k,n,'changed-role') for k,n in m])
   self.assertIsNone(self.invoke(relations=relations),kind)
  wid=next(n for k,n in self.relations[self.rid][1] if k=='w' and n in self.ways)
  for kind in ('coordinate','way-tag','missing-way'):
   ways=dict(self.ways);t,co=ways[wid];co=copy.deepcopy(co);t=dict(t)
   if kind=='coordinate':co[0]=(co[0][0]+.0001,co[0][1])
   if kind=='way-tag':t['service']='siding'
   ways[wid]=(t,co)
   if kind=='missing-way':ways.pop(wid)
   self.assertIsNone(self.invoke(ways=ways),kind)
 def test_other_real_rotterdam_and_amsterdam_services_preserved(self):
  checked=[]
  for rid,(t,m) in self.relations.items():
   if t.get('route')=='tram' and rid not in RET12_ROUTES:
    if t.get('network')=='Rail Rotterdam' or (t.get('network')=='Stadsvervoer Amsterdam' and t.get('ref')=='12'):
     self.assertIsNone(route_exclusion('nl',rid,t,{},ways=self.ways,relations=self.relations));checked.append(rid)
  self.assertGreaterEqual(len(checked),20)
 def test_ordinary_tram20_and_protected_s6_unchanged(self):
  for rid in (192247,192248,999):
   self.assertIsNone(route_exclusion('de',rid,{'name':'Tram 20','route':'tram'},{}))

if __name__=='__main__':unittest.main()
