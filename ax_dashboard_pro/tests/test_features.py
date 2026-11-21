# -*- coding: utf-8 -*-
import base64
import json

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.ax_dashboard_pro.models.compat import set_param
from .common import AxCommon, PREFIX


@tagged('post_install', '-at_install', 'ax_dashboard_pro')
class TestFeatures(AxCommon):

    def _full_dashboard(self):
        d = self.env['ax.dashboard'].create({'name': 'Full', 'theme': 'ocean', 'default_date_preset': 'last_90', 'refresh_seconds': 60})
        self.env['ax.dashboard.filter'].create({'dashboard_id': d.id, 'name': 'Country', 'field_name': 'country_id'})
        self.make_item(dash=d, name='Rows', aggregate='count', code='rows', target_value=10, compare_mode='previous_period', kpi_color='#112233')
        self.make_item(dash=d, name='By country', item_type='chart', chart_type='doughnut', groupby='country_id', aggregate='sum', measure='color', drill_path='function')
        self.make_item(dash=d, name='Rows list', item_type='list', list_fields=['name', 'color'], list_order='name asc')
        self.env['ax.dashboard.item'].create({'name': 'Todo', 'dashboard_id': d.id, 'item_type': 'todo',
                                               'todo_line_ids': [(0, 0, {'name': 'Call the bank'})]})
        return d

    # ---- export and import
    def test_export_import_round_trip(self):
        d = self._full_dashboard()
        text = d.export_json()
        data = json.loads(text)
        self.assertEqual(data['format'], 'axsync_dashboard')
        self.assertEqual(len(data['items']), 4)
        new, warnings = self.env['ax.dashboard'].import_json(text)
        self.assertFalse(warnings)
        self.assertNotEqual(new, d)
        self.assertEqual(new.theme, 'ocean')
        self.assertEqual(new.refresh_seconds, 60)
        self.assertEqual(len(new.item_ids), 4)
        self.assertEqual(len(new.filter_ids), 1)
        rows = new.item_ids.filtered(lambda i: i.name == 'Rows')
        self.assertEqual((rows.target_value, rows.kpi_color, rows.compare_mode), (10, '#112233', 'previous_period'))
        self.assertEqual(self.values(rows)['value'], 6)
        self.assertEqual(new.item_ids.filtered(lambda i: i.item_type == 'todo').todo_line_ids.name, 'Call the bank')

    def test_import_rejects_bad_files(self):
        for bad in ('not json', '[]', '{"format": "other"}', '{}'):
            with self.assertRaises(UserError):
                self.env['ax.dashboard'].import_json(bad)

    def test_import_skips_missing_models_and_fields(self):
        d = self._full_dashboard()
        data = json.loads(d.export_json())
        data['items'][0]['model'] = 'not.installed'
        data['items'][1]['groupby'] = 'no_such_field'
        new, warnings = self.env['ax.dashboard'].import_json(json.dumps(data))
        self.assertEqual(len(new.item_ids), 2)
        self.assertEqual(len(warnings), 2)

    def test_export_never_contains_sql_or_secrets(self):
        set_param(self.env, 'ax_dashboard_pro.allow_sql', 'True')
        d = self.env['ax.dashboard'].create({'name': 'S'})
        self.env['ax.dashboard.item'].create({'name': 'sql', 'dashboard_id': d.id, 'item_type': 'list', 'source_type': 'sql', 'sql_query': 'SELECT 1 AS secret_marker'})
        self.assertNotIn('secret_marker', d.export_json())
        new, warnings = self.env['ax.dashboard'].import_json(json.dumps(dict(json.loads(d.export_json()), items=[
            {'name': 'x', 'item_type': 'list', 'source_type': 'sql', 'sql_query': 'select 1'}])))
        self.assertFalse(new.item_ids)
        self.assertTrue(warnings)

    def test_import_wizard(self):
        d = self._full_dashboard()
        wiz = self.env['ax.dashboard.import.wizard'].create({'file': base64.b64encode(d.export_json().encode()).decode(), 'filename': 'd.json'})
        act = wiz.action_import()
        self.assertEqual(act['tag'], 'ax_dashboard_pro.client')
        bad = self.env['ax.dashboard.import.wizard'].create({'file': base64.b64encode(b'\xff\xfe').decode(), 'filename': 'x.json'})
        with self.assertRaises(UserError):
            bad.action_import()

    def test_duplicate(self):
        d = self._full_dashboard()
        d.shared_all = True
        act = d.action_duplicate()
        new = self.env['ax.dashboard'].browse(act['params']['dashboard_id'])
        self.assertEqual(len(new.item_ids), 4)
        self.assertFalse(new.shared_all, 'a copy starts private')

    def test_move_item_to_another_dashboard(self):
        d = self._full_dashboard()
        target = self.env['ax.dashboard'].create({'name': 'Target'})
        item = d.item_ids[0]
        self.env['ax.dashboard.move.wizard'].create({'item_id': item.id, 'dashboard_id': target.id}).action_move()
        self.assertEqual(item.dashboard_id, target)

    # ---- versions
    def test_versions_and_restore(self):
        d = self.env['ax.dashboard'].create({'name': 'Versioned'})
        self.make_item(dash=d, name='First')
        d._snapshot_version('first')
        v1 = self.env['ax.dashboard.version'].search([('dashboard_id', '=', d.id)], order='id desc', limit=1)
        self.assertEqual(len(json.loads(v1.data)['items']), 1)
        # edits within a minute are merged into the latest version, so age this one before changing things
        self.env.cr.execute("UPDATE ax_dashboard_version SET create_date = create_date - interval '5 minutes' WHERE id = %s", (v1.id,))
        v1.invalidate_recordset()
        self.make_item(dash=d, name='Second')
        d.item_ids.filtered(lambda i: i.name == 'First').write({'name': 'First renamed'})
        d.restore_version(v1.id)
        self.assertEqual(d.item_ids.mapped('name'), ['First'])
        notes = self.env['ax.dashboard.version'].search([('dashboard_id', '=', d.id)]).mapped('note')
        self.assertTrue(any('restor' in (n or '').lower() for n in notes))

    def test_version_cap(self):
        d = self.env['ax.dashboard'].create({'name': 'Cap'})
        Version = self.env['ax.dashboard.version']
        for i in range(45):
            Version.create({'dashboard_id': d.id, 'number': i + 10, 'data': json.dumps(d.export_dict()), 'user_id': self.env.uid})
        d.write({'description': 'x'})
        d._snapshot_version('trim')
        self.assertLessEqual(Version.search_count([('dashboard_id', '=', d.id)]), 41)

    def test_restore_other_dashboards_version_refused(self):
        a = self.env['ax.dashboard'].create({'name': 'A'})
        b = self.env['ax.dashboard'].create({'name': 'B'})
        b._snapshot_version('b')
        vb = self.env['ax.dashboard.version'].search([('dashboard_id', '=', b.id)], limit=1)
        with self.assertRaises(AccessError):
            a.restore_version(vb.id)

    # ---- templates
    def test_templates_create_working_dashboards(self):
        Template = self.env['ax.dashboard.template']
        self.assertGreaterEqual(Template.search_count([]), 8)
        built = 0
        for tpl in Template.search([]):
            if not tpl.available:
                continue
            dash, warnings = tpl.create_dashboard()
            built += 1
            for item in dash.item_ids:
                res = item.get_data({'preset': 'all'})
                self.assertFalse(res.get('error'), '%s / %s: %s' % (tpl.name, item.name, res.get('error')))
        self.assertTrue(built, 'no template could be built')

    def test_save_as_template_and_reuse(self):
        d = self._full_dashboard()
        act = d.action_save_as_template()
        tpl = self.env['ax.dashboard.template'].browse(act['res_id'])
        self.assertEqual(tpl.item_count, 4)
        self.assertTrue(tpl.available)
        new, _w = tpl.create_dashboard()
        self.assertEqual(len(new.item_ids), 4)

    def test_template_with_missing_model_is_flagged(self):
        tpl = self.env['ax.dashboard.template'].create({'name': 'Needs plugin', 'data': json.dumps({
            'format': 'axsync_dashboard', 'items': [{'name': 'x', 'item_type': 'kpi', 'model': 'no.such.model', 'aggregate': 'count'}]})})
        self.assertFalse(tpl.available)
        with self.assertRaises(UserError):
            tpl.create_dashboard()

    def test_template_group_sharing(self):
        grp = self.env.ref('base.group_system')
        tpl = self.env['ax.dashboard.template'].create({'name': 'Shared', 'group_xmlids': 'base.group_system', 'data': json.dumps({
            'format': 'axsync_dashboard', 'items': [{'name': 'x', 'item_type': 'kpi', 'model': 'res.partner', 'aggregate': 'count'}]})})
        dash, _w = tpl.create_dashboard()
        self.assertEqual(dash.group_ids, grp)

    # ---- collaboration, logs, preferences
    def test_comments_and_mentions(self):
        user = self.make_user('ax_mention', ['ax_dashboard_pro.group_ax_dashboard_user'])
        self.dash.write({'user_ids': [(4, user.id)]})
        self.env['ax.dashboard.comment'].post(self.dash.id, 'Please check @ax_mention')
        comments = self.env['ax.dashboard.comment'].list_for(self.dash.id)
        self.assertEqual(len(comments), 1)
        self.assertTrue(comments[0]['mine'])
        with self.assertRaises(UserError):
            self.env['ax.dashboard.comment'].post(self.dash.id, '   ')

    def test_activity_log(self):
        d = self.env['ax.dashboard'].create({'name': 'Logged'})
        d.write({'shared_all': True})
        actions = self.env['ax.dashboard.log'].search([('dashboard_id', '=', d.id)]).mapped('action')
        self.assertIn('create', actions)
        self.assertIn('share', actions)
        d.load_dashboard()
        self.assertIn('view', self.env['ax.dashboard.log'].search([('dashboard_id', '=', d.id)]).mapped('action'))

    def test_bookmarks(self):
        BM = self.env['ax.dashboard.bookmark']
        BM.save_bookmark(self.dash.id, 'Q1', {'preset': 'this_quarter'})
        listed = BM.list_for(self.dash.id)
        self.assertEqual(listed[0]['filters'], {'preset': 'this_quarter'})

    def test_todo_lines(self):
        item = self.env['ax.dashboard.item'].create({'name': 'Todo', 'dashboard_id': self.dash.id, 'item_type': 'todo'})
        item.add_todo('Write the report')
        line = item.todo_line_ids
        item.toggle_todo(line.id, True)
        self.assertTrue(line.done)
        res = item.get_data({})
        self.assertEqual(res['lines'][0]['name'], 'Write the report')
        item.remove_todo(line.id)
        self.assertFalse(item.todo_line_ids)

    def test_performance_is_recorded(self):
        item = self.make_item()
        item.get_data(self.ALL)
        item.invalidate_recordset()
        self.assertEqual(item.load_count, 1)
        set_param(self.env, 'ax_dashboard_pro.slow_ms', '0')
        item.get_data(self.ALL)
        self.assertTrue(self.env['ax.dashboard.perf'].search_count([('item_id', '=', item.id)]))

    def test_list_dashboards_and_context(self):
        self.dash.shared_all = True
        names = [d['name'] for d in self.env['ax.dashboard'].list_dashboards()]
        self.assertIn('Test dashboard', names)
        ctx = self.env['ax.dashboard'].user_context()
        self.assertTrue(ctx['can_build'])
        self.assertIn(['last_30', 'Last 30 days'], [list(p) for p in ctx['presets']])

    def test_load_dashboard_payload(self):
        d = self._full_dashboard()
        payload = d.load_dashboard()
        self.assertEqual(payload['name'], 'Full')
        self.assertEqual(len(payload['items']), 4)
        self.assertEqual(payload['filters'][0]['field'], 'country_id')
        self.assertEqual(payload['refresh_seconds'], 60)

    def test_layout_save_and_versioning(self):
        d = self._full_dashboard()
        item = d.item_ids[0]
        d.save_layout([{'id': item.id, 'x': 3, 'y': 5, 'w': 20, 'h': 0}])
        self.assertEqual((item.grid_x, item.grid_y, item.grid_w, item.grid_h), (3, 5, 12, 1))
        self.assertTrue(self.env['ax.dashboard.version'].search_count([('dashboard_id', '=', d.id)]))

    def test_manager_menu_actions(self):
        for name in ('action_open', 'action_view_versions', 'action_view_logs', 'action_view_comments', 'action_add_item'):
            act = getattr(self.dash, name)()
            self.assertTrue(act.get('type'))
