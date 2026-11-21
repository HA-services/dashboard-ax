# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import add_restriction, AxCommon, PREFIX, group_field


@tagged('post_install', '-at_install', 'ax_dashboard_pro')
class TestSecurity(AxCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.viewer = cls.make_user(cls, 'ax_viewer', ['ax_dashboard_pro.group_ax_dashboard_user'])
        cls.builder = cls.make_user(cls, 'ax_builder', ['ax_dashboard_pro.group_ax_dashboard_builder'])
        cls.manager = cls.make_user(cls, 'ax_manager', ['ax_dashboard_pro.group_ax_dashboard_manager'])
        cls.outsider = cls.make_user(cls, 'ax_outsider', [])

    def _dash_by(self, user, **kw):
        vals = {'name': 'Private ' + user.login}
        vals.update(kw)
        return self.env['ax.dashboard'].with_user(user).create(vals)

    def test_group_hierarchy(self):
        self.assertTrue(self.builder.has_group('ax_dashboard_pro.group_ax_dashboard_user'))
        self.assertTrue(self.manager.has_group('ax_dashboard_pro.group_ax_dashboard_builder'))
        self.assertFalse(self.viewer.has_group('ax_dashboard_pro.group_ax_dashboard_builder'))

    def test_viewer_cannot_create_or_edit(self):
        with self.assertRaises(AccessError):
            self.env['ax.dashboard'].with_user(self.viewer).create({'name': 'nope'})
        shared = self._dash_by(self.builder, user_ids=[(6, 0, [self.viewer.id])])
        with self.assertRaises(AccessError):
            shared.with_user(self.viewer).write({'name': 'hacked'})
        with self.assertRaises(AccessError):
            self.env['ax.dashboard.item'].with_user(self.viewer).create({'name': 'x', 'dashboard_id': shared.id})

    def test_private_dashboard_is_invisible(self):
        private = self._dash_by(self.builder)
        found = self.env['ax.dashboard'].with_user(self.viewer).search([('id', '=', private.id)])
        self.assertFalse(found)
        found = self.env['ax.dashboard'].with_user(self.manager).search([('id', '=', private.id)])
        self.assertTrue(found)

    def test_sharing_by_user_and_group(self):
        d = self._dash_by(self.builder, user_ids=[(6, 0, [self.viewer.id])])
        self.assertTrue(self.env['ax.dashboard'].with_user(self.viewer).search([('id', '=', d.id)]))
        g = self.env.ref('ax_dashboard_pro.group_ax_dashboard_manager')
        d2 = self._dash_by(self.builder, group_ids=[(6, 0, [g.id])])
        self.assertTrue(self.env['ax.dashboard'].with_user(self.manager).search([('id', '=', d2.id)]))
        self.assertFalse(self.env['ax.dashboard'].with_user(self.viewer).search([('id', '=', d2.id)]))

    def test_sharing_with_everyone_is_explicit(self):
        # a dashboard with no sharing is private to its owner and managers, never public by accident
        d = self._dash_by(self.builder)
        self.assertEqual(self.env['ax.dashboard'].with_user(self.viewer).search_count([('id', '=', d.id)]), 0)
        d.shared_all = True
        self.assertEqual(self.env['ax.dashboard'].with_user(self.viewer).search_count([('id', '=', d.id)]), 1)
        self.assertEqual(d.share_summary, 'Everyone with dashboard access')

    def test_editor_list_gives_edit_rights(self):
        d = self._dash_by(self.builder, user_ids=[(6, 0, [self.manager.id])], edit_user_ids=[(6, 0, [self.manager.id])])
        d.with_user(self.manager).write({'description': 'edited'})
        self.assertEqual(d.description, 'edited')

    def test_outsider_has_no_access_at_all(self):
        with self.assertRaises(AccessError):
            self.env['ax.dashboard'].with_user(self.outsider).search([])

    def test_data_respects_record_rules(self):
        """The numbers are computed with the viewer's own rights: a rule that hides rows changes the totals."""
        item = self.make_item(item_type='kpi', aggregate='count')
        item.dashboard_id.write({'user_ids': [(6, 0, [self.viewer.id])]})
        before = item.with_user(self.viewer).get_data(self.ALL)['value']
        self.assertEqual(before, 6)
        be = self.env.ref('base.be')
        add_restriction(self.env, 'test: only BE partners', 'base.model_res_partner', "[('country_id', '=', %d)]" % be.id)
        after = item.with_user(self.viewer).get_data(self.ALL)
        self.assertFalse(after.get('error'))
        self.assertEqual(after['value'], 2)

    def test_chart_hides_rows_without_access(self):
        item = self.make_item(item_type='chart', chart_type='bar', groupby='country_id', aggregate='count')
        item.dashboard_id.write({'user_ids': [(6, 0, [self.viewer.id])]})
        fr = self.env.ref('base.fr')
        add_restriction(self.env, 'test: no FR', 'base.model_res_partner', "[('country_id', '!=', %d)]" % fr.id)
        res = item.with_user(self.viewer).get_data(self.ALL)
        self.assertFalse(res.get('error'), res.get('error'))
        self.assertNotIn('France', res['labels'])

    def test_model_without_read_access_returns_error_not_data(self):
        model = self.env['ir.model']._get('ir.cron')
        item = self.env['ax.dashboard.item'].create({'name': 'cron', 'dashboard_id': self.dash.id, 'item_type': 'kpi', 'model_id': model.id,
                                                      'aggregate': 'count'})
        self.dash.write({'user_ids': [(6, 0, [self.viewer.id])]})
        res = item.with_user(self.viewer).get_data(self.ALL)
        self.assertTrue(res.get('error'))
        self.assertNotIn('value', res)

    def test_quick_update_whitelist(self):
        item = self.make_item()
        item.quick_update({'name': 'Renamed', 'kpi_color': '#ff0000'})
        self.assertEqual(item.name, 'Renamed')
        with self.assertRaises(AccessError):
            item.quick_update({'domain': '[]'})
        with self.assertRaises(AccessError):
            item.quick_update({'sql_query': 'select 1'})

    def test_builder_cannot_create_sql_items(self):
        d = self._dash_by(self.builder)
        model = self.env['ir.model']._get('res.partner')
        with self.assertRaises(UserError):
            self.env['ax.dashboard.item'].with_user(self.builder).create({
                'name': 'sql', 'dashboard_id': d.id, 'item_type': 'list', 'source_type': 'sql', 'sql_query': 'SELECT 1 AS a'})

    def test_connection_secrets_are_manager_only(self):
        conn = self.env['ax.dashboard.connection'].create({'name': 'c', 'conn_type': 'api', 'base_url': 'https://example.com', 'auth_value': 'Bearer secret'})
        with self.assertRaises(AccessError):
            conn.with_user(self.builder).read(['auth_value'])
        with self.assertRaises(AccessError):
            self.env['ax.dashboard.connection'].with_user(self.builder).create({'name': 'x'})
        self.assertEqual(conn.with_user(self.manager).auth_value, 'Bearer secret')

    def test_preferences_and_bookmarks_are_per_user(self):
        d = self._dash_by(self.builder, user_ids=[(6, 0, [self.viewer.id])])
        Pref = self.env['ax.dashboard.pref']
        Pref.with_user(self.viewer).set_pref(d.id, {'hide_values': True})
        self.assertTrue(Pref.with_user(self.viewer).get_prefs(d.id).get('hide_values'))
        self.assertFalse(Pref.with_user(self.builder).get_prefs(d.id).get('hide_values'))
        # unknown keys are ignored
        Pref.with_user(self.viewer).set_pref(d.id, {'evil': 1})
        self.assertNotIn('evil', Pref.with_user(self.viewer).get_prefs(d.id))
        # no preferences on a dashboard you cannot see
        private = self._dash_by(self.builder, name='hidden')
        with self.assertRaises(AccessError):
            Pref.with_user(self.viewer).set_pref(private.id, {'theme': 'light'})

    def test_personal_layout_does_not_change_the_shared_one(self):
        d = self._dash_by(self.builder, user_ids=[(6, 0, [self.viewer.id])])
        item = self.make_item(dash=d, name='moveme')
        x0 = item.grid_x
        d.with_user(self.viewer).save_layout([{'id': item.id, 'x': 6, 'y': 9, 'w': 3, 'h': 2}], personal=True)
        self.assertEqual(item.grid_x, x0)
        mine = d.with_user(self.viewer).load_dashboard()['items'][0]
        self.assertEqual((mine['x'], mine['y']), (6, 9))
        with self.assertRaises(AccessError):
            d.with_user(self.viewer).save_layout([{'id': item.id, 'x': 1, 'y': 1, 'w': 1, 'h': 1}], personal=False)

    def test_multi_company_rule(self):
        other = self.env['res.company'].create({'name': 'Other co'})
        d = self.env['ax.dashboard'].create({'name': 'Other company only', 'company_id': other.id})
        main_user = self.env['ax.dashboard'].with_user(self.manager)
        self.assertFalse(main_user.search([('id', '=', d.id)]))
        self.manager.write({'company_ids': [(4, other.id)]})
        self.assertTrue(self.env['ax.dashboard'].with_user(self.manager).with_context(allowed_company_ids=[other.id]).search([('id', '=', d.id)]))

    def test_comments_only_on_visible_dashboards(self):
        private = self._dash_by(self.builder, name='private2')
        with self.assertRaises(AccessError):
            self.env['ax.dashboard.comment'].with_user(self.viewer).post(private.id, 'hello')

    def test_builder_can_pick_models_and_fields(self):
        Model = self.env['ir.model'].with_user(self.builder)
        model = Model.search([('model', '=', 'res.partner')])
        self.assertTrue(model)
        fields_ = self.env['ir.model.fields'].with_user(self.builder).search([('model_id', '=', model.id), ('name', '=', 'country_id')])
        self.assertTrue(fields_)
        d = self._dash_by(self.builder, name='Builder work')
        item = self.env['ax.dashboard.item'].with_user(self.builder).create({
            'name': 'Mine', 'dashboard_id': d.id, 'item_type': 'chart', 'chart_type': 'bar', 'model_id': model.id,
            'groupby_field_id': fields_.id, 'aggregate': 'count'})
        res = item.get_data({'preset': 'all'})
        self.assertFalse(res.get('error'), res.get('error'))
        self.assertTrue(res['labels'])
        with self.assertRaises(AccessError):
            Model.create({'name': 'x', 'model': 'x_x'})
