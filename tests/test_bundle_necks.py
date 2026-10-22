"""split_necks: a junction two stretches leave together is moved to where they part (line_bundles)."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import line_bundles as lb
from line_bundles import Network, contract, split_necks


def riebeck(east_lines=("A", "B", "T"), north_lines=("A", "T"), west_lines=("A", "B")):
    """Halle Riebeckplatz in small (2026-10-22): a street west-east through J (0,0); the stretch
    north leaves J along the stretch east, within 2 m of it for 10 m, then turns north. A and B
    run west-east, T turns from east to north (it never goes west)."""
    net = Network(source_bound=True)
    j = net.new_node((0.0, 0.0))
    w, e, n = net.new_node((-300.0, 0.0)), net.new_node((300.0, 0.0)), net.new_node((12.0, 300.0))
    net.new_edge([(-300.0, 0.0), (0.0, 0.0)], w, j, west_lines)
    net.new_edge([(0.0, 0.0), (10.0, 0.0), (300.0, 0.0)], j, e, east_lines)
    net.new_edge([(0.0, 0.0), (10.0, 1.5), (12.0, 20.0), (12.0, 300.0)], j, n, north_lines)
    return net, j


def fork(angle):
    """J with a street west and two stretches east-ish, angle degrees apart."""
    net = Network(source_bound=True)
    j = net.new_node((0.0, 0.0))
    w = net.new_node((-300.0, 0.0))
    a = math.radians(angle / 2)
    p, q = (300 * math.cos(a), 300 * math.sin(a)), (300 * math.cos(a), -300 * math.sin(a))
    u, v = net.new_node(p), net.new_node(q)
    net.new_edge([(-300.0, 0.0), (0.0, 0.0)], w, j, ["A", "B"])
    net.new_edge([(0.0, 0.0), p], j, u, ["A"])
    net.new_edge([(0.0, 0.0), q], j, v, ["B"])
    return net, j


class NeckTests(unittest.TestCase):
    def test_the_junction_moves_to_where_the_two_stretches_part(self):
        net, j = riebeck()
        split_necks(net)
        at_j = [e for e in net.edge.values() if j in (e["u"], e["v"])]
        self.assertEqual(len(at_j), 2)                       # the street west and the neck
        neck = next(e for e in at_j if e["co"][0] != (-300.0, 0.0))
        self.assertEqual(neck["lines"], {"A", "B"})          # T only turns at the new node
        m = neck["v"] if neck["u"] == j else neck["u"]
        self.assertGreater(math.dist(net.node[m], (0.0, 0.0)), 5.0)
        self.assertLess(math.dist(net.node[m], (0.0, 0.0)), 15.0)
        lines_at_m = sorted(sorted(e["lines"]) for e in net.edge.values() if m in (e["u"], e["v"]))
        self.assertEqual(lines_at_m, [["A", "B"], ["A", "B", "T"], ["A", "T"]])

    def test_after_contract_the_old_node_is_gone(self):
        # the neck carries what the street west carries: one stretch from west to the new node
        net, j = riebeck()
        split_necks(net)
        edges = contract(net)
        self.assertFalse(any(j in (e["u"], e["v"]) for e in edges))
        self.assertEqual(len(edges), 3)

    def test_a_narrow_fork_is_left_alone(self):
        # two stretches drifting apart from the node on (Halle Saline, 15 degrees) are no neck
        net, j = fork(15)
        before = {i: dict(e) for i, e in net.edge.items()}
        split_necks(net)
        self.assertEqual({i: (e["u"], e["v"], e["co"]) for i, e in net.edge.items()},
                         {i: (e["u"], e["v"], e["co"]) for i, e in before.items()})

    def test_a_wide_junction_is_left_alone(self):
        net, j = fork(90)
        n = len(net.edge)
        split_necks(net)
        self.assertEqual(len(net.edge), n)

    def test_a_loop_back_to_the_node_is_no_neck(self):
        # Halle Marktplatz: Tram 5 out 11 m along the bundle and back to the node through one
        # node of two stretches; contract drops it as a thin loop only if its ends stay on the node
        net, j = riebeck()
        k = net.new_node((5.0, 8.0))
        net.new_edge([(0.0, 0.0), (10.0, 0.5), (12.0, 6.0), (5.0, 8.0)], j, k, ["L"])
        net.new_edge([(5.0, 8.0), (-2.0, 6.0), (0.0, 0.0)], k, j, ["L"])
        split_necks(net)
        self.assertTrue(all(j in (e["u"], e["v"]) for e in net.edge.values() if "L" in e["lines"]))

    def test_only_the_listed_cities(self):
        self.assertEqual(lb.NECK_CITIES, ("哈勒",))


class StubIdentityTests(unittest.TestCase):
    def test_alicante_group_line_of_another_city(self):
        p = {"ct": "西班牙其他", "g": "es", "network": "TRAM Metropolità d'Alacant", "n": "Dénia ↔ Benidorm"}
        self.assertTrue(lb.listed(p, lb.BRANCH_STUB_CITIES, lb.BRANCH_STUB_IDENTITIES))
        q = dict(p, n="T1 (Ibaiondo - Salburua)", network="Euskotren Tranbia")
        self.assertFalse(lb.listed(q, lb.BRANCH_STUB_CITIES, lb.BRANCH_STUB_IDENTITIES))


if __name__ == "__main__":
    unittest.main()
