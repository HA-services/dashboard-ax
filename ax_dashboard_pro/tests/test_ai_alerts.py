# -*- coding: utf-8 -*-
import base64
import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.ax_dashboard_pro.models import ai as ai_mod
from odoo.addons.ax_dashboard_pro.models.compat import set_param
from .common import add_restriction, AxCommon

GOOD = {'name': 'Contacts overview', 'items': [
    {'name': 'Contacts', 'item_type': 'kpi', 'model': 'res.partner', 'aggregate': 'count'},
    {'name': 'By country', 'item_type': 'chart', 'chart_type': 'bar', 'model': 'res.partner', 'groupby': 'country_id'},
    {'name': 'Ghost', 'item_type': 'kpi', 'model': 'res.partner', 'aggregate': 'sum', 'measure': 'ghost_field'},
    {'name': 'Nope', 'item_type': 'kpi', 'model': 'not.a.model'},
]}


def fake(answer, status=200, sink=None, provider='openai'):
    def transport(method, url, headers, payload, timeout):
        if sink is not None:
            sink.append((url, headers, json.loads(payload)))
        if provider == 'anthropic':
            return status, json.dumps({'content': [{'type': 'text', 'text': answer}]})
        return status, json.dumps({'choices': [{'message': {'content': answer}}]})
    return transport


@tagged('post_install', '-at_install', 'ax_dashboard_pro')
class TestAI(AxCommon):
    """The AI layer is verified against a mock transport: no provider is contacted."""

    def _configure(self, provider='openai'):
        icp = self.env['ir.config_parameter'].sudo()
        set_param(self.env, 'ax_dashboard_pro.ai_api_key', 'sk-test')
        set_param(self.env, 'ax_dashboard_pro.ai_provider', provider)
        set_param(self.env, 'ax_dashboard_pro.ai_model', 'test-model')

    def test_not_configured(self):
        set_param(self.env, 'ax_dashboard_pro.ai_api_key', '')
        with self.assertRaises(UserError):
            self.env['ax.dashboard.ai'].generate_dashboard('sales by month for my customers')
        self.assertFalse(self.env['ax.dashboard'].user_context()['ai_enabled'])

    def test_generate_dashboard_keeps_valid_items_and_reports_the_rest(self):
        self._configure()
        sink = []
        with patch.object(ai_mod, 'AI_TRANSPORT', fake('Here you go:\n' + json.dumps(GOOD), sink=sink)):
            dash, warnings = self.env['ax.dashboard.ai'].generate_dashboard('contacts by country as a chart')
        self.assertEqual(dash.name, 'Contacts overview')
        self.assertEqual(sorted(dash.item_ids.mapped('name')), ['By country', 'Contacts'])
        self.assertEqual(len(warnings), 2)
        self.assertTrue(sink[0][0].endswith('/chat/completions'))
        self.assertEqual(sink[0][1]['Authorization'], 'Bearer sk-test')
        self.assertIn('res.partner', sink[0][2]['messages'][1]['content'])

    def test_anthropic_provider_request_shape(self):
        self._configure('anthropic')
        sink = []
        with patch.object(ai_mod, 'AI_TRANSPORT', fake(json.dumps(GOOD), sink=sink, provider='anthropic')):
            dash, _w = self.env['ax.dashboard.ai'].generate_dashboard('contacts by country as a chart')
        self.assertTrue(sink[0][0].endswith('/v1/messages'))
        self.assertEqual(sink[0][1]['x-api-key'], 'sk-test')
        self.assertTrue(dash.item_ids)

    def test_generated_domain_cannot_run_code(self):
        self._configure()
        evil = {'name': 'Evil', 'items': [{'name': 'E', 'item_type': 'kpi', 'model': 'res.partner', 'domain': "[('name', '=', __import__('os').system('id'))]"}]}
        with patch.object(ai_mod, 'AI_TRANSPORT', fake(json.dumps(evil))):
            with self.assertRaises(UserError):
                self.env['ax.dashboard.ai'].generate_dashboard('something with contacts please')

    def test_bad_answers(self):
        self._configure()
        AI = self.env['ax.dashboard.ai']
        for answer in ('I cannot help with that', '{"items": []}', '{bad json}'):
            with patch.object(ai_mod, 'AI_TRANSPORT', fake(answer)):
                with self.assertRaises(UserError):
                    AI.generate_dashboard('contacts by country as a chart')
        with patch.object(ai_mod, 'AI_TRANSPORT', fake('x', status=401)):
            with self.assertRaises(UserError):
                AI.generate_dashboard('contacts by country as a chart')
        with self.assertRaises(UserError):
            AI.generate_dashboard('hi')

    def test_generate_item_and_wizard(self):
        self._configure()
        one = {'name': 'Rows', 'item_type': 'kpi', 'model': 'res.partner', 'aggregate': 'count'}
        wiz = self.env['ax.dashboard.ai.wizard'].create({'mode': 'item', 'dashboard_id': self.dash.id, 'prompt': 'count the contacts'})
        with patch.object(ai_mod, 'AI_TRANSPORT', fake(json.dumps(one))):
            act = wiz.action_generate()
        self.assertEqual(act['tag'], 'ax_dashboard_pro.client')
        self.assertIn('Rows', self.dash.item_ids.mapped('name'))

    def test_summarise_item_sends_only_the_numbers(self):
        self._configure()
        item = self.make_item(item_type='chart', chart_type='bar', groupby='country_id', aggregate='count')
        sink = []
        with patch.object(ai_mod, 'AI_TRANSPORT', fake('France leads with two contacts.', sink=sink)):
            text = item.ai_insight(self.ALL)
        self.assertEqual(text, 'France leads with two contacts.')
        sent = sink[0][2]['messages'][1]['content']
        self.assertIn('France', sent)
        self.assertNotIn('sk-test', sent)

    def test_catalog_lists_only_readable_models(self):
        viewer = self.make_user('ax_cat', ['ax_dashboard_pro.group_ax_dashboard_builder'])
        catalog = self.env['ax.dashboard.ai'].with_user(viewer)._catalog('partners and cron jobs and users')
        self.assertIn('res.partner', catalog)
        self.assertNotIn('ir.cron', catalog)
        self.assertNotIn('password', catalog)


@tagged('post_install', '-at_install', 'ax_dashboard_pro')
class TestAlerts(AxCommon):

    def _kpi(self, **kw):
        vals = dict(aggregate='count', alert_enabled=True)
        vals.update(kw)
        return self.make_item(**vals)

    def test_threshold_alerts_and_dedupe(self):
        item = self._kpi(use_alert_min=True, alert_min=10.0, use_alert_max=True, alert_max=100.0)
        low = item.check_alerts(5.0)
        self.assertEqual([a.kind for a in low], ['below'])
        self.assertEqual(item.check_alerts(5.0), [], 'the same alert is not raised twice within 24 hours')
        high = item.check_alerts(500.0)
        self.assertEqual([a.kind for a in high], ['above'])
        self.assertEqual(item.check_alerts(50.0), [])

    def test_alert_repeats_after_a_day(self):
        item = self._kpi(use_alert_min=True, alert_min=10.0)
        alert = item.check_alerts(1.0)[0]
        self.env.cr.execute("UPDATE ax_dashboard_alert SET create_date = %s WHERE id = %s", (fields.Datetime.now() - timedelta(hours=30), alert.id))
        self.assertEqual(len(item.check_alerts(1.0)), 1)

    def test_alert_notifies_recipients(self):
        user = self.make_user('ax_alertee', ['ax_dashboard_pro.group_ax_dashboard_user'])
        item = self._kpi(use_alert_max=True, alert_max=1.0)
        item.alert_user_ids = [(6, 0, [user.id])]
        item.check_alerts(9.0)
        msgs = self.env['mail.message'].search([('model', '=', 'ax.dashboard'), ('res_id', '=', item.dashboard_id.id), ('body', 'ilike', 'above')])
        self.assertTrue(msgs)
        self.assertIn(user.partner_id, msgs[0].partner_ids)

    def test_acknowledge(self):
        item = self._kpi(use_alert_min=True, alert_min=10.0)
        alert = item.check_alerts(1.0)[0]
        self.assertEqual(alert.state, 'new')
        alert.action_acknowledge()
        self.assertNotEqual(alert.state, 'new')

    def test_zscore(self):
        Item = self.env['ax.dashboard.item']
        self.assertEqual(Item.zscore(5, [1, 2, 3]), (None, None), 'fewer than 7 points: no verdict')
        z, mean = Item.zscore(10, [5, 5, 5, 5, 5, 5, 5, 6])
        self.assertGreater(abs(z), 3)
        z, _m = Item.zscore(5.2, [5, 5, 5, 5, 5, 5, 5, 6])
        self.assertLess(abs(z), 3)
        self.assertEqual(Item.zscore(5, [5] * 8)[0], 0.0)
        self.assertEqual(Item.zscore(50, [5] * 8)[0], 10.0)

    def test_anomaly_alert(self):
        item = self._kpi(alert_enabled=False, anomaly_enabled=True)
        today = fields.Date.today()
        for i in range(1, 10):
            self.env['ax.dashboard.snapshot'].create({'item_id': item.id, 'date': today - timedelta(days=i), 'value': 100.0 + (i % 3)})
        self.assertEqual(item.check_alerts(101.0), [])
        raised = item.check_alerts(900.0)
        self.assertEqual([a.kind for a in raised], ['anomaly'])

    def test_snapshot_cron(self):
        item = self._kpi(snapshot_enabled=True, alert_enabled=False)
        item.snapshot_preset = 'all'
        self.env['ax.dashboard.item']._cron_snapshots()
        snap = self.env['ax.dashboard.snapshot'].search([('item_id', '=', item.id)])
        self.assertEqual(len(snap), 1)
        self.env['ax.dashboard.item']._cron_snapshots()
        self.assertEqual(self.env['ax.dashboard.snapshot'].search_count([('item_id', '=', item.id)]), 1, 'one snapshot per day')

    def test_snapshot_cron_uses_the_owners_rights(self):
        owner = self.make_user('ax_snap_owner', ['ax_dashboard_pro.group_ax_dashboard_builder'])
        d = self.env['ax.dashboard'].create({'name': 'Owned', 'owner_id': owner.id})
        item = self.make_item(dash=d, aggregate='count', snapshot_enabled=True)
        item.snapshot_preset = 'all'
        add_restriction(self.env, 'only BE', 'base.model_res_partner', "[('country_id.code', '=', 'BE')]")
        self.env['ax.dashboard.item']._cron_snapshots()
        snap = self.env['ax.dashboard.snapshot'].search([('item_id', '=', item.id)])
        self.assertEqual(snap.value, 2)
