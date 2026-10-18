"""Exercise the public bundle entry and shared branch-centre contract."""
from pathlib import Path
import sys
import unittest
import math
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import line_bundles as lb
from endpoint_bundles import shared_centres
from endpoint_order import EndpointOrder, line_key
from endpoint_profiles import offset_profiles
from continuous_offset import value_at

class EndpointEntryTests(unittest.TestCase):
    def test_real_public_entry_emits_profiles_and_keeps_untouched_feature(self):
        def feature(n,rid,coords,kind='urban'):
            return {'type':'Feature','properties':{'n':n,'rid':rid,'network':'N','ct':'Test','jk':kind,'col':'#fff'},
                    'geometry':{'type':'LineString','coordinates':coords}}
        a=feature('A','1',[[-.002,0],[.002,0]])
        b=feature('B','2',[[-.002,0],[.002,0]])
        c=feature('C','3',[[-.002,0],[0,0],[0,.002]])
        untouched=feature('Metro','4',[[.1,0],[.2,0]],'subway')
        source={line_key(f['properties']):{'rids':[int(f['properties']['rid'])],
                 'routes':[{'chunks':[f['geometry']['coordinates']]}]} for f in [a,b,c]}
        audit=[]
        result=lb.apply([a,b,c,untouched],'test',True,source=source,endpoint_cities=('Test',),endpoint_audit=audit)
        self.assertIs(result[0],untouched)
        self.assertEqual({line_key(f['properties']) for f in result[1:]},set(source))
        self.assertTrue(all('op' in f['properties'] for f in result[1:]))
        self.assertGreater(sum(g['locked_pairs'] for g in audit),0)
        self.assertEqual(sum(g['endpoint_inversions_after'] for g in audit),0)

    def test_source_corridor_excludes_a_shorter_foreign_walk(self):
        course=[(0,0),(0,100),(200,100),(200,0)]
        variants=[]
        for strict in [False,True]:
            graph=lb.Network(source_bound=strict)
            a=graph.new_node(course[0]); b=graph.new_node(course[-1])
            native=graph.new_edge(course,a,b,['Base'])
            foreign=graph.new_edge([course[0],course[-1]],a,b,['Base'])
            graph.insert(course,'Route')
            variants.append((set(graph.edge[native]['lines']),set(graph.edge[foreign]['lines'])))
        self.assertIn('Route',variants[0][1])  # independent reproduction of old shortcut
        self.assertIn('Route',variants[1][0])
        self.assertNotIn('Route',variants[1][1])

    def test_shared_branch_centres_and_profiles_agree_without_moving_true_ends(self):
        graph=lb.Network();graph.node={0:(-100,0),1:(0,0),2:(100,0),3:(0,100)}
        edges=[{'u':0,'v':1,'co':[graph.node[0],graph.node[1]],'lines':['A','B']},
               {'u':1,'v':2,'co':[graph.node[1],graph.node[2]],'lines':['A','B']},
               {'u':1,'v':3,'co':[graph.node[1],graph.node[3]],'lines':['B']}]
        order=EndpointOrder(graph,edges,{})
        drawings={(0,'A'):[(-100,0),(-50,0),(0,6)],(1,'A'):[(0,6),(50,0),(100,0)],
                  (0,'B'):edges[0]['co'],(1,'B'):edges[1]['co'],(2,'B'):edges[2]['co']}
        fitted,changes=shared_centres(edges,drawings,graph)
        self.assertEqual(len(changes['shared_paths']),2)
        self.assertEqual(len(changes['ports']),1)
        # one common centre towards the branching node; towards the far ends each keeps its own
        from shapely.geometry import LineString
        a,b=LineString(fitted[0,'A']),LineString(fitted[0,'B'])
        for d in (0,2,5):
            self.assertLess(a.interpolate(a.length-d).distance(b.interpolate(b.length-d)),.05)
        profiles=offset_profiles(edges,order,fitted)
        for (i,key),co in fitted.items():
            end=-1 if edges[i]['v']==1 else 0
            self.assertLess(math.dist(co[end],graph.node[1]),1e-9)
            self.assertEqual(co[0 if end==-1 else -1],drawings[i,key][0 if end==-1 else -1])
            distance=sum(math.dist(a,b) for a,b in zip(co,co[1:])) if end==-1 else 0
            self.assertAlmostEqual(value_at(profiles[i,key],distance),0)

if __name__=='__main__':unittest.main()
