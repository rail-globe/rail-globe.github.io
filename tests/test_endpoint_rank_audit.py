"""Independent endpoint-rank invariants for the bounded Apple-idea pilot.

The native evidence establishes a conditional endpoint-index sort, not this
implementation's graph construction, source matching, or optimisation policy.
These tests check actual rank relationships rather than objective improvement.
"""
import itertools
import math
from collections import Counter
from pathlib import Path
import sys
import unittest

from shapely.geometry import LineString, MultiLineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import line_bundles as lb
from endpoint_order import EndpointOrder, source_turns


def fixture(nodes, rows):
    graph = lb.Network()
    graph.node = dict(enumerate(nodes))
    edges = [{'u': u, 'v': v, 'co': [nodes[u], nodes[v]], 'lines': list(names)}
             for u, v, names in rows]
    return graph, edges


def reverse_edges(edges, selected):
    return [{**edge, 'u': edge['v'], 'v': edge['u'], 'co': edge['co'][::-1]}
            if index in selected else {**edge, 'co': list(edge['co'])}
            for index, edge in enumerate(edges)]


def backed_order(graph, edges, initial=None):
    """Synthetic fixtures explicitly prove every unambiguous source turn.

    Per-line raw geometry includes both incident arms. These fixtures describe
    coincident source tracks, so no pair has a physical side-change witness.
    Ambiguous turns still require an explicit fixture vote rather than a guess.
    """
    votes = {}
    paths = {}
    for line in {name for edge in edges for name in edge['lines']}:
        parts = [edge['co'] for edge in edges if line in edge['lines']]
        paths[line] = MultiLineString(parts)
        for node in graph.node:
            incident = [i for i, edge in enumerate(edges)
                        if node in (edge['u'], edge['v']) and line in edge['lines']]
            if len(incident) == 2:
                i, j = incident
                votes[node, i, line] = Counter({j: 1})
                votes[node, j, line] = Counter({i: 1})
    return EndpointOrder(graph, edges, votes, paths, initial=initial)


class EndpointRankAudit(unittest.TestCase):
    def test_common_travel_direction_with_every_stored_orientation(self):
        graph, edges = fixture([(0, 0), (100, 0), (200, 0), (300, 0)],
                               [(0, 1, 'ABC'), (1, 2, 'ABC'), (2, 3, 'ABC')])
        for mask in itertools.product((False, True), repeat=3):
            with self.subTest(reversed=mask):
                variant = reverse_edges(edges, {i for i, yes in enumerate(mask) if yes})
                order = backed_order(graph, variant, initial=[list(x) for x in ('CAB', 'ABC', 'BCA')])
                self.assertEqual(sum(len(lock[3]) for lock in order.locks), 6)
                order.anneal(rounds=50)
                # Convert stored rank back into the common west-to-east frame.
                directed = [row[::-1] if flipped else row
                            for row, flipped in zip(order.order, mask)]
                self.assertEqual(directed[0], directed[1])
                self.assertEqual(directed[1], directed[2])
                self.assertEqual(order.inversions(order.locks), 0)

    def test_closed_ring_keeps_all_ports_under_reversal_and_edge_reordering(self):
        graph, edges = fixture([(0, 0), (100, 0), (50, 90)],
                               [(0, 1, 'AB'), (1, 2, 'AB'), (2, 0, 'AB')])
        for mask in itertools.product((False, True), repeat=3):
            for permutation in ((0, 1, 2), (2, 0, 1)):
                with self.subTest(reversed=mask, permutation=permutation):
                    variant = reverse_edges(edges, {i for i, yes in enumerate(mask) if yes})
                    variant = [variant[i] for i in permutation]
                    order = backed_order(graph, variant)
                    self.assertEqual(len(order.locks), 3)
                    order.anneal(rounds=50)
                    self.assertFalse(order.parity_conflicts)
                    self.assertEqual(len(order.active_locks), 3)
                    self.assertEqual(order.inversions(order.locks), 0)

    def test_multiple_source_choices_keep_votes_and_exclude_ambiguous_line_from_lock(self):
        graph, edges = fixture([(-100, 0), (0, 0), (100, 0), (60, 80)],
                               [(0, 1, 'ABC'), (1, 2, 'ABC'), (1, 3, 'A')])
        votes = {(1, 0, 'A'): Counter({1: 7, 2: 2}),
                 (1, 1, 'A'): Counter({0: 7}),
                 (1, 2, 'A'): Counter({0: 2})}
        for line in 'BC':
            votes[1, 0, line] = Counter({1: 1})
            votes[1, 1, line] = Counter({0: 1})
        source = {line: LineString([(-100, 0), (0, 0), (100, 0)]) for line in 'ABC'}
        order = EndpointOrder(graph, edges, votes, source)
        self.assertEqual(order.connections[1, 0, 'A'], Counter({1: 7, 2: 2}))
        self.assertNotIn((1, 0, 'A'), order.next)
        self.assertEqual(order.locks, [(1, 0, 1, [('B', 'C')])])
        order.anneal(rounds=50)
        self.assertTrue(math.isfinite(order.total()))
        self.assertEqual(order.inversions(order.locks), 0)

    def test_unilateral_source_choice_does_not_create_reciprocal_pair_lock(self):
        graph, edges = fixture([(-100, 0), (0, 0), (100, 0), (60, 80)],
                               [(0, 1, 'AB'), (1, 2, 'AB'), (1, 3, 'AB')])
        order = EndpointOrder(graph, edges, {(1, 0, line): {1: 1} for line in 'AB'})
        self.assertEqual(order.next[1, 0, 'A'], 1)
        self.assertNotIn((1, 1, 'A'), order.next)
        self.assertFalse(order.locks)

    def test_missing_source_at_branch_does_not_use_votes_to_nonincident_edge(self):
        graph, edges = fixture([(-100, 0), (0, 0), (100, 0), (60, 80), (200, 0)],
                               [(0, 1, 'A'), (1, 2, 'A'), (1, 3, 'A'), (2, 4, 'A')])
        order = EndpointOrder(graph, edges, {(1, 0, 'A'): {3: 50}})
        self.assertNotIn((1, 0, 'A'), order.connections)
        self.assertNotIn((1, 0, 'A'), order.next)
        self.assertIn([1, 0, 'A', [1, 2]], order.connection_audit['unresolved_ports'])

    def test_disconnected_source_chunks_do_not_prove_a_turn_at_ambiguous_node(self):
        graph, edges = fixture([(-100, 0), (0, 0), (100, 0), (0, 100)],
                               [(0, 1, 'A'), (1, 2, 'A'), (1, 3, 'A')])
        source = {'A': {'routes': [{'chunks': [
            [[-100, 0], [-30, 0]], [[0, 30], [0, 100]]]}]}}
        votes, report = source_turns(edges, source, lambda x, y: (x, y))
        self.assertEqual(report['source_chunks'], 2)
        self.assertEqual(report['matched_source_transitions'], 0)
        self.assertFalse(votes)
        order = EndpointOrder(graph, edges, votes)
        self.assertNotIn((1, 0, 'A'), order.next)

    def test_source_side_change_stays_protected_in_reversed_and_multipart_frames(self):
        graph, edges = fixture([(-100, 0), (0, 0), (100, 0)],
                               [(0, 1, 'AB'), (1, 2, 'AB')])
        a = [(-100, 0), (100, 0)]
        b = [(-100, -8), (100, 8)]
        for reverse in (False, True):
            for multipart in (False, True):
                with self.subTest(reverse=reverse, multipart=multipart):
                    paths = [a[::-1], b[::-1]] if reverse else [a, b]
                    cls = (lambda co: MultiLineString([co])) if multipart else LineString
                    source = {line: cls(co) for line, co in zip('AB', paths)}
                    variant = reverse_edges(edges, {0, 1} if reverse else set())
                    votes = {(1, i, line): {1 - i: 1} for i in (0, 1) for line in 'AB'}
                    order = EndpointOrder(graph, variant, votes, source)
                    self.assertEqual(len(order.protected), 1)
                    self.assertFalse(order.locks)

    def test_distinct_pair_families_with_feasible_odd_orientation_cycle_are_enforced(self):
        graph, edges = fixture([(0, 0), (100, 0), (-50, 86.6), (-50, -86.6)],
                               [(0, 1, 'ABEF'), (0, 2, 'ABCD'), (0, 3, 'CDEF')])
        order = backed_order(graph, edges)
        self.assertEqual(len(order.locks), 3)
        self.assertEqual(sum(len(lock[3]) for lock in order.locks), 3)
        # Independent witness: the three pair constraints really are feasible.
        witness = backed_order(graph, edges, initial=[list(x) for x in ('ABEF', 'BACD', 'DCFE')])
        self.assertEqual(len(witness.locks), 3)
        self.assertEqual(witness.inversions(witness.locks), 0)
        # Seeding must enforce feasible pair constraints without relying on a
        # stochastic objective improvement. Whole-edge parity is too coarse.
        order.anneal(rounds=0)
        self.assertEqual(order.inversions(order.locks), 0)

    def test_unique_topology_without_source_does_not_create_hard_lock(self):
        graph, edges = fixture([(-100, 0), (0, 0), (100, 0)],
                               [(0, 1, 'AB'), (1, 2, 'AB')])
        geometry = {line: LineString([(-100, 0), (100, 0)]) for line in 'AB'}
        order = EndpointOrder(graph, edges, {}, geometry)
        self.assertFalse(order.locks)

    def test_votes_without_raw_physical_geometry_do_not_create_hard_lock(self):
        graph, edges = fixture([(-100, 0), (0, 0), (100, 0)],
                               [(0, 1, 'AB'), (1, 2, 'AB')])
        votes = {(1, i, line): {1 - i: 1} for i in (0, 1) for line in 'AB'}
        order = EndpointOrder(graph, edges, votes)
        self.assertFalse(order.locks)

    def test_weak_distinct_source_tracks_are_unknown_instead_of_hard_locked(self):
        graph, edges = fixture([(-100, 0), (0, 0), (100, 0)],
                               [(0, 1, 'AB'), (1, 2, 'AB')])
        votes = {(1, i, line): {1 - i: 1} for i in (0, 1) for line in 'AB'}
        source = {'A': LineString([(-100, 0), (100, 0)]),
                  'B': LineString([(-100, 1), (100, 1)])}
        order = EndpointOrder(graph, edges, votes, source)
        self.assertIsNone(order.physical_crossing(1, 0, 1, 'A', 'B'))
        self.assertFalse(order.protected)
        self.assertFalse(order.locks)


if __name__ == '__main__':
    unittest.main()
