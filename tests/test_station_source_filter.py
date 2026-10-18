import copy
import hashlib
import json
from pathlib import Path
import pickle
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from station_provenance import filter_station_sources


class StationSourceFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.extract_path=Path(self.temp.name)/'extract.pkl';self.ledger_path=Path(self.temp.name)/'fr.json'
        tags={'name':'Same name','station':'subway'}
        keep=({'name':'Same name','station':'subway'},2,48)
        drop=({'name':'Same name','station':'subway'},2.0001,48)
        independent=({'name':'Same name','railway':'tram_stop'},2.0002,48)
        other_mode=({'name':'Same name','station':'train'},2.0003,48)
        self.extract={'stations':[keep,drop,independent,other_mode],
                      'sources':[{'file':'france.pbf','sha256':'a'*64}]}
        node={'type':'n','id':1,'tags':{'railway':'station',**tags},'at':[2,48]}
        outline={'type':'w','id':2,'tags':{'railway':'station',**tags},'at':[2.0001,48],
                 'coords':[[1.9999,47.9999],[2.0003,47.9999],[2.0003,48.0001],[1.9999,48.0001],[1.9999,47.9999]]}
        self.ledger={'v':1,'country':'fr','pbf_source':{'file':'france.pbf','sha256':'a'*64},
                     'duplicates':[{'name':'Same name','stop_area':{'id':10,'members':[('n',1,'stop'),('w',2,'')]},
                                    'keep':{'type':'n','id':1,'extract_index':0,'station_tuple':copy.deepcopy(list(keep)),'native':node},
                                    'suppress':{'type':'w','id':2,'extract_index':1,'station_tuple':copy.deepcopy(list(drop)),'native':outline}}]}
        self.freeze()

    def freeze(self):
        self.extract_path.write_bytes(pickle.dumps(self.extract,protocol=4))
        self.ledger['extract_sha256']=hashlib.sha256(self.extract_path.read_bytes()).hexdigest()
        self.ledger_path.write_text(json.dumps(self.ledger))

    def run_filter(self):
        return filter_station_sources('fr',self.extract,self.extract_path,ledger_path=self.ledger_path)

    def test_old_tuple_only_suppresses_proven_outline_and_keeps_exact_order_and_points(self):
        original=copy.deepcopy(self.extract)
        result=self.run_filter()
        self.assertEqual(result,[self.extract['stations'][i] for i in [0,2,3]])
        self.assertEqual(self.extract,original)
        self.assertIs(result[0],self.extract['stations'][0])

    def test_wrong_extract_hash_cannot_guess(self):
        self.extract_path.write_bytes(b'changed extract')
        self.assertEqual(self.run_filter(),self.extract['stations'])

    def test_wrong_pbf_vintage_cannot_guess_even_with_rebound_extract(self):
        self.extract['sources'][0]['sha256']='b'*64;self.freeze()
        self.assertEqual(self.run_filter(),self.extract['stations'])

    def test_unknown_explicit_id_cannot_fall_back_to_old_name_and_position(self):
        self.extract['stations'][1][0].update(_osm_type='w',_osm_id=999);self.freeze()
        self.assertEqual(self.run_filter(),self.extract['stations'])

    def test_future_ids_need_revalidated_manifest_for_exact_extract(self):
        self.extract['stations'][0][0].update(_osm_type='n',_osm_id=1)
        self.extract['stations'][1][0].update(_osm_type='w',_osm_id=2)
        self.extract_path.write_bytes(pickle.dumps(self.extract,protocol=4))
        self.assertEqual(self.run_filter(),self.extract['stations'])
        self.freeze()
        self.assertEqual(self.run_filter(),[self.extract['stations'][i] for i in [0,2,3]])

    def test_missing_retained_node_preserves_outline(self):
        self.extract['stations'][0]=({'name':'Unrelated'},3,49);self.freeze()
        self.assertEqual(self.run_filter(),self.extract['stations'])

    def test_repeated_filter_is_idempotent_and_no_average_point_is_written(self):
        first=self.run_filter();self.extract['stations']=first
        self.assertEqual(first,self.run_filter())
        self.assertEqual(first[0][1:],(2,48))

    def test_manifest_geometry_and_native_area_membership_are_verified(self):
        self.ledger['duplicates'][0]['stop_area']['members']=[('n',1,'stop')]
        self.ledger_path.write_text(json.dumps(self.ledger))
        self.assertEqual(self.run_filter(),self.extract['stations'])


if __name__=='__main__':unittest.main()
