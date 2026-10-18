import math
import sys
import unittest
from pathlib import Path
from shapely.geometry import LineString,Point
from shapely.ops import unary_union
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from line_bundles import build,contract,Order,smooth_lines,SIMPLIFY


class SourceLoopTests(unittest.TestCase):
    @staticmethod
    def own(edges,key):
        return unary_union([LineString(e['co']) for e in edges if key in e['lines']])

    def assert_covered(self,source,generated,tolerance=35):
        n=max(1,math.ceil(source.length/2))
        self.assertLessEqual(max(source.interpolate(i*source.length/n).distance(generated) for i in range(n+1)),tolerance)

    def test_independent_closed_source_loop_survives(self):
        co=[(0,0),(0,200),(200,200),(200,0),(0,0)]
        g=build([(co,frozenset(['loop']))],source_bound=True)
        generated=self.own(contract(g),'loop')
        self.assert_covered(LineString(co),generated,1)
        self.assertGreater(generated.length,790)

    def test_leaving_bundle_and_returning_to_same_junction_keeps_source_course(self):
        trunk=[(-700,0),(700,0)]
        detour=[(-150,0),(0,0),(0,200),(200,200),(200,80),(0,80),(0,0),(150,0)]
        for reverse in [False,True]:
            route=list(reversed(detour)) if reverse else detour
            g=build([(trunk,frozenset(['trunk'])),(route,frozenset(['service']))],source_bound=True)
            edges=contract(g);generated=self.own(edges,'service')
            self.assert_covered(LineString(route),generated)
            self.assertLess(Point(200,200).distance(generated),1)
            self.assertTrue(any(e['u']==e['v'] and 'service' in e['lines'] and LineString(e['co']).length>60 for e in edges))
            # The actual normal smoothing code must also keep the retained loop.
            order=Order(g,edges)
            stretch=[]
            for e in edges:
                inner=list(LineString(e['co']).simplify(SIMPLIFY).coords)
                stretch.append([g.node[e['u']]]+inner[1:-1]+[g.node[e['v']]])
            drawn=smooth_lines(edges,stretch,order)
            rendered=unary_union([LineString(co) for (i,key),co in drawn.items() if key=='service'])
            self.assert_covered(LineString(route),rendered)

    def test_true_short_degenerate_closed_run_stays_discarded(self):
        trunk=[(-700,0),(700,0)]
        route=[(-150,0),(0,0),(0,24),(0,0),(150,0)]
        g=build([(trunk,frozenset(['trunk'])),(route,frozenset(['service']))],source_bound=True)
        edges=contract(g)
        self.assertFalse(any(e['u']==e['v'] and 'service' in e['lines'] for e in edges))
        self.assert_covered(LineString(trunk),self.own(edges,'trunk'),1)

    def test_closed_input_reversal_keeps_coverage(self):
        co=[(0,0),(0,200),(200,200),(200,0),(0,0)]
        a=build([(co,frozenset(['loop']))],source_bound=True)
        b=build([(co[::-1],frozenset(['loop']))],source_bound=True)
        ga=self.own(contract(a),'loop');gb=self.own(contract(b),'loop')
        self.assertLessEqual(ga.hausdorff_distance(gb),1)


if __name__=='__main__':unittest.main()
