"""The directional hook must fail closed and preserve complete native loops."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from shapely.geometry import LineString
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import europe_directional_paths as ep


class DirectionalPathsTests(unittest.TestCase):
    def setUp(self):
        self.ways = {
            11: ({'railway':'tram'}, [(8,47),(8.001,47),(8.001,47.001),(8,47)]),
            12: ({'railway':'tram'}, [(8,47),(7.999,47),(7.998,47)]),
            13: ({'railway':'tram'}, [(7.998,47.0001),(7.999,47.0001),(8,47)]),
        }
        self.relations = {
            1: ({'type':'route','route':'tram'}, [('w',11),('w',12),('w',99)]),
            2: ({'type':'route','route':'tram'}, [('w',13)]),
            3: ({'type':'route_master'}, [('r',1),('r',2)]),
        }
        self.default = [LineString([(8,47),(8.1,47)])]
        fp = ep.source_fingerprint((1,2),3,self.ways,self.relations)
        self.profiles = {('test','N','Service',(1,2)):ep.SourceProfile(3,fp)}

    def call(self, rids=(1,2), ways=None, relations=None, name='Service'):
        with patch.object(ep,'PROFILES',self.profiles):
            return ep.directional_paths('test','N',name,rids,
                                        self.ways if ways is None else ways,
                                        self.relations if relations is None else relations,
                                        self.default)

    def test_complete_directions_preserve_real_loop_and_different_terminal(self):
        result=self.call()
        self.assertIsNot(result,self.default)
        native=[LineString(co) for tags,co in self.ways.values()]
        from shapely.ops import unary_union
        self.assertLess(unary_union(result).hausdorff_distance(unary_union(native)),1e-8)

    def test_unknown_or_partial_identity_returns_same_default_object(self):
        for rids,name in [((1,),'Service'),((1,2,4),'Service'),((1,1,2),'Service'),((1,2),'Other')]:
            self.assertIs(self.call(rids=rids,name=name),self.default)

    def test_changed_member_range_or_missing_running_way_fails_closed(self):
        rr=copy.deepcopy(self.relations);rr[1][1].pop()
        self.assertIs(self.call(relations=rr),self.default)
        ww=copy.deepcopy(self.ways);del ww[12]
        self.assertIs(self.call(ways=ww),self.default)

    def test_changed_master_or_new_available_member_fails_closed(self):
        rr=copy.deepcopy(self.relations);rr[3][1].append(('r',4))
        self.assertIs(self.call(relations=rr),self.default)
        ww=copy.deepcopy(self.ways);ww[99]=({'railway':'tram'},[(8,47),(8.002,47)])
        self.assertIs(self.call(ways=ww),self.default)

    def test_unchanged_missing_reviewed_platform_is_bound_in_fingerprint(self):
        self.assertIsNot(self.call(),self.default)
        self.assertEqual(ep.source_fingerprint((2,1),3,self.ways,self.relations),ep.source_fingerprint((1,2),3,self.ways,self.relations))

    def test_unbacked_stitch_output_fails_continuous_source_guard(self):
        with patch.object(ep,'stitch',return_value=[LineString([(8,47),(8.1,47)])]):
            self.assertIs(self.call(),self.default)

    def test_reversed_native_way_representation_can_be_reviewed_independently(self):
        ww={w:(tags,co[::-1]) for w,(tags,co) in self.ways.items()}
        fp=ep.source_fingerprint((1,2),3,ww,self.relations)
        self.profiles={('test','N','Service',(1,2)):ep.SourceProfile(3,fp)}
        result=self.call(ways=ww)
        self.assertIsNot(result,self.default)
        from shapely.ops import unary_union
        self.assertLess(unary_union(result).hausdorff_distance(unary_union([LineString(co) for tags,co in ww.values()])),1e-8)

    def test_expected_absent_master_is_exact_and_new_parent_fails_closed(self):
        rr=copy.deepcopy(self.relations);del rr[3]
        fp=ep.source_fingerprint((1,2),3,self.ways,rr,expected_absent_master=True)
        self.profiles={('test','N','Service',(1,2)):ep.SourceProfile(3,fp,expected_absent_master=True)}
        self.assertIsNot(self.call(relations=rr),self.default)
        rr[3]=copy.deepcopy(self.relations[3])
        self.assertIs(self.call(relations=rr),self.default)
        del rr[3];rr[4]=({'type':'route_master'},[('r',1)])
        self.assertIs(self.call(relations=rr),self.default)

    def test_only_reviewed_native_service_members_are_retained(self):
        ww=copy.deepcopy(self.ways)
        ww[12][0]['service']='crossover'
        ww[13][0]['service']='siding'
        fp=ep.source_fingerprint((1,2),3,ww,self.relations)
        self.profiles={('test','N','Service',(1,2)):ep.SourceProfile(3,fp,running_service_members=(12,))}
        # Direction 2 consists solely of an unreviewed siding, so the whole
        # service must fail closed instead of publishing a partial direction.
        self.assertIs(self.call(ways=ww),self.default)
        del ww[13][0]['service']
        fp=ep.source_fingerprint((1,2),3,ww,self.relations)
        self.profiles={('test','N','Service',(1,2)):ep.SourceProfile(3,fp,running_service_members=(12,))}
        result=self.call(ways=ww)
        from shapely.ops import unary_union
        self.assertLess(unary_union(result).hausdorff_distance(unary_union([LineString(co) for tags,co in ww.values()])),1e-8)

    def test_service_qualification_is_shared_pure_and_profile_complete(self):
        ww=copy.deepcopy(self.ways);ww[12][0]['service']='crossover'
        fp=ep.source_fingerprint((1,2),3,ww,self.relations)
        profiles={('test','N','Service',(1,2)):ep.SourceProfile(3,fp,running_service_members=(12,))}
        original=copy.deepcopy((ww,self.relations))
        with patch.object(ep,'PROFILES',profiles):
            self.assertTrue(ep.approved_service_way('test',1,12,ww,self.relations))
            self.assertFalse(ep.approved_service_way('test',2,12,ww,self.relations))
            self.assertFalse(ep.approved_service_way('test',1,11,ww,self.relations))
            self.assertFalse(ep.approved_service_way('other',1,12,ww,self.relations))
            self.assertEqual((ww,self.relations),original)
            rr=copy.deepcopy(self.relations);rr[2][1].append(('w',999))
            self.assertFalse(ep.approved_service_way('test',1,12,ww,rr))

class NativeNormalContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pickle,tempfile
        import country
        from process_europe import COUNTRIES
        from europe_urban_policy import load_relations
        cls.contexts={};cls.raw={}
        root=Path(__file__).resolve().parents[1]
        for code in {key[0] for key in ep.PROFILES}:
            file_path=root/'data/raw'/('extract_'+code+'.pkl')
            ex=pickle.load(file_path.open('rb'));cfg=COUNTRIES[code]
            cls.raw[code]=({i:(t,c) for i,t,c in ex['ways']},{i:(t,m) for i,t,m in ex['relations']})
            with tempfile.TemporaryDirectory() as temp,patch.object(country,'OUT',Path(temp)):
                if cfg.urban_preflight:cfg.urban_preflight(ex)
            ways={i:(t,c) for i,t,c in ex['ways']};relations={i:(t,m) for i,t,m in ex['relations']}
            if cfg.urban_policy:relations=load_relations(code,file_path,relations,ex.get('relation_tag_schema',()))
            cls.contexts[code]=(ways,relations)

    def test_real_preflight_and_policy_load_hit_every_profile_and_crossovers(self):
        hits=0;approved=[]
        for key,p in ep.PROFILES.items():
            code,network,name,rids=key;ways,relations=self.contexts[code];default=[]
            self.assertIsNot(ep.directional_paths(code,network,name,rids,ways,relations,default),default,key)
            hits+=1
            for rid in rids:
                for wid in p.running_service_members:
                    if ('w',wid) in relations[rid][1]:
                        self.assertTrue(ep.approved_service_way(code,rid,wid,ways,relations))
                        approved.append((rid,wid))
        self.assertGreaterEqual(hits,4)
        self.assertEqual(sorted(approved),[(190184,421604691),(13154071,421604691),(13154071,421883135)])

    def test_raw_and_complete_normal_context_are_independently_bound(self):
        for key,p in ep.PROFILES.items():
            code,network,name,rids=key;ways,relations=self.raw[code]
            self.assertEqual(ep.source_fingerprint(rids,p.master,ways,relations,expected_absent_master=p.expected_absent_master),p.fingerprint)
            ways,relations=self.contexts[code]
            self.assertEqual(ep.source_fingerprint(rids,p.master,ways,relations,expected_absent_master=p.expected_absent_master),p.context_fingerprint)

    def test_native_member_coordinate_and_retained_tag_changes_fail_closed(self):
        for key,p in ep.PROFILES.items():
            code,network,name,rids=key;ways,relations=self.contexts[code];default=[];rid=rids[0]
            for field in ('name','ref','operator'):
                changed=dict(relations);tags,members=relations[rid];changed[rid]=({**tags,field:'changed'},members)
                self.assertIs(ep.directional_paths(code,network,name,rids,ways,changed,default),default)
            changed=dict(relations);tags,members=relations[rid];changed[rid]=(tags,list(members)+[('w',-1)])
            self.assertIs(ep.directional_paths(code,network,name,rids,ways,changed,default),default)
            wid=next(w for kind,w in members if kind=='w' and w in ways)
            changedways=dict(ways);tags,co=ways[wid];newco=list(co);newco[0]=(co[0][0]+1e-6,co[0][1]);changedways[wid]=(tags,newco)
            self.assertIs(ep.directional_paths(code,network,name,rids,changedways,relations,default),default)

    def test_enriched_website_wikipedia_are_exact_values_not_ignored(self):
        for key,p in ep.PROFILES.items():
            code,network,name,rids=key;ways,relations=self.contexts[code];default=[]
            for rid in tuple(rids)+(p.master,):
                if rid not in relations:continue
                tags,members=relations[rid]
                for field in ('website','wikipedia'):
                    if field not in tags:continue
                    changed=dict(relations);changed[rid]=({**tags,field:tags[field]+'-changed'},members)
                    self.assertIs(ep.directional_paths(code,network,name,rids,ways,changed,default),default)
                    for route in rids:
                        for wid in p.running_service_members:
                            self.assertFalse(ep.approved_service_way(code,route,wid,ways,changed))

    def test_changed_raw_extract_cannot_reuse_bound_policy_supplement(self):
        import pickle,tempfile
        from europe_urban_policy import load_relations
        code='es';ways,relations=self.raw[code]
        altered=dict(relations);rid=190184;tags,members=altered[rid];altered[rid]=({**tags,'wikipedia':'changed'},members)
        with tempfile.TemporaryDirectory() as temp:
            file_path=Path(temp)/'extract_es.pkl';file_path.write_bytes(pickle.dumps(altered))
            with self.assertRaisesRegex(ValueError,'another extract'):
                load_relations(code,file_path,altered)

if __name__=='__main__': unittest.main()
