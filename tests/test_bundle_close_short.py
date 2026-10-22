"""close_short: where two nodes of one junction are joined (line_bundles)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from line_bundles import Network, close_short


def network(stub_lines, branch_stubs=True):
    """A street through J (0,0) carrying A, B, C, D; a stub J-K (0,-25) carrying stub_lines; K's
    branch south carrying E and F."""
    net = Network(source_bound=True, branch_stubs=branch_stubs)
    j, k = net.new_node((0.0, 0.0)), net.new_node((0.0, -25.0))
    w, e, s = net.new_node((-300.0, 0.0)), net.new_node((300.0, 0.0)), net.new_node((0.0, -300.0))
    street = ["A", "B", "C", "D"]
    net.new_edge([(-300.0, 0.0), (0.0, 0.0)], w, j, street)
    net.new_edge([(0.0, 0.0), (300.0, 0.0)], j, e, street)
    net.new_edge([(0.0, 0.0), (0.0, -25.0)], j, k, stub_lines)
    net.new_edge([(0.0, -25.0), (0.0, -300.0)], k, s, ["E", "F"])
    return net, j


class CloseShortTests(unittest.TestCase):
    def test_a_branch_stub_joins_the_street_where_the_through_lines_pass(self):
        # Halle Saline, Karlsruhe Schillerstraße (2026-10-22): at the midpoint the street's
        # junction moved 12 m down the branch and every through line dipped to it and back
        net, j = network(["E", "F"])
        close_short(net)
        self.assertEqual(len(net.node), 4)
        self.assertEqual(net.node[j], (0.0, 0.0))
        for edge in net.edge.values():
            if j in (edge["u"], edge["v"]):
                end = edge["co"][0] if edge["u"] == j else edge["co"][-1]
                self.assertEqual(tuple(end), (0.0, 0.0))

    def test_a_stretch_of_the_bundle_itself_closes_up_at_the_midpoint(self):
        # the stub carries as many lines as pass the junction: it is no branch stub
        net, j = network(["A", "B", "C", "D", "E", "F"])
        close_short(net)
        self.assertEqual(net.node[j], (0.0, -12.5))

    def test_cities_not_listed_keep_the_midpoint(self):
        # the rule is on only in line_bundles.BRANCH_STUB_CITIES
        net, j = network(["E", "F"], branch_stubs=False)
        close_short(net)
        self.assertEqual(net.node[j], (0.0, -12.5))


if __name__ == "__main__":
    unittest.main()
