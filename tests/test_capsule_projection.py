import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from station_capsules import project_line


class CapsuleProjectionTests(unittest.TestCase):
    def test_repeated_vertices_keep_distance_and_bounded_anchor(self):
        coords = [[0,0],[0,0],[2,0],[2,0],[2,3]]
        self.assertEqual(project_line(coords, [3,2]), (4, [2,2]))
        self.assertEqual(project_line(coords, [-1,0]), (0, [0,0]))
        self.assertEqual(project_line(coords, [2,4]), (5, [2,3]))

    def test_reverse_path_keeps_anchor_and_complements_distance(self):
        coords = [[0,0],[2,0],[2,3]]
        forward, anchor = project_line(coords, [3,2])
        reverse, back = project_line(coords[::-1], [3,2])
        self.assertEqual(anchor, back)
        self.assertEqual(forward+reverse, 5)

    def test_zero_length_path_has_no_candidate(self):
        self.assertEqual(project_line([[1,1],[1,1]], [1,1]), (None,None))
