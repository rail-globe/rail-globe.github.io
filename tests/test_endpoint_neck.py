"""A line through a junction node along a short neck is no turn back (endpoint_profiles.after_neck)."""
from collections import Counter
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import line_bundles as lb
from endpoint_order import EndpointOrder
from endpoint_profiles import offset_profiles
from continuous_offset import value_at


def junction(part):
    """Node 0 on a street; stretches 1 and 2 leave it together along an 8 m neck, then part:
    north (part=True) or both on east (part=False, a line really running out and back)."""
    graph = lb.Network()
    far = (8, 60) if part else (60, 1)
    graph.node = {0: (0, 0), 1: (-200, 0), 2: far, 3: (8, -60) if part else (60, -1)}
    edges = [{'u': 0, 'v': 1, 'co': [(0, 0), (-200, 0)], 'lines': ['X']},
             {'u': 0, 'v': 2, 'co': [(0, 0), (8, 0), far], 'lines': ['T', 'X']},
             {'u': 0, 'v': 3, 'co': [(0, 0), (8, 0), graph.node[3]], 'lines': ['T', 'X']}]
    votes = {(0, 1, 'T'): Counter({2: 2}), (0, 2, 'T'): Counter({1: 2}),
             (0, 0, 'X'): Counter({1: 2, 2: 1}), (0, 1, 'X'): Counter({0: 2}), (0, 2, 'X'): Counter({0: 1})}
    order = EndpointOrder(graph, edges, votes)
    drawings = {(i, line): e['co'] for i, e in enumerate(edges) for line in e['lines']}
    return edges, order, drawings


class NeckTests(unittest.TestCase):
    def test_a_line_through_a_neck_keeps_its_seat(self):
        edges, order, drawings = junction(part=True)
        before = offset_profiles(edges, order, drawings)
        after = offset_profiles(edges, order, drawings, necks=True)
        for i in (1, 2):
            self.assertAlmostEqual(value_at(before[i, 'T'], 0), 0)        # taken for a turn back
            self.assertGreater(abs(value_at(after[i, 'T'], 0)), .4)       # its seat through the node

    def test_a_real_out_and_back_still_meets_at_the_node(self):
        edges, order, drawings = junction(part=False)
        after = offset_profiles(edges, order, drawings, necks=True)
        for i in (1, 2):
            self.assertAlmostEqual(value_at(after[i, 'T'], 0), 0)


if __name__ == '__main__':
    unittest.main()
