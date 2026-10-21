import copy
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from europe_hsr import Registry, install, normal_name, uniform_tags
from process_europe import COUNTRIES, kind_of, speed_of, stretch_of, rail_properties, EVIDENCE_TAGS


class EuropeanHSRTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()

    @staticmethod
    def raw_country(code):
        # process_europe may install production callbacks at import time. Build
        # a fresh copy of the public base evidence callbacks for each fixture.
        cfg=copy.copy(COUNTRIES[code])
        cfg._europe_hsr_installed=False
        cfg.kind_of, cfg.speed_of = kind_of, speed_of
        cfg.stretch_of, cfg.rail_properties = stretch_of, rail_properties
        cfg.tag_keys = EVIDENCE_TAGS
        cfg.urban_preflight = None
        return cfg

    def country(self, code):
        return install(self.raw_country(code), self.registry)

    @staticmethod
    def extract(tags, relation=None):
        return {'ways': [(123,dict(tags),[(8.0,50.0),(8.01,50.01)])],
                'relations': [] if relation is None else [(456,relation,[('w',123)])]}

    def evidence(self, code, tags, relation=None):
        cfg=self.country(code)
        ex=self.extract(tags,relation)
        cfg.urban_preflight(ex)
        tags=ex['ways'][0][1]
        row=Counter({tuple(sorted((k,tags[k]) for k in cfg.tag_keys if tags.get(k))):1.0})
        kind=cfg.kind_of(tags.get('name',''),row)
        return cfg, tags, row, kind

    def test_verified_existing_remains_conventional_even_with_highspeed_tag(self):
        for code,name in [('de','Berlin-Hamburger Bahn'),('de','Riedbahn'),('fr','Ligne de Paris-Lyon à Marseille-Saint-Charles')]:
            cfg,tags,row,kind=self.evidence(code,dict(railway='rail',name=name,usage='main',highspeed='yes',maxspeed='230'))
            self.assertEqual(kind,'main')
            self.assertIsNone(cfg.speed_of(name,kind,row))
            props=cfg.rail_properties({123:tags})
            self.assertEqual(props['hsr_state'],'upgraded_existing')
            self.assertNotIn('osm_design_speed',props)
            self.assertEqual(props['osm_maxspeed'],230)
            self.assertIn('http',props['hsr_identity_ref'])

    def test_unresolved_is_explicit_and_not_claimed_as_new_build(self):
        cfg,tags,row,kind=self.evidence('de',dict(railway='rail',name='Unknown',usage='main',highspeed='yes',maxspeed='300'))
        # 2026-10-18: only listed new-build lines are high-speed ("不算", 2026-10-17); an unresolved
        # way is drawn as conventional whatever its running limit, and gets no speed band
        self.assertEqual(kind,'main')
        self.assertEqual(tags['_hsr_state'],'unresolved')
        self.assertEqual(cfg.rail_properties({123:tags})['hsr_identity_unresolved'],1)
        self.assertIsNone(cfg.speed_of('Unknown',kind,row))

    def test_native_design_and_operating_limit_separate(self):
        cfg,tags,row,kind=self.evidence('nl',dict(railway='rail',name='Hanzelijn',maxspeed='140',design_speed='200'))
        self.assertEqual(kind,'hs')
        self.assertEqual(cfg.speed_of('Hanzelijn',kind,row),(200,False,'OSM:design_speed'))
        props=cfg.rail_properties({123:tags})
        self.assertEqual(props['osm_maxspeed'],140)
        self.assertEqual(props['osm_design_speed'],200)

    def test_legacy_and_line_level_official_design_never_propagate(self):
        cfg,tags,row,kind=self.evidence('de',dict(railway='rail',name='Schnellfahrstrecke Köln-Rhein/Main',maxspeed='160'))
        self.assertEqual(kind,'hs')
        self.assertEqual(cfg.speed_of('',kind,row),(160,True,'OSM:maxspeed'))
        self.assertNotIn('osm_design_speed',cfg.rail_properties({123:tags}))

    def test_unknown_design_is_not_fabricated(self):
        cfg,tags,row,kind=self.evidence('nl',dict(railway='rail',name='HSL-Zuid'))
        self.assertEqual(kind,'hs')
        self.assertIsNone(cfg.speed_of('',kind,row))

    def test_partial_mixed_name_never_gets_full_line_rule(self):
        for code,name in [('de','Schnellfahrstrecke Nürnberg-Erfurt'),('it','Ferrovia Milano-Verona AV/AC')]:
            _,tags,_,_=self.evidence(code,dict(railway='rail',name=name,maxspeed='300'))
            self.assertEqual(tags['_hsr_state'],'unresolved')

    def test_foreign_alias_and_structure_titles_do_not_match(self):
        for code,name in [('nl','HSL 4'),('de','Talbrücke Leinach'),('it','Galleria Fontanellato'),('be','HSL 4 [nl_lines.json]')]:
            _,tags,_,_=self.evidence(code,dict(railway='rail',name=name,maxspeed='300'))
            self.assertEqual(tags['_hsr_state'],'unresolved')

    def test_service_relation_does_not_assign_infrastructure(self):
        _,tags,_,_=self.evidence('nl',dict(railway='rail',maxspeed='200'),dict(type='route',route='train',name='Hanzelijn'))
        self.assertEqual(tags['_hsr_state'],'unresolved')
        _,tags,_,_=self.evidence('nl',dict(railway='rail',maxspeed='200'),dict(type='route',route='railway',name='Hanzelijn'))
        self.assertEqual(tags['_hsr_state'],'new_build')
        self.assertEqual(tags['_hsr_match'],'infrastructure_relation')

    def test_adopted_name_does_not_assign_identity(self):
        cfg,tags,row,_=self.evidence('nl',dict(railway='rail',maxspeed='140',usage='main'))
        self.assertEqual(cfg.kind_of('HSL-Zuid',row),'main')
        self.assertEqual(tags['_hsr_state'],'unresolved')

    def test_construction_stays_unresolved_and_separate(self):
        ex=self.extract(dict(railway='construction',construction='rail',name='HSL-Zuid',maxspeed='300'))
        self.registry.annotate(ex,'nl')
        self.assertEqual(ex['ways'][0][1]['_hsr_state'],'construction_unresolved')
        self.assertNotIn('_hsr_ids',ex['ways'][0][1])

    def test_preflight_composes_is_idempotent_and_preserves_original_geometry(self):
        cfg=self.raw_country('nl'); called=[]
        cfg.urban_preflight=lambda ex:called.append(ex)
        install(cfg,self.registry); wrapper=cfg.urban_preflight; install(cfg,self.registry)
        self.assertIs(cfg.urban_preflight,wrapper)
        ex=self.extract(dict(railway='rail',name='Hanzelijn'))
        co=ex['ways'][0][2]; cfg.urban_preflight(ex); first=json.dumps(ex,sort_keys=True);cfg.urban_preflight(ex)
        self.assertEqual(first,json.dumps(ex,sort_keys=True))
        self.assertIs(co,ex['ways'][0][2]);self.assertEqual(len(called),2)

    def test_stretches_do_not_mix_evidence_when_names_are_adopted(self):
        cfg=self.country('nl'); ex=self.extract(dict(railway='rail',name='HSL-Zuid',maxspeed='200'))
        cfg.urban_preflight(ex); tags=ex['ways'][0][1]
        unknown=dict(tags,_hsr_state='unresolved');unknown.pop('_hsr_ids');unknown.pop('_hsr_refs')
        self.assertNotEqual(cfg.stretch_of('HSL-Zuid',tags,[]),cfg.stretch_of('HSL-Zuid',unknown,[]))
        with self.assertRaises(ValueError):cfg.rail_properties({123:tags,124:unknown})

    def test_catalog_all_research_records_have_review_state(self):
        # the 80 researched for the seven countries (2026-10-17/18) and Austria's 3 (2026-10-21)
        rows=self.registry.data['records']
        self.assertEqual(len(rows),83)
        self.assertEqual(len({r['id'] for r in rows}),83)
        self.assertTrue(all(r['blockers'] and 'research' in r for r in rows))
        self.assertTrue(all(r['design_binding'] is None for r in rows))

    def test_country_railway_properties_emits_conventional_old_line(self):
        from country import railway_properties
        cfg=self.country('de')
        ex=self.extract(dict(railway='rail',name='Riedbahn',usage='main',highspeed='yes',maxspeed='200'))
        cfg.urban_preflight(ex)
        wid,tags,co=ex['ways'][0]
        st=cfg.stretch_of('Riedbahn',tags,co)
        props,fast=railway_properties(cfg,('rail',st,'Riedbahn'),[wid],{wid:(tags,co)},{wid:2.0})
        self.assertEqual((props['jk'],props['c']),('main','main'))
        self.assertEqual(props['source_way_ids'],'123')
        self.assertNotIn('d',props)
        self.assertNotIn('e',props)
        self.assertIsNone(fast)
        self.assertEqual(props['osm_maxspeed'],200)

    def test_typographic_normalization_is_not_fuzzy_identity(self):
        self.assertEqual(normal_name('A – B'),normal_name('A-B'))
        self.assertNotEqual(normal_name('LGV A'),normal_name('A'))
        with self.assertRaises(ValueError):uniform_tags(Counter({(('maxspeed','200'),):1,(('maxspeed','300'),):1}))


if __name__=='__main__':unittest.main()


class ListedNewBuildOnlyTests(unittest.TestCase):
    """2026-10-18: only listed new-build lines are high-speed; an unresolved way with a running
    limit of 200 or more is conventional, and structure or unnamed gaps inside a new line join it."""

    def test_unresolved_fast_way_is_conventional(self):
        import europe_hsr as eh
        self.assertEqual(eh.identity_kind({'_hsr_state': 'unresolved', 'usage': 'main'}, 'hs'), 'main')
        self.assertEqual(eh.identity_kind({'_hsr_state': 'unresolved'}, 'hs'), 'branch')
        self.assertEqual(eh.identity_kind({'_hsr_state': 'new_build'}, 'main'), 'hs')

    def _extract(self, middle_name, right_identity='de-00'):
        new = lambda i: {'railway': 'rail', 'name': 'NBS', '_hsr_state': 'new_build', '_hsr_ids': i, '_hsr_refs': 'u'}
        return {'ways': [(1, new('de-00'), [(0, 0), (0.01, 0)]),
                         (2, {'railway': 'rail', 'name': middle_name, '_hsr_state': 'unresolved'}, [(0.01, 0), (0.02, 0)]),
                         (3, new(right_identity), [(0.02, 0), (0.03, 0)])]}

    def test_tunnel_between_two_ends_of_one_new_line_joins_it(self):
        import europe_hsr as eh
        ex = self._extract('Euerwangtunnel')
        eh.Registry.between_new_build(None, ex)
        self.assertEqual(ex['ways'][1][1]['_hsr_state'], 'new_build')
        self.assertEqual(ex['ways'][1][1]['_hsr_match'], 'between_new_build')

    def test_gap_between_two_different_lines_or_a_named_line_stays_unresolved(self):
        import europe_hsr as eh
        for ex in (self._extract('Euerwangtunnel', right_identity='de-01'), self._extract('Berlin-Hamburger Bahn')):
            eh.Registry.between_new_build(None, ex)
            self.assertEqual(ex['ways'][1][1]['_hsr_state'], 'unresolved')
