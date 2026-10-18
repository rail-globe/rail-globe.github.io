import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from line_bundles import Projection, groups

PROJECT = Projection(6.86, 51.43)


def feature(name, city, xy, country='de'):
    return {'type': 'Feature', 'properties': {'g': country, 'ct': city, 'n': name,
                                             'network': 'VRR', 'rid': name, 'jk': 'urban'},
            'geometry': {'type': 'LineString', 'coordinates': [PROJECT.back(*point) for point in xy]}}


class ScopedGeographicGrouping(unittest.TestCase):
    enabled = ('鲁尔', '杜塞尔多夫')

    def test_parallel_neighbours_cross_ct_within_merge_distance(self):
        a = feature('NE12', '鲁尔', [(0, 0), (500, 0)])
        b = feature('112', '杜塞尔多夫', [(0, 21), (500, 21)])
        before = copy.deepcopy([a, b])
        result = groups([a, b], geographic_cities=self.enabled)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1], [a, b])
        self.assertIs(result[0][1][0], a)
        self.assertEqual([a, b], before)

    def test_just_outside_shared_track_threshold_stays_separate(self):
        a = feature('NE12', '鲁尔', [(0, 0), (500, 0)])
        b = feature('112', '杜塞尔多夫', [(0, 22.1), (500, 22.1)])
        self.assertEqual(len(groups([a, b], geographic_cities=self.enabled)), 2)

    def test_intersecting_bounding_boxes_are_not_geometric_proof(self):
        a = feature('a', '鲁尔', [(0, 0), (1000, 0), (1000, 1000)])
        b = feature('b', '杜塞尔多夫', [(0, 1000), (0, 900), (900, 900)])
        self.assertEqual(len(groups([a, b], geographic_cities=self.enabled)), 2)

    def test_different_countries_and_unknown_country_do_not_join(self):
        a = feature('a', '鲁尔', [(0, 0), (500, 0)])
        b = feature('b', '杜塞尔多夫', [(0, 0), (500, 0)], country='nl')
        self.assertEqual(len(groups([a, b], geographic_cities=self.enabled)), 2)
        a['properties'].pop('g')
        b['properties'].pop('g')
        self.assertEqual(len(groups([a, b], geographic_cities=self.enabled)), 2)

    def test_default_and_unenabled_ranges_preserve_legacy_groups(self):
        a = feature('a', '鲁尔', [(0, 0), (500, 0)])
        b = feature('b', '杜塞尔多夫', [(0, 0), (500, 0)])
        legacy = groups([a, b])
        self.assertEqual(len(legacy), 2)
        self.assertEqual(groups([a, b], geographic_cities=('斯图加特',)), legacy)
        # Existing same-city bounding-box batching is unchanged outside the scope.
        a['properties']['ct'] = b['properties']['ct'] = 'Other'
        self.assertEqual(groups([a, b], geographic_cities=self.enabled), groups([a, b]))

    def test_multipart_distance_uses_actual_parts(self):
        a = feature('a', '鲁尔', [(0, 0), (500, 0)])
        a['geometry'] = {'type': 'MultiLineString', 'coordinates':
                         [a['geometry']['coordinates'], [PROJECT.back(2000, 2000), PROJECT.back(2500, 2000)]]}
        b = feature('b', '杜塞尔多夫', [(0, 10), (500, 10)])
        self.assertEqual(len(groups([a, b], geographic_cities=self.enabled)), 1)


if __name__ == '__main__':
    unittest.main()
