"""Verified event removal must preserve regular layout and mixed identities."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from country import filter_urban_display
from europe_urban_policy import RET12_ROUTES


class DisplayExclusionTests(unittest.TestCase):
    def test_real_rotterdam_regular_features_and_rows_are_unchanged(self):
        source = ROOT.parent / 'reports/classification/ret12/default.geojson'
        if not source.exists():
            self.skipTest('the Rotterdam evidence lies beside the working copy, not in the repository')
        features = json.loads(source.read_text())['features']
        frozen = copy.deepcopy(features)
        rows = [(f['properties']['ct'], dict(f['properties'])) for f in features]
        expected = [f for f in features if f['properties']['n'] != 'Tram 12']
        actual, actual_rows = filter_urban_display(features, rows, RET12_ROUTES)
        self.assertEqual(features, frozen)
        self.assertEqual(actual, expected)
        self.assertTrue(all(a is b for a, b in zip(actual, expected)))
        self.assertEqual(len({f['properties']['rid'] for f in actual}), 14)
        self.assertEqual([r['rid'] for _, r in actual_rows],
                         [f['properties']['rid'] for f in actual])

    def test_mixed_unknown_and_malformed_identities_stay_visible(self):
        rows = [('x', {'rid': value}) for value in ('', '3009640,999', 'oops')]
        features = [{'properties': r, 'geometry': None} for _, r in rows]
        actual, result_rows = filter_urban_display(features, rows, RET12_ROUTES)
        self.assertEqual(actual, features)
        self.assertEqual(result_rows, rows)

    def test_empty_exclusion_is_a_noop(self):
        rows = [('x', {'rid': '3009640'})]
        features = [{'properties': rows[0][1]}]
        self.assertEqual(filter_urban_display(features, rows, set()), (features, rows))


if __name__ == '__main__':
    unittest.main()
