import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from europe_identity_candidates import CANDIDATES,build_matcher


def fixture(candidate):
    master=dict(type='route_master',route_master=candidate.mode,ref=candidate.ref,
                name='Tram '+candidate.ref,network=candidate.networks[0])
    rows=[(candidate.master,master,[('r',rid) for rid in candidate.routes])]
    for i,rid in enumerate(candidate.routes):
        tags=dict(type='route',route=candidate.mode,ref=candidate.ref,
                  network=candidate.networks[i%len(candidate.networks)],colour='#ed6ea7',name='direction '+str(i))
        rows.append((rid,tags,[('w',rid+100)]))
    return {'relations':rows,'ways':[]}


class IdentityCandidateTests(unittest.TestCase):
    def test_exact_reviewed_master_and_routes_merge_across_network_aliases(self):
        c=CANDIDATES[0];ex=fixture(c);callback,audit=build_matcher(ex,'ch')
        keys=[callback((ex['relations'][i+1][1]['network'],'Tram 8','#ed6ea7'),rid) for i,rid in enumerate(c.routes)]
        self.assertEqual(len(set(keys)),1)
        self.assertEqual(audit[0]['status'],'accepted')

    def test_same_name_and_colour_outside_whitelist_do_not_merge(self):
        c=CANDIDATES[0];callback,_=build_matcher(fixture(c),'ch')
        key=('TNW','Tram 8','#ed6ea7');self.assertEqual(callback(key,999),key)
        foreign=('Other network','Tram 8','#ed6ea7');self.assertEqual(callback(foreign,c.routes[0]),foreign)

    def test_future_extra_master_branch_fails_closed(self):
        c=CANDIDATES[0];ex=fixture(c);ex['relations'][0][2].append(('r',999))
        callback,audit=build_matcher(ex,'ch');key=('TNW','Tram 8','#ed6ea7')
        self.assertEqual(callback(key,c.routes[-1]),key)
        self.assertIn('master_children_changed',audit[0]['issues'])

    def test_changed_ref_or_mode_or_country_does_not_merge(self):
        c=CANDIDATES[0]
        for field,value in [('ref','8A'),('route','bus'),('network','Unknown')]:
            ex=fixture(c);ex['relations'][1][1][field]=value
            callback,audit=build_matcher(ex,'ch');key=('TNW','Tram 8','#ed6ea7')
            self.assertEqual(callback(key,c.routes[-1]),key)
            self.assertEqual(audit[0]['status'],'blocked')
        callback,_=build_matcher(fixture(c),'be');key=('TNW','Tram 8','#ed6ea7')
        self.assertEqual(callback(key,c.routes[0]),key)

    def test_conflicting_direction_colours_require_independent_review(self):
        c=CANDIDATES[2];ex=fixture(c);ex['relations'][1][1]['colour']='#996c1b'
        callback,audit=build_matcher(ex,'de');row=next(r for r in audit if r['master']==c.master)
        self.assertIn('reviewed_colour_required',row['issues'])
        callback,audit=build_matcher(ex,'de',reviewed_colours={c.master:'#a795ba'})
        self.assertEqual(callback(('VRR','Tram 101','#996c1b'),c.routes[0]),('VRR','Tram 101','#a795ba'))

    def test_input_is_not_mutated_and_variant_services_are_absent(self):
        ex=fixture(CANDIDATES[0]);before=copy.deepcopy(ex);build_matcher(ex,'ch');self.assertEqual(ex,before)
        forbidden={920089,920090,3150546,3150579,16018429,16018430,2386447,12400405}
        self.assertFalse(forbidden&{rid for c in CANDIDATES for rid in c.routes})


if __name__=='__main__':unittest.main()
