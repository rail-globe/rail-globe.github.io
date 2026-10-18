import math
import sys
import unittest
from pathlib import Path
from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import line_bundles as lb
from endpoint_order import EndpointOrder, geographic_groups, canonical_features
from endpoint_profiles import offset_profiles
from continuous_offset import value_at


def proved(g, edges, initial=None, geometries=None):
    votes = {}
    for i,a in enumerate(edges):
        for j,b in enumerate(edges):
            if i==j: continue
            for node in {a['u'],a['v']} & {b['u'],b['v']}:
                for line in set(a['lines']) & set(b['lines']):
                    votes.setdefault((node,i,line),{})[j]=1
    if geometries is None:
        path=LineString([(-100,0),(100,0)])
        geometries={line:path for e in edges for line in e['lines']}
    return EndpointOrder(g,edges,votes,geometries,initial=initial)


class EndpointTests(unittest.TestCase):
    def graph(self):
        g = lb.Network()
        g.node = {0: (-100, 0), 1: (0, 0), 2: (100, 0), 3: (50, 80)}
        edges = [{'co': [g.node[0], g.node[1]], 'u': 0, 'v': 1, 'lines': ['A', 'B']},
                 {'co': [g.node[1], g.node[2]], 'u': 1, 'v': 2, 'lines': ['A', 'B']},
                 {'co': [g.node[1], g.node[3]], 'u': 1, 'v': 3, 'lines': ['A']}]
        return g, edges

    def test_source_turn_overrules_straightest_guess(self):
        g, edges = self.graph()
        order = EndpointOrder(g, edges, {(1, 0, 'A'): {2: 1}, (1, 2, 'A'): {0: 1}})
        self.assertEqual(order.next[1, 0, 'A'], 2)
        self.assertTrue(order.connection_audit['changed_straightest_guesses'])

    def test_unresolved_branch_does_not_get_straightest_fallback(self):
        g, edges = self.graph()
        order = EndpointOrder(g, edges, {})
        self.assertNotIn((1, 0, 'A'), order.next)
        self.assertTrue(order.connection_audit['unresolved_ports'])

    def test_true_source_branches_keep_all_choices(self):
        g, edges = self.graph()
        order = EndpointOrder(g, edges, {(1, 0, 'A'): {1: 2, 2: 1}})
        self.assertEqual(set(order.connections[1, 0, 'A']), {1, 2})
        self.assertNotIn((1, 0, 'A'), order.next)

    def test_endpoint_projection_and_annealing_keep_pair_order(self):
        g, edges = self.graph()
        edges = edges[:2]
        order = proved(g, edges, initial=[['A', 'B'], ['B', 'A']])
        self.assertEqual(order.inversions(order.locks), 1)
        order.anneal(rounds=200)
        self.assertEqual(order.inversions(), 0)
        self.assertEqual(order.order[0], order.order[1])

    def test_reversed_edge_uses_reversed_stored_rank(self):
        g, edges = self.graph()
        edges = edges[:2]
        edges[1] = {**edges[1], 'u': 2, 'v': 1, 'co': edges[1]['co'][::-1]}
        order = proved(g, edges)
        order.anneal(rounds=200)
        self.assertEqual(order.order[0], order.order[1][::-1])

    def test_physical_side_change_is_not_a_monotone_lock(self):
        g, edges = self.graph()
        source = {'A': LineString([(-100, 0), (100, 0)]),
                  'B': LineString([(-100, -8), (100, 8)])}
        order = proved(g, edges[:2], geometries=source)
        self.assertTrue(order.protected)
        self.assertFalse(order.locks)

    def test_local_hairpin_port_uses_near_tangent_not_distant_direction(self):
        g, edges = self.graph()
        edges = edges[:2]
        edges[1]['lines'] = ['A']
        order = proved(g, edges)
        straight = offset_profiles(edges, order, {(i, name): edge['co'] for i, edge in enumerate(edges) for name in edge['lines']})
        self.assertEqual(value_at(straight[0, 'A'], 100), -.5)
        # The first 8 m turn back west, while the long direction points north.
        edges[1]['co'] = [(0, 0), (-10, 0), (0, 100)]
        order = proved(g, edges)
        tight = offset_profiles(edges, order, {(i, name): edge['co'] for i, edge in enumerate(edges) for name in edge['lines']})
        self.assertEqual(value_at(tight[0, 'A'], 100), 0)

    def test_common_branch_centre_eases_back_before_an_end_where_no_line_branches(self):
        """Basel Bankverein, 2026-10-18: the common course of a stretch from a branching node
        must not carry one family's turn to the stretch's other end, where the lines part."""
        from endpoint_bundles import shared_centres
        g = lb.Network()
        g.node = {0: (0, 0), 1: (300, 0), 2: (600, 0), 3: (480, 220), 4: (-300, 0), 5: (-200, -250)}
        edges = [{'co': [g.node[0], g.node[1]], 'u': 0, 'v': 1, 'lines': ['A', 'B', 'C']},
                 {'co': [g.node[1], g.node[2]], 'u': 1, 'v': 2, 'lines': ['A', 'B']},
                 {'co': [g.node[1], g.node[3]], 'u': 1, 'v': 3, 'lines': ['C']},
                 {'co': [g.node[4], g.node[0]], 'u': 4, 'v': 0, 'lines': ['A', 'B', 'C']},
                 {'co': [g.node[0], g.node[5]], 'u': 0, 'v': 5, 'lines': ['C']}]
        order = proved(g, edges)
        stretch = [list(e['co']) for e in edges]
        drawings = lb.smooth_lines(edges, stretch, order)
        out, audit = shared_centres(edges, drawings, g)
        # the far end (node 1, no line branches there): every line meets its own next stretch,
        # off the graph node (smoothed), and that node's ports are not pulled together
        self.assertNotIn(1, [row['node'] for row in audit['ports']])
        for line, nxt in (('A', 1), ('B', 1), ('C', 2)):
            self.assertEqual(tuple(out[0, line][-1]), tuple(out[nxt, line][0]))
        self.assertGreater(math.dist(out[0, 'C'][-1], g.node[1]), 1)
        # the branching end keeps one common port on the graph node
        self.assertLess(max(math.dist(out[0, line][0], g.node[0]) for line in 'ABC'), 1e-9)

    def test_near_geometry_across_city_names_groups_together(self):
        a = {'properties': {'ct': 'X'}, 'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [.01, 0]]}}
        b = {'properties': {'ct': 'Y'}, 'geometry': {'type': 'LineString', 'coordinates': [[0, .0001], [.01, .0001]]}}
        self.assertEqual(len(geographic_groups([a, b])), 1)

    def test_same_label_without_source_identity_is_not_merged(self):
        features = [{'properties': {'network': 'N', 'n': '1', 'col': '#ff0000', 'rid': rid},
                     'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [.01, 0]]}} for rid in ['1', '2']]
        source = {f'N|1|{rid}': {'rids': [int(rid)], 'masters': []} for rid in ['1', '2']}
        out, _ = canonical_features(features, source)
        self.assertEqual(len(out), 2)

    def test_shared_route_master_merges_variants_preserving_rids(self):
        features = [{'properties': {'network': 'N', 'n': '1', 'col': '#ff0000', 'rid': rid},
                     'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [.01, 0]]}} for rid in ['1', '2']]
        source = {f'N|1|{rid}': {'rids': [int(rid)], 'masters': [100], 'routes': []} for rid in ['1', '2']}
        out, _ = canonical_features(features, source)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['properties']['rid'], '1,2')
        self.assertEqual(len(out[0]['geometry']['coordinates']), 1)


if __name__ == '__main__':
    unittest.main()
