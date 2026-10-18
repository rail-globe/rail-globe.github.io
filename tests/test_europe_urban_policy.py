import pickle
import sys
import unittest
import tempfile
import json
from unittest.mock import patch
from pathlib import Path
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from europe_urban_policy import (nearest_city, policy, route_exclusion, load_relations, tourist)
import europe_urban_policy
from process_jp import km


class PolicyBoundaries(unittest.TestCase):
    def decide(self, urban, rail=10, current='urban', code='fr', ids=(1,)):
        ways = {1: ({'railway': 'light_rail'}, []), 2: ({'railway': 'rail'}, [])}
        return policy(code, [1, 2], ways, {1: urban, 2: rail}, ids, {}, current)

    def test_exact_threshold_and_mixed_tram_train(self):
        self.assertFalse(self.decide(.499999)['keep'])
        self.assertTrue(self.decide(.5)['keep'])
        self.assertTrue(self.decide(.6, rail=100)['keep'])

    def test_known_s6_boundary_does_not_relax_other_lines(self):
        self.assertTrue(self.decide(.49, code='de', ids=(192247,))['keep'])
        self.assertFalse(self.decide(.49, code='de', ids=(192249,))['keep'])

    def test_master_train_and_names_are_not_filters(self):
        self.assertIsNone(route_exclusion('de', 999, {'name': 'Museum Zoo Express'}, {'route_master': 'train'}))
        self.assertFalse(tourist({'tourism': 'no', 'heritage': 'no'}))

    def test_nearest_city_independent_of_order_and_outside(self):
        cities = [('Far', 1, 0, 2), ('Near', .1, 0, 2)]
        self.assertEqual(nearest_city(cities, Point(0, 0), 'Other'), 'Near')
        self.assertEqual(nearest_city(cities[::-1], Point(0, 0), 'Other'), 'Near')
        self.assertEqual(nearest_city(cities, Point(10, 10), 'Other'), 'Other')

    def test_subway_rule_unique_ways_and_exact_ten_percent(self):
        ways = {1: ({'railway': 'subway'}, []), 2: ({'railway': 'light_rail'}, [])}
        result = policy('de', [1, 1, 2], ways, {1: 1, 2: 9}, [], {}, 'subway')
        self.assertEqual(result['jk'], 'subway')
        result = policy('de', [1, 2], ways, {1: .99, 2: 9.01}, [], {}, 'subway')
        self.assertEqual(result['jk'], 'urban')

    def test_no_partial_heritage_track_exclusion(self):
        ways = {1: ({'railway': 'tram', 'usage': 'tourism'}, []), 2: ({'railway': 'tram'}, [])}
        self.assertTrue(policy('de', [1, 2], ways, {1: 1, 2: 9}, [], {}, 'urban')['keep'])

    def test_missing_source_supplement_is_unknown_and_fails(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(europe_urban_policy, 'ROOT', Path(directory)):
            with self.assertRaisesRegex(ValueError, 'bound relation-policy'):
                load_relations('de', Path(directory)/'extract.pkl', {1: ({}, [])})

    def test_wrong_extract_binding_and_incomplete_scan_fail(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(europe_urban_policy, 'ROOT', Path(directory)):
            extract = Path(directory)/'extract.pkl'
            extract.write_bytes(b'bounded-test-input')
            supplement = Path(directory)/'data/europe_relation_tags/de.json'
            supplement.parent.mkdir(parents=True)
            supplement.write_text(json.dumps({'extract_sha256': 'wrong', 'relations': {}}))
            with self.assertRaisesRegex(ValueError, 'another extract'):
                load_relations('de', extract, {1: ({}, [])})
            supplement.write_text(json.dumps({'extract_sha256': europe_urban_policy.sha256(extract), 'relations': {}}))
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                load_relations('de', extract, {1: ({}, [])})


class NativeSourceRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        file_path = ROOT / 'data/raw/extract_de.pkl'
        with file_path.open('rb') as stream:
            ex = pickle.load(stream)
        cls.ways = {wid: (tags, co) for wid, tags, co in ex['ways']}
        cls.relations = load_relations('de', file_path, {rid: (tags, members) for rid, tags, members in ex['relations']})

    def test_real_s6_retained_with_native_lengths(self):
        ids = (192247, 192248)
        wids = {wid for rid in ids for kind, wid in self.relations[rid][1]
                if kind == 'w' and wid in self.ways and not self.ways[wid][0].get('service')}
        lengths = {wid: km(self.ways[wid][1]) for wid in wids}
        result = policy('de', wids, self.ways, lengths, ids, self.relations, 'urban')
        self.assertTrue(result['keep'])
        self.assertAlmostEqual(result['urban_track_km'], .6488566616547601)

    def test_actual_stuttgart_tourism_missing_in_old_extract_is_recovered(self):
        tags = self.relations[1317322][0]
        self.assertEqual(tags['service'], 'tourism')
        self.assertEqual(route_exclusion('de', 1317322, tags, {}), 'relation-tourism-heritage')

    def test_event_identites_do_not_remove_regular_tram20(self):
        self.assertEqual(route_exclusion('de', 397326, self.relations[397326][0], {}), 'event-service')
        self.assertEqual(self.relations[2101137][0]['ref'], '20')
        self.assertIsNone(route_exclusion('de', 2101137, self.relations[2101137][0], {}))


if __name__ == '__main__':
    unittest.main()
