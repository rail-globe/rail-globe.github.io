"""Source-safe legacy bundling preserves native short pieces without expanding scope."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from shapely.geometry import LineString
from shapely.ops import unary_union
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import line_bundles as lb

class SourceSafetyTests(unittest.TestCase):
    def own(self,graph,key):
        return unary_union([LineString(e['co']) for e in lb.contract(graph) if key in e['lines']])

    def test_isolated_native_short_piece_survives_in_both_directions(self):
        trunk=[(200,200),(1200,200)]
        native=[(0,0),(23.387,0)]
        for co in (native,native[::-1]):
            g=lb.build([(trunk,frozenset(['other'])),(co,frozenset(['service']))],source_bound=True)
            own=self.own(g,'service')
            self.assertLess(own.hausdorff_distance(LineString(native)),1e-9)
            self.assertAlmostEqual(own.length,23.387)
            self.assertFalse(any('other' in e['lines'] and 'service' in e['lines'] for e in g.edge.values()))

    def test_default_short_piece_behavior_is_unchanged(self):
        g=lb.build([([(0,0),(23.387,0)],frozenset(['service']))])
        self.assertTrue(self.own(g,'service').is_empty)

    def test_a_short_junction_edge_still_closes_in_bounded_mode(self):
        g=lb.Network(source_bound=True)
        a=g.new_node((0,0));b=g.new_node((10,0));c=g.new_node((200,0))
        g.new_edge([(0,0),(10,0)],a,b,['service'])
        g.new_edge([(10,0),(200,0)],b,c,['service'])
        lb.close_short(g)
        self.assertEqual(len(g.edge),1)
        self.assertLess(self.own(g,'service').distance(LineString([(10,0),(200,0)])),1e-9)

    def feature(self,n,city,y=0):
        return {'type':'Feature','properties':{'n':n,'rid':n,'network':'N','ct':city,'g':'test','jk':'urban'},
                'geometry':{'type':'LineString','coordinates':[[0,y],[.002,y]]}}

    def test_public_entry_scope_is_explicit_and_default_remains_legacy(self):
        fs=[self.feature('1','Chosen'),self.feature('2','Other',.1)]
        for selected,expected in [((),[False,False]),(('Chosen',),[True,False])]:
            with patch.object(lb,'build',wraps=lb.build) as build:
                result=lb.apply(fs,'test',True,source_bound_cities=selected)
            by_city={next(iter(call.args[0][0][1])).split('|')[1]:call.kwargs['source_bound'] for call in build.call_args_list}
            self.assertEqual(by_city,{'1':expected[0],'2':expected[1]})
            self.assertEqual({(f['properties']['n'],f['properties']['rid'],f['properties']['network']) for f in result},{('1','1','N'),('2','2','N')})
            self.assertTrue(all('op' not in f['properties'] for f in result))

    def test_mixed_geographic_batch_requires_all_original_cities_selected(self):
        fs=[self.feature('1','Chosen'),self.feature('2','Other')]
        for selected,expected in [(('Chosen',),False),(('Chosen','Other'),True)]:
            with patch.object(lb,'build',wraps=lb.build) as build:
                lb.apply(fs,'test',True,geographic_cities=('Chosen','Other'),source_bound_cities=selected)
            self.assertEqual(len(build.call_args_list),1)
            self.assertEqual(build.call_args.kwargs['source_bound'],expected)

    def test_shared_fallback_city_needs_complete_exact_service_batch(self):
        fs=[self.feature('1','Fallback'),self.feature('2','Fallback')]
        own=('test','N','1','1');other=('test','N','2','2')
        for selected,expected in [((),False),((own,),False),((own,other),True),((('wrong','N','1','1'),other),False)]:
            with patch.object(lb,'build',wraps=lb.build) as build:
                lb.apply(fs,'test',True,source_bound_identities=selected)
            self.assertEqual(build.call_args.kwargs['source_bound'],expected)
        fs.append(self.feature('3','Fallback',.1))
        with patch.object(lb,'build',wraps=lb.build) as build:
            lb.apply(fs,'test',True,source_bound_identities=(own,other))
        self.assertEqual([c.kwargs['source_bound'] for c in build.call_args_list],[True,False])

if __name__=='__main__':unittest.main()
