"""Antwerp source candidate stays disabled after a real endpoint regression."""
import copy,hashlib,json,pickle,sys,unittest
from pathlib import Path
from unittest.mock import patch
from shapely.geometry import LineString
from shapely.ops import unary_union
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent;OUT=BASE/'reports/terminal-paths/antwerp';sys.path.insert(0,str(ROOT/'scripts'))
import europe_terminal_paths as ep
class AntwerpTerminalTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if not (OUT/'inputs.pkl').exists():raise unittest.SkipTest('Bound read-only Antwerp replay fixture is not present')
  with (OUT/'inputs.pkl').open('rb') as h:cls.f=pickle.load(h)['be']
  cls.data=json.loads(ep.DATA.read_text());cls.p=next(p for p in cls.data['profiles'] if p['id']=='antwerp12');cls.default=[LineString([(0,0),(0,.01)])]
 def test_original_identity_parent_and_native_graph_complete(self):
  p=self.p;self.assertEqual((p['country'],p['network'],p['name'],p['rids']),('be','VVR Antwerpen','Tram 12',[11212,3419127]));self.assertEqual(p['available_parent_relation_ids'],[3419132]);self.assertEqual(len(p['required_way_ids']),12);self.assertEqual(ep.source_fingerprint(p['rids'],self.f['ways'],self.f['relations']),p['fingerprint'])
  t=json.loads((OUT/'topology.json').read_text());self.assertEqual(t['native_coordinate_binding_failures'],0);self.assertTrue(all(x['graph']['components']==1 and not x['ordered_way_endpoint_gaps'] for x in t['native_per_direction'].values()));self.assertTrue(all(n['tags']['railway']=='railway_crossing' for n in t['directions_shared_native_nodes']))
 def test_failed_profile_is_disabled_and_runtime_keeps_same_default(self):
  p=self.p;self.assertFalse(p['enabled']);self.assertFalse(p['validation']['source_geometry_checks_passed']);self.assertFalse(p['validation']['endpoint_non_regression']);self.assertIs(ep.terminal_paths('be',p['network'],p['name'],p['rids'],self.f['ways'],self.f['relations'],self.default),self.default)
 def test_independent_candidate_preserves_full_native_runs_and_source(self):
  p=copy.deepcopy(self.p);p['enabled']=True;key=('be',p['network'],p['name'],tuple(p['rids']));before=ep.source_fingerprint(p['rids'],self.f['ways'],self.f['relations'])
  with patch.object(ep,'PROFILES',{key:p}):
   out=ep.terminal_paths(*key,self.f['ways'],self.f['relations'],self.default);self.assertIsNot(out,self.default);native=unary_union([LineString(self.f['ways'][w][1]) for w in p['required_way_ids']]);self.assertTrue(unary_union(out).equals(native))
   for rid in p['rids']:
    for wid in p['required_way_ids']:self.assertFalse(ep.approved_service_way('be',rid,wid,self.f['ways'],self.f['relations']))
  self.assertEqual(before,ep.source_fingerprint(p['rids'],self.f['ways'],self.f['relations']))
 def test_changed_original_way_or_parent_fails_closed(self):
  p=copy.deepcopy(self.p);key=('be',p['network'],p['name'],tuple(p['rids']));w=copy.deepcopy(self.f['ways']);w[p['required_way_ids'][0]][0]['usage']='tourism';r=copy.deepcopy(self.f['relations']);r[3419132][0]['name']='Other'
  with patch.object(ep,'PROFILES',{key:p}):self.assertIs(ep.terminal_paths(*key,w,self.f['relations'],self.default),self.default);self.assertIs(ep.terminal_paths(*key,self.f['ways'],r,self.default),self.default)
 def test_full_city_coverage_and_endpoint_failure_are_both_recorded(self):
  d=json.loads((OUT/'antwerp-city-replay.json').read_text());self.assertEqual(d['services'],12);self.assertFalse(d['passed']);a,b=d['variants'];old={json.dumps(r['identity'],sort_keys=True):r for r in a['rows']}
  for r in b['rows']:
   prev=old[json.dumps(r['identity'],sort_keys=True)]
   for k in ('source_to_output','output_to_source'):self.assertGreaterEqual(r[k]['coverage35']+1e-6,prev[k]['coverage35'])
   per={x['rid']:x for x in prev['per_direction']}
   for x in r['per_direction']:self.assertGreaterEqual(x['source_to_output']['coverage35']+1e-6,per[x['rid']]['source_to_output']['coverage35'])
  self.assertTrue(any(x.get('node')==13793510392 and x['after']>x['before']+1 for x in d['regressions']))
  topo=json.loads((OUT/'topology.json').read_text());self.assertEqual(topo['stages']['current']['components'],2);self.assertEqual(topo['stages']['candidate']['components'],1)
 def test_legacy_bound_does_not_fix_display_disconnect(self):
  d=json.loads((OUT/'antwerp-legacy-bound-city-replay.json').read_text());self.assertTrue(d['passed']);self.assertTrue(all(not s['hook_active'] for s in d['stages']))
 def test_previously_approved_spanish_records_and_module_frozen(self):
  expected=json.loads((OUT/'frozen-spanish-profiles.json').read_text());canon=lambda p:hashlib.sha256(json.dumps(p,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest();actual={p['id']:canon(p) for p in self.data['profiles'] if p['country']=='es' and p['enabled']};self.assertEqual(actual,expected['profiles']);self.assertEqual(hashlib.sha256((ROOT/'scripts/europe_terminal_paths.py').read_bytes()).hexdigest(),expected['module_sha256'])
if __name__=='__main__':unittest.main()
