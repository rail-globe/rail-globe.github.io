"""Railway station capsules (2026-10-18, "铁路站也要胶囊"): a train service is put on the drawn
line its member tracks coincide with near the station, never on the nearest one; a station where
only one of the parallel lines has a calling service stays a dot (Goodmayes)."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_tiles
from station_capsules import annotate_rail, runs_on, service_lines, track_is, _rail_stop_name, _spelling

LAT = 51.5
DEG = 1 / 111320                     # a metre of latitude
EAST = 1 / (111320 * math.cos(math.radians(LAT)))


def north(metres):                   # a straight east-west line this many metres north of the station
    return [[-300 * EAST, LAT + metres * DEG], [300 * EAST, LAT + metres * DEG]]


def drawn(name, metres, off, **props):
    return {'type': 'Feature', 'properties': {'n': name, 'g': 'uk', 'jk': 'main', 'c': 'main', 'off': off, **props},
            'geometry': {'type': 'LineString', 'coordinates': north(metres)}}


def extract(services, track_name=None, legal=None):
    """services: {rid: (name, [track metres north of the station], calls here)}; track_name:
    {rid: the name tag of its tracks}; legal: {rid: the route=railway relation its tracks are in}."""
    ways, relations, routes, nodes = [], [], {}, {}
    for rid, (name, tracks, calls) in services.items():
        refs = []
        for i, metres in enumerate(tracks):
            wid = rid * 10 + i
            tags = {'railway': 'rail', **({'name': track_name[rid]} if track_name and rid in track_name else {})}
            ways.append((wid, tags, [tuple(p) for p in north(metres)]))
            refs.append(('w', wid))
            if legal and rid in legal:
                relations.append((900 + wid, {'type': 'route', 'route': 'railway', 'name': legal[rid]}, [('w', wid)]))
        relations.append((rid, {'type': 'route', 'route': 'train', 'name': name}, refs))
        if calls:
            nodes[rid * 100] = ({'name': 'Interchange', 'railway': 'stop'}, 0.0, LAT + tracks[0] * DEG)
            routes[rid] = [('n', rid * 100, 'stop')]
    return {'ways': ways, 'relations': relations,
            'stops': {'routes': routes, 'nodes': nodes, 'platforms': {}, 'areas': {}}}


STATION = {'type': 'Feature', 'properties': {'n': 'Interchange', 'g': 'uk'}, 'geometry': {'type': 'Point', 'coordinates': [0.0, LAT]}}


class RunsOnTests(unittest.TestCase):
    def setUp(self):
        self.lines = {'A': LineString([(-300, 0), (300, 0)]), 'B': LineString([(-300, 9), (300, 9)])}

    def test_the_line_under_the_tracks_not_the_nearest_to_the_station(self):
        samples = [(x, 8.5) for x in range(-150, 151, 5)]          # B's track, though A passes the station
        self.assertEqual(runs_on(samples, self.lines), {'B'})

    def test_far_or_undecided_tracks_are_no_evidence(self):
        self.assertEqual(runs_on([(x, 30) for x in range(-100, 101, 5)], self.lines), set())
        self.assertEqual(runs_on([(x, 4.5) for x in range(-100, 101, 5)], self.lines), set())
        self.assertEqual(runs_on([], self.lines), set())

    def test_one_track_with_a_guest_goes_to_the_line_named_after_the_service(self):
        lines = {'host': LineString([(-300, 0), (300, 0)]), 'guest': LineString([(-300, .5), (300, .5)])}
        samples = [(x, .2) for x in range(-100, 101, 5)]
        self.assertEqual(runs_on(samples, lines), {'host', 'guest'})
        names = {'host': '东北环线', 'guest': '北京市郊铁路S2线'}
        self.assertEqual(runs_on(samples, lines, service_name='北京市郊铁路S2线 (黄土店至延庆方向)', names=names), {'guest'})
        self.assertEqual(runs_on(samples, lines, service_name='北京市郊铁路S22线', names=names), {'host', 'guest'})

    def test_stop_names_of_a_station(self):
        self.assertEqual(_rail_stop_name('田端駅'), '田端')
        self.assertEqual(_rail_stop_name('서울역'), '서울')
        self.assertEqual(_rail_stop_name('Stratford'), 'Stratford')


class AnnotateRailTests(unittest.TestCase):
    def setUp(self):
        self.lines = [(drawn('Elizabeth line', -6, -.5, lc='#9364cc'), 'rail'), (drawn('Great Eastern Main Line', 6, .5), 'rail')]

    def test_two_parallel_lines_with_calling_services_make_a_capsule_and_keep_the_station(self):
        ex = extract({1: ('Elizabeth line: Shenfield → Paddington', [-7.5, -4.5], True),
                      2: ('Greater Anglia: Norwich → London', [4.5, 7.5], True)})
        original = copy.deepcopy(STATION)
        audit = []
        first = annotate_rail([STATION], self.lines, ex, audit=audit)
        p = first[0]['properties']
        self.assertEqual(STATION, original)
        self.assertEqual(first[0]['geometry'], original['geometry'])
        capsule = json.loads(p['cp'])
        self.assertEqual(len(capsule['m']), 2)
        self.assertEqual({m['mode'] for m in capsule['m']}, {'rail'})
        self.assertEqual(sorted(m['wc'] for m in capsule['m']), ['main', 'own'])
        self.assertEqual(sorted(json.loads(r['line'])[6] for r in p['cpe']), ['Elizabeth line', 'Great Eastern Main Line'])
        self.assertEqual(audit[0]['status'], 'capsule')
        self.assertEqual(first, annotate_rail(first, self.lines, ex))          # idempotent

    def test_goodmayes_the_fast_lines_do_not_stop_so_it_stays_a_dot(self):
        ex = extract({1: ('Elizabeth line: Shenfield → Paddington', [-7.5, -4.5], True),
                      2: ('Greater Anglia: Norwich → London', [4.5, 7.5], False)})
        self.assertNotIn('cp', annotate_rail([STATION], self.lines, ex)[0]['properties'])

    def test_a_calling_service_counts_for_its_own_tracks_only(self):
        # both services call, but both run on the Elizabeth line's tracks: one line stops here
        ex = extract({1: ('Elizabeth line: Shenfield → Paddington', [-7.5, -4.5], True),
                      2: ('Elizabeth line: Paddington → Shenfield', [-7, -5], True)})
        audit = []
        self.assertNotIn('cp', annotate_rail([STATION], self.lines, ex, audit=audit)[0]['properties'])
        self.assertEqual(audit[0]['reason'], 'one_line_stops_here')

    def test_a_metro_station_keeps_its_metro_capsule(self):
        station = copy.deepcopy(STATION)
        station['properties'].update(m=1, cp='{"v":1,"a":[0,51.5],"t":[1,51.5],"m":[]}')
        ex = extract({1: ('Elizabeth line', [-6], True), 2: ('Greater Anglia', [6], True)})
        out = annotate_rail([station], self.lines, ex, skip=lambda p: bool(p.get('m') and p.get('cp') and '"mode":' not in p['cp']))
        self.assertEqual(out[0], station)

    def test_a_track_named_for_its_line_is_that_line_wherever_it_is_drawn(self):
        # Okachimachi: the Keihin-Tohoku track lies nearer the drawn Yamanote line than its own
        lines = [(drawn('JR山手線', 0, -.5, g='jp'), 'rail'), (drawn('JR京浜東北線', 8, .5, g='jp'), 'rail')]
        ex = extract({1: ('JR山手線', [-4, 4], True), 2: ('JR京浜東北線・根岸線 各駅停車 (大宮 → 大船)', [2.5], True)},
                     track_name={1: '山手線', 2: '京浜東北線'}, legal={1: '東海道本線', 2: '東海道本線'})
        p = annotate_rail([STATION], lines, ex)[0]['properties']
        self.assertEqual(sorted(json.loads(r['line'])[6] for r in p['cpe']), ['JR京浜東北線', 'JR山手線'])

    def test_the_tracks_own_name_comes_before_its_legal_line(self):
        lines = [(drawn('JR山手線', 0, -.5, g='jp'), 'rail'), (drawn('JR東海道本線', 8, .5, g='jp'), 'rail')]
        ex = extract({1: ('JR山手線', [0], True)}, track_name={1: '山手線'}, legal={1: '東海道本線'})
        audit = []
        self.assertNotIn('cp', annotate_rail([STATION], lines, ex, audit=audit)[0]['properties'])
        self.assertEqual(audit[0]['reason'], 'one_line_stops_here')

    def test_a_guest_named_after_the_service_takes_it_from_its_host(self):
        # 黄土店: the S2 runs on 东北环线's track (its member tracks are named so) and is drawn beside it
        lines = {'h': LineString([(-300, 0), (300, 0)]), 's': LineString([(-300, .3), (300, .3)])}
        pieces = [(({_spelling('东北环线')}, set()), 300, [(x, 0) for x in range(-150, 151, 5)])]
        spelled = {'h': {_spelling('东北环线')}, 's': {_spelling('北京市郊铁路S2线')}}
        names = {'h': '东北环线', 's': '北京市郊铁路S2线'}
        self.assertEqual(set(service_lines(pieces, lines, spelled, guests={'s'}, service_name='北京市郊铁路S2线 (黄土店至延庆方向)', names=names)), {'s'})
        self.assertEqual(set(service_lines(pieces, lines, spelled, guests={'s'}, service_name='京包线普速', names=names)), {'h'})

    def test_track_names_and_company_prefixes(self):
        self.assertTrue(track_is(_spelling('Elizabeth Line'), _spelling('Elizabeth line')))
        self.assertTrue(track_is(_spelling('山手線'), _spelling('JR山手線')))
        self.assertFalse(track_is(_spelling('京成線'), _spelling('新京成線')))
        self.assertFalse(track_is(_spelling('1号线'), _spelling('11号线')))

    def test_a_metro_station_beside_its_railway_station_leaves_the_capsule_to_it(self):
        ex = extract({1: ('Elizabeth line: Shenfield → Paddington', [-7.5, -4.5], True),
                      2: ('Greater Anglia: Norwich → London', [4.5, 7.5], True)})
        metro = copy.deepcopy(STATION)
        metro['properties']['m'] = 1
        alone = annotate_rail([metro], self.lines, ex)                   # Stratford: the metro station is the railway station
        self.assertIn('cp', alone[0]['properties'])
        beside = copy.deepcopy(STATION)
        beside['geometry']['coordinates'] = [100 * EAST, LAT]
        out = annotate_rail([metro, beside], self.lines, ex)             # 上野: JR's station is beside Tokyo Metro's
        self.assertNotIn('cp', out[0]['properties'])
        self.assertIn('cp', out[1]['properties'])

    def test_railway_capsules_reach_the_station_tiles(self):
        self.assertIn('cp', build_tiles.LAYERS['stations']['keep'].split())


if __name__ == '__main__':
    unittest.main()
