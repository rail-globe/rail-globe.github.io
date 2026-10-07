import sys
import unittest
from pathlib import Path

from shapely.geometry import LineString
from shapely.ops import substring

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from design_speeds import SectionPaths, card_aliases, catalogue_rows, contiguous_sections, grade, line_name, split_part


def section(a, b, speed=250, **extra):
    return dict(name=a + b, endpoints=a + '~' + b, design=speed,
                design_infrastructure=speed, url='reference', **extra)


class DesignSpeeds(unittest.TestCase):
    def test_seven_bands_and_unknown(self):
        values = (None, 0, 80, 159, 160, 165, 200, 205, 250, 300, 350, 380)
        self.assertEqual([grade(v) for v in values], [None, None, 'hsrslow', 'hsrslow',
                         'hsr160', 'hsr160', 'hsr200', 'hsr200', 'hsr250', 'hsr300', 'hsr350', 'hsr400'])

    def test_physical_aliases_do_not_merge_conventional_and_hsr(self):
        self.assertEqual(line_name('京哈高铁京沈段'), line_name('京哈高速线'))
        self.assertEqual(line_name('沪蓉线（工电）'), line_name('沪蓉线'))
        self.assertNotEqual(line_name('京哈线'), line_name('京哈高速线'))

    def test_grade_change_preserves_path_and_exact_shared_endpoint(self):
        g = LineString([(0, 0), (1, 0), (1, 1)])
        fs = list(split_part(g, [(0, 1, section('a', 'b', 250)), (1, 2, section('b', 'c', 160))],
                             {'c': 'hsr350', 'n': 'line', 's': 350}))
        self.assertEqual(len(fs), 2)
        self.assertEqual(fs[0]['geometry']['coordinates'][-1], fs[1]['geometry']['coordinates'][0])
        self.assertEqual(fs[0]['properties']['c'], 'hsr250')
        self.assertEqual(fs[1]['properties']['c'], 'hsr160')
        self.assertNotIn('s', fs[0]['properties'])

    def test_conflicting_sources_leave_no_design_value(self):
        g = LineString([(0, 0), (1, 0)])
        fs = list(split_part(g, [(0, 1, section('a', 'b', 250)), (0, 1, section('a', 'b', 160))],
                             {'c': 'hsr350', 'd': 350, 'ref': 'old'}))
        self.assertNotIn('d', fs[0]['properties'])
        self.assertNotIn('ref', fs[0]['properties'])

    def test_without_a_design_value_a_fast_line_keeps_its_band_as_an_estimate(self):
        g = LineString([(0, 0), (1, 0)])
        for nominal in ('hsr350', 'hsr250', 'hsr200'):
            props = next(split_part(g, [], {'c': nominal, 'n': 'line'}))['properties']
            self.assertEqual((props['c'], props.get('e')), (nominal, 1))

    def test_without_a_design_value_any_other_line_is_conventional(self):
        g = LineString([(0, 0), (1, 0)])
        for nominal in ('main', 'branch'):
            props = next(split_part(g, [], {'c': nominal, 'n': 'line'}))['properties']
            self.assertEqual(props['c'], nominal)
            self.assertNotIn('e', props)

    def test_a_documented_stretch_is_not_an_estimate(self):
        g = LineString([(0, 0), (2, 0)])
        fs = list(split_part(g, [(0, 1, section('a', 'b', 250))], {'c': 'hsr350', 'n': 'line'}))
        self.assertEqual([(f['properties']['c'], f['properties'].get('e')) for f in fs], [('hsr250', None), ('hsr350', 1)])
        again = next(split_part(LineString([(0, 0), (1, 0)]), [(0, 1, section('a', 'b', 250))], fs[1]['properties']))
        self.assertNotIn('e', again['properties'])

    def test_a_card_without_track_name_is_found_by_its_own_title(self):
        card = dict(section('昌邑', '芝罘', 350), name='潍烟高速铁路', track_name='')
        self.assertIn(line_name('潍烟高速线'), card_aliases(card))
        stretch = dict(section('青白江', '镇江关', 200), name='川青铁路成镇段', track_name='川青铁路青黄段')
        self.assertIn(line_name('川青线'), card_aliases(stretch))
        self.assertEqual(line_name('台灣高速鐵路'), line_name('台湾高速铁路'))
        branch = dict(section('下花园北', '太子城', 250), name='京张高铁崇礼支线下太段', track_name='崇礼线')
        self.assertNotIn(line_name('京张高速线'), card_aliases(branch))       # a branch is not the main line

    def test_fast_line_is_found_under_another_word_for_fast_only_as_a_fallback(self):
        fast, slow = [section('a', 'b', 350)], [section('a', 'b', 160)]
        index = {line_name('合蚌高速线'): fast, line_name('京沪线'): slow, line_name('京沪高速线'): fast}
        self.assertEqual(catalogue_rows('合蚌客专线', index, {}), (fast, line_name('合蚌高速线')))
        self.assertEqual(catalogue_rows('京沪线', index, {}), (slow, None))          # never the high-speed line of the same cities
        self.assertEqual(catalogue_rows('京广线', index, {}), ([], None))

    def test_the_other_track_takes_the_section_it_leaves_and_rejoins(self):
        main = LineString([(0, 0), (1, 0), (2, 0), (3, 0)])
        other = LineString([(1, 0), (1.5, .2), (2, 0)])               # a second bore, apart from the first
        spur = LineString([(2.5, 0), (2.5, .5)])                      # leaves and does not come back
        paths = SectionPaths([main, other, spur], {'a': [(0, 0)], 'b': [(3, 0)]}, {'a', 'b'})
        card = section('a', 'b', 350)
        spans = {}
        for i, x, y in paths.between('a', 'b'):
            spans.setdefault(i, []).append((x, y, card))
        more = paths.other_tracks(spans)
        self.assertEqual(set(more), {1})
        self.assertAlmostEqual(sum(y - x for x, y, _ in more[1]), other.length)

    def test_boundary_beyond_the_end_of_the_line_is_the_end_of_the_line(self):
        line = [LineString([(0, 0), (1, 0)])]
        points = {'a': [(0, 0)], 'terminus': [(1.1, 0.02)], 'beside': [(.5, .1)]}
        paths = SectionPaths(line, points, {'a', 'terminus', 'beside'})
        self.assertIsNotNone(paths.between('a', 'terminus'))
        self.assertEqual(paths.snapped, ['terminus'])
        self.assertIsNone(paths.between('a', 'beside'))          # off the middle of the line: not on it

    def test_missing_boundary_is_not_replaced_by_nearby_station(self):
        paths = SectionPaths([LineString([(0, 0), (1, 0)])], {'a': [(0, 0)], 'b': [(1, 0)]}, {'a', 'b线路所'})
        self.assertIsNone(paths.between('a', 'b线路所'))

    def test_station_path_includes_junction_in_middle_of_piece(self):
        paths = SectionPaths([LineString([(0, 0), (1, 0)]), LineString([(.5, 0), (.5, .5)])],
                             {'a': [(0, 0)], 'b': [(.5, .5)]}, {'a', 'b'})
        path = paths.between('a', 'b')
        self.assertEqual({span[0] for span in path}, {0, 1})

    def test_reprocessing_split_geometry_does_not_disconnect_station_anchors(self):
        g = LineString([(114.398727, 30.210067), (115.323465, 31.338178)])
        for count in range(2, 16):
            ds = [i * g.length / count for i in range(count + 1)]
            pieces = [substring(g, a, b) for a, b in zip(ds, ds[1:])]
            points = {'a': [list(g.coords[0])], 'b': [list(g.coords[-1])]}
            paths = SectionPaths(pieces, points, {'a', 'b'})
            self.assertIsNotNone(paths.between('a', 'b'))

    def test_redundant_same_grade_boundary_can_be_removed(self):
        rows = contiguous_sections([section('a', 'missing', 350), section('missing', 'b', 350)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['endpoints'], 'a~b')

    def test_scope_caveats_and_missing_values_stop_merging(self):
        rows = contiguous_sections([section('a', 'b', 350), section('b', 'c', 350, requires_review=True)])
        self.assertEqual(len(rows), 2)

    def test_same_value_with_different_design_basis_stays_separate(self):
        a, b = section('a', 'b', 160), section('b', 'c', 160)
        a['design_infrastructure'] = None
        a['design_track'] = 160
        self.assertEqual(len(contiguous_sections([a, b])), 2)


if __name__ == '__main__':
    unittest.main()
