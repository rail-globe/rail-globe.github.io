import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from europe_short_routes import minimum


class ShortPublicRouteTests(unittest.TestCase):
    def test_verified_native_public_tram_keeps_its_full_short_route(self):
        self.assertEqual(minimum('es', 'Metrovalencia', 'Línia 8', [5622077, 5622078], 2), .5)

    def test_unknown_identity_or_mixed_members_do_not_relax_global_cutoff(self):
        for args in [('es','Metrovalencia','Línia 8',[999]),
                     ('es','Metrovalencia','Línia 8',[5622077,999]),
                     ('it','Metrovalencia','Línia 8',[5622077]),
                     ('es','Other','Línia 8',[5622077]),
                     ('es','Metrovalencia','Línia 9',[5622077]),
                     ('es','Metrovalencia','Línia 8',[])]:
            self.assertEqual(minimum(*args,2), 2)
