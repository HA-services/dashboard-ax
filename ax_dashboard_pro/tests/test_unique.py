# -*- coding: utf-8 -*-
from datetime import date, timedelta
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from ..models import connection as conn_mod
from ..models.compat import set_param
from .common import AxCommon, MODEL, PREFIX


@tagged('post_install', '-at_install')
class TestForecast(AxCommon):

    def _series(self, values, **kw):
        """Partners created one per month going back from last month, with color = value."""
        today = date.today().replace(day=15)
        start = today
        for i, v in enumerate(values):
            month = today.month - (len(values) - i)
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            p = self.env[MODEL].create({'name': PREFIX + 'F%d' % i, 'color': v})
            self.env.cr.execute('UPDATE res_partner SET create_date = %s WHERE id = %s', (date(year, month, 10).isoformat() + ' 12:00:00', p.id))
        self.env[MODEL].invalidate_model()
        return self.make_item(item_type='chart', chart_type=kw.pop('chart_type', 'line'), groupby='create_date', date_interval='month',
                              aggregate='sum', measure='color', date_field='create_date', domain="[('name', '=like', 'AXT F%')]", **kw)

    def test_forecast_extends_a_linear_trend(self):
        item = self._series([10, 20, 30, 40, 50, 60], forecast_periods=3)
        res = self.values(item, self.ALL)
        fc = [d for d in res['datasets'] if d.get('forecast')]
        self.assertEqual(len(fc), 1)
        data = fc[0]['data']
        self.assertEqual(len(data), len(res['labels']))
        self.assertEqual(res['forecast']['periods'], 3)
        self.assertEqual(data[-3:], [70.0, 80.0, 90.0])
        self.assertEqual(data[-4], 60)
        self.assertEqual(len(res['labels']) - len(res['domains']), 0)

    def test_forecast_off_by_default_and_for_other_types(self):
        item = self._series([10, 20, 30, 40])
        self.assertFalse([d for d in self.values(item)['datasets'] if d.get('forecast')])
        item.write({'forecast_periods': 2, 'chart_type': 'pie'})
        self.assertFalse([d for d in self.values(item)['datasets'] if d.get('forecast')])

    def test_forecast_needs_three_points_and_never_goes_negative(self):
        item = self._series([10, 20], forecast_periods=2)
        self.assertNotIn('forecast', self.values(item))
        item = self._series([100, 60, 30, 10], forecast_periods=4)
        fc = [d for d in self.values(item)['datasets'] if d.get('forecast')][0]['data']
        self.assertTrue(all(v >= 0 for v in fc if v is not None))

    def test_forecast_survives_export(self):
        item = self._series([10, 20, 30, 40], forecast_periods=2)
        exporter = self.env['ax.dashboard.exporter']
        data = item.get_data(self.ALL)
        self.assertTrue(exporter.to_xlsx([data], 'x'))
        self.assertTrue(exporter.to_pdf('x', [data], ''))
        self.assertTrue(exporter.to_csv(data))

    def test_forecast_setting_round_trips_through_export(self):
        item = self._series([10, 20, 30, 40], forecast_periods=4)
        self.assertEqual(item.export_dict()['forecast_periods'], 4)


@tagged('post_install', '-at_install')
class TestPacing(AxCommon):

    def test_pace_projects_a_running_period(self):
        today = date.today()
        first = today.replace(day=1)
        for i in range(3):
            p = self.env[MODEL].create({'name': PREFIX + 'P%d' % i, 'color': 10})
            self.env.cr.execute('UPDATE res_partner SET create_date = %s WHERE id = %s', (first.isoformat() + ' 08:00:00', p.id))
        self.env[MODEL].invalidate_model()
        item = self.make_item(aggregate='sum', measure='color', target_value=1000)
        res = item.get_data({'preset': 'this_month'})
        self.assertNotIn('error', res)
        nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        total = (nxt - first).days
        if today < nxt - timedelta(days=1):
            self.assertAlmostEqual(res['pace_value'], res['value'] * total / ((today - first).days + 1), places=1)
            self.assertAlmostEqual(res['pace_pct'], res['pace_value'] / 1000 * 100, delta=0.2)

    def test_no_pace_for_finished_periods_or_without_target(self):
        item = self.make_item(aggregate='count', target_value=5)
        self.assertNotIn('pace_pct', item.get_data({'preset': 'last_month'}))
        self.assertNotIn('pace_pct', item.get_data(self.ALL))
        item.target_value = 0
        self.assertNotIn('pace_pct', item.get_data({'preset': 'this_month'}))


@tagged('post_install', '-at_install')
class TestDrivers(AxCommon):

    def _data(self):
        env = self.env
        today = date.today()
        cur = today.replace(day=1) + timedelta(days=0)
        prev = (cur - timedelta(days=3)).replace(day=5)
        be, fr = env.ref('base.be'), env.ref('base.fr')
        specs = [('D1', be, 10, prev), ('D2', fr, 10, prev), ('D3', be, 10, cur), ('D4', be, 40, cur), ('D5', fr, 15, cur)]
        for name, country, color, when in specs:
            p = env[MODEL].create({'name': PREFIX + name, 'country_id': country.id, 'color': color})
            env.cr.execute('UPDATE res_partner SET create_date = %s WHERE id = %s', (when.isoformat() + ' 09:00:00', p.id))
        env[MODEL].invalidate_model()
        return self.make_item(aggregate='sum', measure='color', compare_mode='previous_period', groupby='country_id', domain="[('name', '=like', 'AXT D%')]")

    def test_drivers_rank_the_groups_behind_the_change(self):
        item = self._data()
        res = item.get_drivers({'preset': 'this_month'}, 'country_id')
        self.assertNotIn('error', res)
        self.assertEqual(res['field_name'], 'country_id')
        self.assertEqual(res['current'], 65)
        self.assertEqual(res['previous'], 20)
        self.assertEqual(res['delta'], 45)
        by = {d['label']: d for d in res['drivers']}
        self.assertEqual(by['Belgium']['delta'], 40)
        self.assertEqual(by['France']['delta'], 5)
        self.assertEqual(res['drivers'][0]['label'], 'Belgium')
        self.assertAlmostEqual(by['Belgium']['share'], 88.9, places=1)
        self.assertTrue(any(f['name'] == 'country_id' for f in res['fields']))

    def test_drivers_pick_a_field_automatically(self):
        item = self._data()
        res = item.get_drivers({'preset': 'this_month'})
        self.assertNotIn('error', res)
        self.assertTrue(res['drivers'])

    def test_drivers_refuse_all_time_and_averages(self):
        item = self._data()
        self.assertIn('date range', item.get_drivers(self.ALL)['error'])
        item.aggregate = 'avg'
        self.assertIn('error', item.get_drivers({'preset': 'this_month'}))

    def test_get_data_flags_eligible_items(self):
        item = self._data()
        self.assertTrue(item.get_data({'preset': 'this_month'})['can_drivers'])
        self.assertFalse(item.get_data(self.ALL)['can_drivers'])

    def test_drivers_use_the_viewers_rights(self):
        item = self._data()
        user = self.make_user('drv_user', ['ax_dashboard_pro.group_ax_dashboard_user'])
        self.dash.write({'shared_all': True})
        res = item.with_user(user).get_drivers({'preset': 'this_month'}, 'country_id')
        self.assertTrue('error' in res or res['drivers'])


@tagged('post_install', '-at_install')
class TestWebhook(AxCommon):

    def _alert_item(self):
        return self.make_item(aggregate='count', alert_enabled=True, use_alert_min=True, alert_min=100, snapshot_preset='all')

    def test_alert_posts_to_the_webhook(self):
        set_param(self.env, 'ax_dashboard_pro.alert_webhook', 'https://hooks.example.com/abc')
        calls = []

        def transport(method, url, headers, timeout, body=None):
            calls.append((method, url, body))
            return 200, 'ok'
        with patch.object(conn_mod, 'HTTP_TRANSPORT', transport):
            raised = self._alert_item().check_alerts()
        self.assertEqual(len(raised), 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'POST')
        self.assertIn('Test dashboard', calls[0][2])
        self.assertIn('below the minimum', calls[0][2])

    def test_a_failing_webhook_never_blocks_the_alert(self):
        set_param(self.env, 'ax_dashboard_pro.alert_webhook', 'https://hooks.example.com/abc')
        with patch.object(conn_mod, 'HTTP_TRANSPORT', lambda *a: (500, 'no')):
            raised = self._alert_item().check_alerts()
        self.assertEqual(len(raised), 1)

    def test_no_webhook_means_no_call(self):
        set_param(self.env, 'ax_dashboard_pro.alert_webhook', '')
        with patch.object(conn_mod, 'HTTP_TRANSPORT', lambda *a: self.fail('should not be called')):
            self.assertEqual(len(self._alert_item().check_alerts()), 1)

    def test_webhook_to_a_private_host_is_refused(self):
        with self.assertRaises(UserError):
            self.env['ax.dashboard.connection']._post_json('https://localhost/hook', {'text': 'x'})

    def test_settings_test_button(self):
        settings = self.env['res.config.settings'].create({'ax_alert_webhook': 'https://hooks.example.com/abc'})
        with patch.object(conn_mod, 'HTTP_TRANSPORT', lambda *a: (200, 'ok')):
            res = settings.action_ax_test_webhook()
        self.assertEqual(res['params']['type'], 'success')
        settings.ax_alert_webhook = ''
        with self.assertRaises(UserError):
            settings.action_ax_test_webhook()
