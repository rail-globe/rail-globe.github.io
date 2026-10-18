import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from europe_urban_colours import colour_for, match_colour, match_source, sources


class UrbanColourIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = sources()
        cls.new = [r for r in cls.records if r.get('map_sha256')]

    def test_existing_five_records_remain_in_order(self):
        self.assertEqual([r['n'] for r in self.records[:5]],
                         ['Tranvía Línea 1', 'Tranvía Línea 2', 'Monorraíl T4',
                          'EP-Express / Monorail-Bahn', 'Métro Ligne 2'])
        self.assertEqual(self.records[0]['colour'], '#de010b')
        self.assertEqual(self.records[1]['colour'], '#032b73')

    def test_every_new_colour_requires_all_four_identity_fields(self):
        self.assertGreaterEqual(len(self.new), 41)
        for entry in self.new:
            args = (entry['g'], entry['network'], entry['n'], entry['osm_relations'])
            self.assertEqual(colour_for(*args), entry['colour'])
            self.assertIsNone(colour_for('wrong-country', *args[1:]))
            self.assertIsNone(colour_for(args[0], 'wrong-network', *args[2:]))
            self.assertIsNone(colour_for(*args[:2], 'wrong-name', args[3]))
            self.assertIsNone(colour_for(*args[:3], [999999999999]))
            self.assertIsNone(colour_for(*args[:3], args[3] + [999999999999]))
            self.assertIsNone(colour_for(*args[:3], []))

    def test_route_callback_preserves_unmatched_key(self):
        key = ('STIBM', 'Tram 31/', '#123456')
        self.assertEqual(match_colour('it', key, 3150546), key)
        entry = self.new[0]
        key = (entry['network'], entry['n'], '#123456')
        self.assertEqual(match_colour(entry['g'], key, entry['osm_relations'][0]),
                         (*key[:2], entry['colour']))

    def test_same_colour_does_not_merge_source_identities(self):
        two = next(r for r in self.new if r['g'] == 'ch' and r['n'] == 'Tram 2')
        fifteen = next(r for r in self.new if r['g'] == 'ch' and r['n'] == 'Tram 15')
        self.assertEqual(two['colour'], fifteen['colour'])
        self.assertIsNone(colour_for('ch', 'ZVV', 'Tram 2', fifteen['osm_relations']))

    def test_operator_uniform_milan_colour_is_retained(self):
        milan = [r for r in self.new if r['g'] == 'it']
        self.assertEqual(len(milan), 17)
        self.assertEqual({r['colour'] for r in milan}, {'#00abe5'})
        self.assertTrue(all('tram mode' in r['note'] for r in milan))

    def test_evidence_metadata_and_native_id_types(self):
        for entry in self.new:
            self.assertEqual(len(entry['map_sha256']), 64)
            self.assertEqual(entry['map_page'], 1)
            self.assertTrue(entry['downloaded_at'])
            self.assertEqual(entry['evidence']['source_sha256'], entry['map_sha256'])
            evidence = entry['evidence']
            if 'exact_colour_pixels' in evidence:
                self.assertGreater(evidence['exact_colour_pixels'], 10)
            else:
                self.assertIn('vector', evidence['method'])
                self.assertEqual(len(evidence['clip_pdf_points']), 4)
                self.assertEqual(evidence['colour'], entry['colour'])
                self.assertTrue(evidence['crop'].endswith('.png'))
            self.assertTrue(all(type(rid) is int for rid in entry['osm_relations']))

    def test_conflicting_official_colours_fail(self):
        entry = self.new[0]
        conflict = {**entry, 'colour': '#123456'}
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            colour_for(entry['g'], entry['network'], entry['n'], entry['osm_relations'], [entry, conflict])

    def test_string_and_boolean_ids_cannot_match(self):
        entry = self.new[0]
        with self.assertRaises(TypeError):
            colour_for(entry['g'], entry['network'], entry['n'], str(entry['osm_relations'][0]))
        self.assertIsNone(colour_for(entry['g'], entry['network'], entry['n'], [True]))


if __name__ == '__main__':
    unittest.main()
