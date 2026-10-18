from pathlib import Path
import copy,json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from station_display_names import correct_generated_station_names,OLD,NEW
O=Path(__file__).resolve().parent
class DisplayNameProposal(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.proof=json.loads((O.parent/'data/europe_station_display/it.json').read_text())
  cls.stations=[dict(type='Feature',properties=dict(n=OLD,g='it',m=1),geometry=dict(type='Point',coordinates=[12.24064,45.49031]))]
 def fix(self,rows=None,code='it',proof=None,sha=None):
  return correct_generated_station_names(code,self.stations if rows is None else rows,extract_sha256=sha or self.proof['extract_sha256'],proof=proof or self.proof)
 def test_only_display_name_changes_and_all_points_stay(self):
  before=copy.deepcopy(self.stations);after=self.fix()
  self.assertEqual(before,self.stations);self.assertEqual(len(before),len(after))
  self.assertEqual(after[0]['properties']['n'],NEW)
  after[0]['properties']['n']=OLD;self.assertEqual(before,after)
 def test_wrong_hash_country_and_unknown_position_do_not_guess(self):
  self.assertEqual(self.fix(sha='wrong'),self.stations)
  self.assertEqual(self.fix(code='fr'),self.stations)
  other=copy.deepcopy(self.stations);other[0]['geometry']['coordinates'][0]+=.00001
  self.assertEqual(self.fix(other),other)
 def test_native_id_and_ref_must_be_exact(self):
  p=copy.deepcopy(self.proof);p['native_nodes'][0]['id']=1
  self.assertEqual(self.fix(proof=p),self.stations)
  p=copy.deepcopy(self.proof);p['native_nodes'][0]['tags']['ref']='6033'
  self.assertEqual(self.fix(proof=p),self.stations)
 def test_other_station_and_landmark_name_are_unchanged(self):
  other=copy.deepcopy(self.stations);other[0]['properties']['n']='Cappuccina Bembo'
  self.assertEqual(self.fix(other),other)
  other[0]['properties']['n']='Museo M9';self.assertEqual(self.fix(other),other)
 def test_rerun_is_idempotent_and_capsule_metadata_preserved(self):
  rows=copy.deepcopy(self.stations);rows[0]['properties']['cp']='original-source-bound-proof'
  after=self.fix(rows);self.assertEqual(after,self.fix(after))
  self.assertEqual(after[0]['properties']['cp'],'original-source-bound-proof')
 def test_normal_stage_computes_capsule_proof_before_display_correction(self):
  from unittest.mock import patch
  from process_europe import station_display
  seen=[]
  def annotate(rows,*args,**kwargs):
   seen.extend(f['properties']['n'] for f in rows)
   result=copy.deepcopy(rows)
   for f in result:f['properties']['cp']='source-proof'
   return result
  with patch('process_europe.annotate_capsules',side_effect=annotate):
   actual=station_display(self.stations,[],{})
  self.assertEqual(seen,[OLD]);self.assertEqual(actual[0]['properties']['n'],NEW)
  self.assertEqual(actual[0]['properties']['cp'],'source-proof')
  self.assertEqual(self.stations[0]['properties']['n'],OLD)
if __name__=='__main__':unittest.main(verbosity=2)
