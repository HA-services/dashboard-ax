# -*- coding: utf-8 -*-
from datetime import date

from odoo.tests import tagged
from odoo.exceptions import UserError

from odoo.addons.ax_dashboard_pro.models import safe
from .common import AxCommon


@tagged('post_install', '-at_install', 'ax_dashboard_pro')
class TestEngine(AxCommon):

    # ---- KPI
    def test_kpi_count_sum_avg_min_max(self):
        self.assertEqual(self.values(self.make_item(aggregate='count'))['value'], 6)
        self.assertEqual(self.values(self.make_item(aggregate='sum', measure='color'))['value'], 155)
        self.assertAlmostEqual(self.values(self.make_item(aggregate='avg', measure='color'))['value'], 155 / 6.0)
        self.assertEqual(self.values(self.make_item(aggregate='max', measure='color'))['value'], 50)
        self.assertEqual(self.values(self.make_item(aggregate='min', measure='color'))['value'], 5)

    def test_kpi_date_filter_and_domain(self):
        self.assertEqual(self.values(self.make_item(aggregate='sum', measure='color'), self.JAN)['value'], 30)
        item = self.make_item(aggregate='count', domain="[('name', '=like', '%s%%'), ('country_id.code', '=', 'FR')]" % 'AXT ')
        self.assertEqual(self.values(item)['value'], 2)

    def test_kpi_previous_period_and_year(self):
        item = self.make_item(aggregate='sum', measure='color', compare_mode='previous_period')
        res = self.values(item, self.JAN)
        self.assertEqual(res['previous'], 5)          # December 2025
        self.assertEqual(res['change_pct'], 500.0)
        item.compare_mode = 'previous_year'
        res = self.values(item, self.JAN)
        self.assertEqual(res['previous'], 50)         # January 2025
        self.assertEqual(res['change_pct'], -40.0)

    def test_kpi_no_comparison_without_period(self):
        item = self.make_item(aggregate='count', compare_mode='previous_period')
        self.assertNotIn('previous', self.values(item, self.ALL))

    def test_kpi_target(self):
        item = self.make_item(aggregate='sum', measure='color', target_value=310.0)
        res = self.values(item)
        self.assertEqual(res['target_pct'], 50.0)

    def test_kpi_sparkline(self):
        res = self.values(self.make_item(aggregate='count'), {'preset': 'custom', 'date_from': '2026-01-01', 'date_to': '2026-02-28'})
        self.assertTrue(len(res.get('spark', [])) >= 2)

    # ---- charts
    def test_chart_group_by_many2one(self):
        item = self.make_item(item_type='chart', chart_type='bar', groupby='country_id', aggregate='sum', measure='color')
        res = self.values(item)
        data = dict(zip(res['labels'], res['datasets'][0]['data']))
        self.assertEqual(data['Belgium'], 30)
        self.assertEqual(data['France'], 70)
        self.assertEqual(data['Germany'], 55)

    def test_chart_sort_and_limit(self):
        item = self.make_item(item_type='chart', chart_type='hbar', groupby='country_id', aggregate='sum', measure='color',
                              sort_by='value', sort_dir='desc', limit=2)
        res = self.values(item)
        self.assertEqual(res['labels'], ['France', 'Germany'])
        item.write({'sort_dir': 'asc', 'limit': 0})
        self.assertEqual(self.values(item)['labels'], ['Belgium', 'Germany', 'France'])
        item.write({'sort_by': 'label', 'sort_dir': 'asc'})
        self.assertEqual(self.values(item)['labels'], ['Belgium', 'France', 'Germany'])

    def test_chart_date_buckets(self):
        item = self.make_item(item_type='chart', chart_type='line', groupby='create_date', date_interval='month', aggregate='count',
                              sort_by='label', sort_dir='asc')
        res = self.values(item)
        self.assertEqual(sum(res['datasets'][0]['data']), 6)
        self.assertEqual(len(res['labels']), 4)    # Jan 2025, Dec 2025, Jan 2026, Feb 2026

    def test_chart_every_type_returns_data(self):
        for ctype in ('bar', 'hbar', 'stacked', 'line', 'area', 'pie', 'doughnut', 'polar'):
            item = self.make_item(item_type='chart', chart_type=ctype, groupby='country_id', aggregate='count')
            res = self.values(item)
            self.assertEqual(res['chart_type'], ctype)
            self.assertEqual(sum(res['datasets'][0]['data']), 6, ctype)

    def test_chart_second_grouping_makes_series(self):
        item = self.make_item(item_type='chart', chart_type='stacked', groupby='country_id', groupby2='function', aggregate='count')
        res = self.values(item)
        self.assertEqual({d['label'] for d in res['datasets']}, {'sales', 'buyer'})
        self.assertTrue(res['stacked'])

    def test_chart_compare_previous_year_adds_series(self):
        item = self.make_item(item_type='chart', chart_type='line', groupby='create_date', date_interval='month', aggregate='count',
                              compare_mode='previous_year', sort_by='label', sort_dir='asc')
        res = self.values(item, {'preset': 'custom', 'date_from': '2026-01-01', 'date_to': '2026-02-28'})
        self.assertEqual(len(res['datasets']), 2)
        self.assertTrue(res['datasets'][1].get('compare'))

    def test_drill_down_and_up(self):
        item = self.make_item(item_type='chart', chart_type='bar', groupby='country_id', aggregate='count', drill_path='function')
        top = self.values(item)
        self.assertEqual(top['drill']['level'], 0)
        self.assertEqual(top['drill']['max'], 1)
        idx = top['labels'].index('France')
        sub = self.values(item, drill={'level': 1, 'domain': top['domains'][idx]})
        self.assertEqual(sub['drill']['level'], 1)
        self.assertEqual(sub['labels'], ['sales'])
        self.assertEqual(sub['datasets'][0]['data'], [2])

    def test_domains_open_the_right_records(self):
        item = self.make_item(item_type='chart', chart_type='bar', groupby='country_id', aggregate='count')
        res = self.values(item)
        idx = res['labels'].index('Belgium')
        found = self.env['res.partner'].search(res['domains'][idx] + [('name', '=like', 'AXT %')])
        self.assertEqual(sorted(found.mapped('name')), ['AXT A1', 'AXT A2'])

    # ---- lists
    def test_list_item(self):
        item = self.make_item(item_type='list', list_fields=['name', 'country_id', 'color'], list_order='color desc', limit=3)
        res = self.values(item)
        self.assertEqual([c['name'] for c in res['columns']], ['name', 'country_id', 'color'])
        self.assertEqual(len(res['rows']), 3)
        self.assertEqual(res['rows'][0]['cells'][0], 'AXT A5')

    def test_list_order_cannot_inject(self):
        item = self.make_item(item_type='list', list_fields=['name'], list_order='color desc')
        item.list_order = 'name; DROP TABLE res_partner'
        res = item.get_data(self.ALL)
        self.assertTrue(res.get('error') or res.get('rows') is not None)
        self.env.cr.execute("SELECT to_regclass('res_partner')")
        self.assertTrue(self.env.cr.fetchone()[0])

    # ---- formula
    def test_formula_item(self):
        a = self.make_item(name='A', aggregate='sum', measure='color', code='total')
        b = self.make_item(name='B', aggregate='count', code='rows')
        f = self.env['ax.dashboard.item'].create({'name': 'Avg', 'dashboard_id': self.dash.id, 'item_type': 'kpi',
                                                   'source_type': 'formula', 'formula': '{total} / {rows}'})
        self.assertAlmostEqual(self.values(f)['value'], 155 / 6.0)

    def test_formula_rejects_code(self):
        for bad in ('__import__("os").system("id")', '{x}.__class__', 'open("/etc/passwd")', '(lambda: 1)()', '1 if 2 else 3'):
            with self.assertRaises(UserError):
                safe.eval_formula(bad, {'x': 1})
        self.assertEqual(safe.eval_formula('({a} + {b}) * 2 % 5', {'a': 3, 'b': 4}), 4)
        self.assertEqual(safe.eval_formula('{a} / {b}', {'a': 3, 'b': 0}), 0)

    # ---- dates
    def test_date_presets(self):
        today = date(2026, 11, 21)
        s, e, ps, pe = safe.date_range('this_month', today)
        self.assertEqual((s, e), (date(2026, 11, 1), date(2026, 11, 30)))
        self.assertEqual((ps, pe), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(safe.date_range('last_month', today)[:2], (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(safe.date_range('this_quarter', today)[:2], (date(2026, 10, 1), date(2026, 12, 31)))
        self.assertEqual(safe.date_range('last_quarter', today)[:2], (date(2026, 7, 1), date(2026, 9, 30)))
        self.assertEqual(safe.date_range('this_year', today)[:2], (date(2026, 1, 1), date(2026, 12, 31)))
        self.assertEqual(safe.date_range('last_year', today)[:2], (date(2025, 1, 1), date(2025, 12, 31)))
        self.assertEqual(safe.date_range('ytd', today)[:2], (date(2026, 1, 1), today))
        self.assertEqual(safe.date_range('last_7', today)[:2], (date(2026, 11, 15), today))
        self.assertEqual(safe.date_range('last_30', today)[:2], (date(2026, 10, 23), today))
        self.assertEqual(safe.date_range('today', today)[:2], (today, today))
        self.assertEqual(safe.date_range('yesterday', today)[:2], (date(2026, 11, 20), date(2026, 11, 20)))
        self.assertEqual(safe.date_range('this_week', today)[:2], (date(2026, 11, 16), date(2026, 11, 22)))
        self.assertEqual(safe.date_range('all', today)[:2], (None, None))
        self.assertEqual(safe.date_range('custom', today, '2026-02-01', '2026-02-10')[:2], (date(2026, 2, 1), date(2026, 2, 10)))

    def test_leap_year_previous_year(self):
        s, e = safe.shift_year(date(2024, 2, 29), date(2024, 2, 29))
        self.assertEqual((s, e), (date(2023, 2, 28), date(2023, 2, 28)))

    # ---- formatting and meta
    def test_number_format_meta(self):
        item = self.make_item(aggregate='sum', measure='color', number_format='percent', decimals=1, prefix='~', suffix=' pts')
        meta = self.values(item)['meta']
        self.assertEqual((meta['format'], meta['decimals'], meta['prefix'], meta['suffix']), ('percent', 1, '~', ' pts'))

    def test_errors_are_returned_in_band(self):
        item = self.make_item(item_type='chart', chart_type='bar', groupby='country_id', aggregate='count')
        item.domain = "[('nonexistent_field', '=', 1)]"
        res = item.get_data(self.ALL)
        self.assertTrue(res.get('error'))

    def test_invalid_domain_is_refused(self):
        item = self.make_item()
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            item.domain = "[('name', '=', __import__('os'))]"

    def test_item_positions_do_not_overlap_when_added(self):
        a = self.make_item(name='one')
        b = self.make_item(name='two')
        self.assertNotEqual((a.grid_x, a.grid_y), (b.grid_x, b.grid_y))

    def test_dashboard_filters(self):
        self.env['ax.dashboard.filter'].create({'dashboard_id': self.dash.id, 'name': 'Country', 'field_name': 'country_id'})
        item = self.make_item(aggregate='count')
        flt = self.dash.filter_ids[0]
        be = self.env.ref('base.be').id
        res = self.values(item, {'preset': 'all', 'fields': {str(flt.id): be}})
        self.assertEqual(res['value'], 2)
        opts = flt.get_options('Belg')
        self.assertTrue(any(o['id'] == be for o in opts))
