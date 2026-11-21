# -*- coding: utf-8 -*-
import json

from odoo.tests import HttpCase, tagged

from .common import MODEL, PREFIX, group_field


@tagged('post_install', '-at_install', 'ax_dashboard_pro')
class TestRoutes(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        gf = group_field(env)

        def user(login, xmlids):
            return env['res.users'].with_context(no_reset_password=True).create({
                'name': login, 'login': login, 'password': login, 'email': login + '@example.com',
                gf: [(6, 0, [env.ref(x).id for x in ['base.group_user'] + xmlids])]})
        cls.viewer = user('ax_http_viewer', ['ax_dashboard_pro.group_ax_dashboard_user'])
        cls.outsider = user('ax_http_outsider', [])
        cls.dash = env['ax.dashboard'].create({'name': 'Route test', 'user_ids': [(6, 0, [cls.viewer.id])]})
        model = env['ir.model']._get(MODEL)
        cls.item = env['ax.dashboard.item'].create({'name': 'Rows', 'dashboard_id': cls.dash.id, 'item_type': 'kpi', 'model_id': model.id, 'aggregate': 'count'})
        cls.chart = env['ax.dashboard.item'].create({'name': 'By country', 'dashboard_id': cls.dash.id, 'item_type': 'chart', 'chart_type': 'bar', 'model_id': model.id,
                                                      'groupby_field_id': env['ir.model.fields']._get(MODEL, 'country_id').id, 'aggregate': 'count'})
        cls.private = env['ax.dashboard'].create({'name': 'Not shared'})
        cls.private_item = env['ax.dashboard.item'].create({'name': 'Secret', 'dashboard_id': cls.private.id, 'item_type': 'kpi', 'model_id': model.id, 'aggregate': 'count'})

    def _get(self, path):
        return self.url_open(path, allow_redirects=False)

    def test_anonymous_is_sent_to_login(self):
        res = self._get('/ax_dashboard/item/%s/xlsx' % self.item.id)
        self.assertIn(res.status_code, (301, 302, 303, 307, 308, 401, 403))

    def test_viewer_downloads_exports(self):
        self.authenticate('ax_http_viewer', 'ax_http_viewer')
        res = self._get('/ax_dashboard/item/%s/xlsx' % self.chart.id)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.content.startswith(b'PK'))
        self.assertIn('spreadsheetml', res.headers['Content-Type'])
        res = self._get('/ax_dashboard/item/%s/csv' % self.chart.id)
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res.headers['Content-Type'])
        res = self._get('/ax_dashboard/item/%s/pdf' % self.chart.id)
        self.assertTrue(res.content.startswith(b'%PDF'))
        self.assertIn('attachment', res.headers['Content-Disposition'])

    def test_dashboard_exports_with_filters(self):
        self.authenticate('ax_http_viewer', 'ax_http_viewer')
        q = '?filters=' + json.dumps({'preset': 'last_30'})
        for fmt, magic in (('xlsx', b'PK'), ('pdf', b'%PDF')):
            res = self._get('/ax_dashboard/dashboard/%s/%s%s' % (self.dash.id, fmt, q))
            self.assertEqual(res.status_code, 200, fmt)
            self.assertTrue(res.content.startswith(magic), fmt)

    def test_unshared_dashboard_is_not_downloadable(self):
        self.authenticate('ax_http_viewer', 'ax_http_viewer')
        self.assertEqual(self._get('/ax_dashboard/item/%s/xlsx' % self.private_item.id).status_code, 404)
        self.assertEqual(self._get('/ax_dashboard/dashboard/%s/pdf' % self.private.id).status_code, 404)

    def test_user_without_dashboard_role_is_refused(self):
        self.authenticate('ax_http_outsider', 'ax_http_outsider')
        self.assertEqual(self._get('/ax_dashboard/item/%s/xlsx' % self.item.id).status_code, 404)

    def test_bad_formats_and_ids(self):
        self.authenticate('ax_http_viewer', 'ax_http_viewer')
        self.assertEqual(self._get('/ax_dashboard/item/%s/exe' % self.item.id).status_code, 404)
        self.assertEqual(self._get('/ax_dashboard/item/99999999/xlsx').status_code, 404)
        res = self._get('/ax_dashboard/item/%s/csv?filters=%%7Bbroken' % self.item.id)
        self.assertEqual(res.status_code, 200)

    def test_template_download_is_json(self):
        self.authenticate('admin', 'admin')
        tpl = self.env['ax.dashboard.template'].search([], limit=1)
        res = self._get('/ax_dashboard/template/%s/download' % tpl.id)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(json.loads(res.content)['format'], 'axsync_dashboard')
