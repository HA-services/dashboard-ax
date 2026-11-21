# -*- coding: utf-8 -*-
import io
from datetime import date

import xlsxwriter

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import tagged

from ..models import filetable, safe
from .common import AxCommon, PREFIX, bin_value


@tagged('post_install', '-at_install')
class TestChartTypes(AxCommon):

    def _chart(self, ctype, **kw):
        return self.make_item(item_type='chart', chart_type=ctype, groupby='country_id', aggregate='sum', measure='color', **kw)

    def test_new_types_return_labels_and_values(self):
        for ctype in ('radar', 'funnel', 'flower', 'radial', 'bullet'):
            res = self.values(self._chart(ctype), self.ALL)
            self.assertEqual(sorted(res['labels']), ['Belgium', 'France', 'Germany'], ctype)
            self.assertEqual(res['chart_type'], ctype)

    def test_bullet_carries_the_target(self):
        item = self._chart('bullet', target_value=100)
        self.assertEqual(self.values(item)['target'], 100)

    def test_scatter_needs_a_second_measure_and_returns_points(self):
        res = self._chart('scatter').get_data(self.ALL)
        self.assertIn('second measure', res['error'])
        res = self.values(self._chart('scatter', measure2='id'), self.ALL)
        self.assertEqual(len(res['points']), 3)
        by = {p['label']: p for p in res['points']}
        self.assertEqual(by['Belgium']['x'], 30)

    def test_map_returns_country_codes(self):
        res = self.values(self._chart('map'), self.ALL)
        self.assertEqual(sorted(res['codes']), ['BE', 'DE', 'FR'])

    def test_map_rejects_a_non_country_field(self):
        item = self.make_item(item_type='chart', chart_type='map', groupby='function', aggregate='count')
        self.assertIn('country', item.get_data(self.ALL)['error'])

    def test_export_keeps_second_measure(self):
        item = self._chart('scatter', measure2='id')
        d = item.export_dict()
        d['code'] = False
        self.assertEqual(d['measure2'], 'id')
        vals, warn = self.env['ax.dashboard.item'].values_from_dict(d, self.dash)
        self.assertEqual(self.env['ax.dashboard.item'].create(vals).measure2_field_id.name, 'id')


@tagged('post_install', '-at_install')
class TestFileSource(AxCommon):
    CSV = b'Region,Sales,Units\nNorth,100,4\nSouth,250,6\nNorth,50,1\nWest,"1,000",10\n'

    def _file_item(self, content=CSV, name='sales.csv', **kw):
        vals = {'name': 'File', 'dashboard_id': self.dash.id, 'source_type': 'file', 'item_type': 'chart', 'chart_type': 'bar',
                'data_file': bin_value(content), 'data_filename': name, 'file_groupby': 'Region',
                'file_measure': 'Sales', 'aggregate': 'sum', 'sort_by': 'label', 'sort_dir': 'asc'}
        vals.update(kw)
        return self.env['ax.dashboard.item'].create(vals)

    def test_csv_chart(self):
        res = self.values(self._file_item())
        self.assertEqual(res['labels'], ['North', 'South', 'West'])
        self.assertEqual(res['datasets'][0]['data'], [150.0, 250.0, 1000.0])

    def test_aggregates(self):
        self.assertEqual(self.values(self._file_item(aggregate='avg'))['datasets'][0]['data'][0], 75.0)
        self.assertEqual(self.values(self._file_item(aggregate='count'))['datasets'][0]['data'][0], 2.0)
        self.assertEqual(self.values(self._file_item(aggregate='max'))['datasets'][0]['data'][2], 1000.0)

    def test_kpi_and_list(self):
        self.assertEqual(self.values(self._file_item(item_type='kpi', aggregate='sum', file_groupby=False))['value'], 1400.0)
        res = self.values(self._file_item(item_type='list', file_columns='Region,Units'))
        self.assertEqual([c['label'] for c in res['columns']], ['Region', 'Units'])
        self.assertEqual(len(res['rows']), 4)

    def test_xlsx(self):
        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {'in_memory': True})
        ws = wb.add_worksheet()
        for r, row in enumerate([['Region', 'Sales'], ['A', 5], ['B', 7], ['A', 1]]):
            for c, v in enumerate(row):
                ws.write(r, c, v)
        wb.close()
        res = self.values(self._file_item(buf.getvalue(), 'book.xlsx'))
        self.assertEqual(dict(zip(res['labels'], res['datasets'][0]['data'])), {'A': 6.0, 'B': 7.0})

    def test_map_from_codes(self):
        res = self.values(self._file_item(b'Country,Sales\nFR,5\nbe,3\n', 'c.csv', chart_type='map', file_groupby='Country'))
        self.assertEqual(sorted(c for c in res['codes'] if c), ['BE', 'FR'])

    def test_bad_column_is_reported(self):
        item = self._file_item(file_groupby='Nope')
        self.assertIn('Nope', item.get_data(self.ALL)['error'])

    def test_file_required(self):
        with self.assertRaises(ValidationError):
            self.env['ax.dashboard.item'].create({'name': 'x', 'dashboard_id': self.dash.id, 'source_type': 'file', 'item_type': 'kpi'})

    def test_limits(self):
        with self.assertRaises(UserError):
            filetable.read_table(bin_value(b'x' * (filetable.MAX_BYTES + 1)), 'a.csv')
        with self.assertRaises(UserError):
            filetable.read_table(bin_value(b'PK\x03\x04not a zip'), 'a.xlsx')

    def test_files_are_skipped_on_import(self):
        d = self._file_item().export_dict()
        vals, warn = self.env['ax.dashboard.item'].values_from_dict(d, self.dash)
        self.assertFalse(vals)
        self.assertTrue(warn)

    def test_file_content_is_builder_only(self):
        viewer = self.make_user('ax_file_viewer', ['ax_dashboard_pro.group_ax_dashboard_user'])
        item = self._file_item()
        with self.assertRaises(AccessError):
            item.with_user(viewer).sudo(False).read(['data_file'])


@tagged('post_install', '-at_install')
class TestDatesAndTokens(AxCommon):

    def test_next_ranges(self):
        today = date(2026, 11, 21)
        self.assertEqual(safe.date_range('next_day', today)[:2], (date(2026, 11, 22), date(2026, 11, 22)))
        self.assertEqual(safe.date_range('next_week', today)[:2], (date(2026, 11, 23), date(2026, 11, 29)))
        self.assertEqual(safe.date_range('next_month', today)[:2], (date(2026, 12, 1), date(2026, 12, 31)))
        self.assertEqual(safe.date_range('next_quarter', today)[:2], (date(2027, 1, 1), date(2027, 3, 31)))
        self.assertEqual(safe.date_range('next_year', today)[:2], (date(2027, 1, 1), date(2027, 12, 31)))

    def test_financial_year(self):
        today = date(2026, 11, 21)
        self.assertEqual(safe.date_range('this_fy', today)[:2], (date(2026, 1, 1), date(2026, 12, 31)))
        self.assertEqual(safe.date_range('last_fy', today)[:2], (date(2025, 1, 1), date(2025, 12, 31)))
        # a year ending 30 June
        self.assertEqual(safe.date_range('this_fy', today, fy_end=(6, 30))[:2], (date(2026, 7, 1), date(2027, 6, 30)))
        self.assertEqual(safe.date_range('last_fy', today, fy_end=(6, 30))[:2], (date(2025, 7, 1), date(2026, 6, 30)))

    def test_every_preset_resolves(self):
        for key in safe.PRESET_KEYS:
            if key != 'custom':
                safe.date_range(key, date(2026, 11, 21))
        self.assertGreaterEqual(len(safe.PRESETS), 20)

    def test_uid_and_company_tokens(self):
        item = self.make_item(domain="[('create_uid', '=', %UID), ('company_id', 'in', [False, %MYCOMPANY])]")
        self.assertEqual(item._eval_domain()[0], ('create_uid', '=', self.env.uid))
        self.assertEqual(item._eval_domain()[1][2], [False, self.env.company.id])


@tagged('post_install', '-at_install')
class TestMenuEntry(AxCommon):

    def test_manager_adds_and_removes_menu(self):
        mgr = self.make_user('ax_menu_mgr', ['ax_dashboard_pro.group_ax_dashboard_manager'])
        dash = self.env['ax.dashboard'].with_user(mgr).create({'name': 'In menu', 'show_in_menu': True})
        self.assertTrue(dash.menu_id)
        self.assertEqual(dash.menu_id.name, 'In menu')
        self.assertIn(str(dash.id), dash.menu_id.action.context)
        dash.write({'name': 'Renamed'})
        self.assertEqual(dash.menu_id.name, 'Renamed')
        menu = dash.menu_id
        dash.write({'show_in_menu': False})
        self.assertFalse(menu.exists())
        dash.write({'show_in_menu': True})
        menu = dash.menu_id
        dash.unlink()
        self.assertFalse(menu.exists())

    def test_builder_cannot_add_menu(self):
        builder = self.make_user('ax_menu_builder', ['ax_dashboard_pro.group_ax_dashboard_builder'])
        with self.assertRaises(AccessError):
            self.env['ax.dashboard'].with_user(builder).create({'name': 'Nope', 'show_in_menu': True})


@tagged('post_install', '-at_install')
class TestPlacement(AxCommon):

    def test_new_items_fill_the_row_before_starting_another(self):
        dash = self.env['ax.dashboard'].create({'name': 'Grid'})
        spots = []
        for i in range(5):
            item = self.env['ax.dashboard.item'].create({'name': 'K%d' % i, 'dashboard_id': dash.id, 'item_type': 'kpi', 'model_id': self.env.ref('base.model_res_partner').id, 'aggregate': 'count'})
            spots.append((item.grid_x, item.grid_y))
        self.assertEqual(spots, [(0, 0), (3, 0), (6, 0), (9, 0), (0, 2)])

    def test_a_gap_is_reused(self):
        dash = self.env['ax.dashboard'].create({'name': 'Grid2'})
        Item = self.env['ax.dashboard.item']
        model = self.env.ref('base.model_res_partner').id
        a = Item.create({'name': 'a', 'dashboard_id': dash.id, 'item_type': 'chart', 'chart_type': 'bar', 'model_id': model, 'aggregate': 'count',
                         'groupby_field_id': self.env['ir.model.fields']._get('res.partner', 'country_id').id, 'grid_x': 0, 'grid_y': 0, 'grid_w': 6, 'grid_h': 4})
        Item.create({'name': 'b', 'dashboard_id': dash.id, 'item_type': 'kpi', 'model_id': model, 'aggregate': 'count', 'grid_x': 6, 'grid_y': 0, 'grid_w': 6, 'grid_h': 2})
        c = Item.create({'name': 'c', 'dashboard_id': dash.id, 'item_type': 'kpi', 'model_id': model, 'aggregate': 'count'})
        self.assertEqual((c.grid_x, c.grid_y), (6, 2))
