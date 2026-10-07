import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fetch_design_catalog import facts


def html(notes='', design='380', track='350'):
    return BeautifulSoup('''<div class="border-radius-xs shadow-xs position-r">
      <div class="font-small">京沪高速线</div><div class="title-label">京沪高速铁路</div>
      <div class="text-blue">北京南~上海虹桥</div>''' + notes +
      ''.join('<div class="para"><div class="para-N">' + value + '</div><div class="para-M">' + label + '</div></div>'
              for label, value in [('线下设计速度', design), ('线上设计速度', track), ('最高运行速度', '350')]) + '</div>', 'html.parser')


class CatalogueFields(unittest.TestCase):
    def read(self, soup):
        with patch('fetch_design_catalog.page', return_value=soup):
            return facts('https://www.china-emu.cn/RailRoads/Line/?LineName=京沪高速铁路')['sections'][0]

    def test_design_and_operation_are_separate(self):
        s = self.read(html())
        self.assertEqual(s['design'], 380)
        self.assertEqual(s['design_track'], 350)
        self.assertEqual(s['operating'], 350)

    def test_actual_and_planned_opening_records_are_distinct(self):
        s = self.read(html('<div class="bg-faded">2011-06-30开通。预计2027年12月1日开通。</div>'))
        self.assertEqual(s['events'], [{'date': '2011-06-30', 'event': 'opened', 'planned': False},
                                     {'date': '2027-12-01', 'event': 'opened', 'planned': True}])

    def test_invalid_dates_are_ignored(self):
        s = self.read(html('<div class="bg-faded">2026-02-31开通。</div>'))
        self.assertEqual(s['events'], [])

    def test_scope_caveat_in_second_note_is_detected(self):
        s = self.read(html('<div class="bg-faded text-info">已开通。</div><div class="bg-faded text-info">设计速度200km/h路段为兰棱-五家。</div>'))
        self.assertTrue(s['requires_review'])

    def test_red_notice_contains_a_scope_caveat(self):
        s = self.read(html('<div class="bg-faded text-danger">当前无动车服务。设计速度200km/h路段为兰棱-五家。</div>'))
        self.assertTrue(s['requires_review'])

    def test_trial_speed_caveat_does_not_erase_a_design_scope(self):
        s = self.read(html('<div class="bg-faded text-info">青神-乐山线下、线上设计速度为350、300km/h；最高试验速度暂无来源，仅供参考。</div>'))
        self.assertTrue(s['requires_review'])
        self.assertEqual(s['design_track'], 350)

    def test_design_range_is_not_promoted_to_its_maximum(self):
        s = self.read(html(design='200~250', track=''))
        self.assertIsNone(s['design'])

    def test_unverified_track_value_does_not_replace_infrastructure(self):
        s = self.read(html('<div class="bg-faded text-info">线上设计速度暂无准确资料来源，仅供参考。</div>'))
        self.assertEqual(s['design'], 380)
        self.assertIsNone(s['design_track'])
        self.assertFalse(s['requires_review'])


if __name__ == '__main__':
    unittest.main()
