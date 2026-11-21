# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
import logging
import math
from datetime import timedelta

from odoo import _, api, fields, models

from . import compat

_logger = logging.getLogger(__name__)


class AxDashboardSnapshot(models.Model):
    _name = 'ax.dashboard.snapshot'
    _description = 'KPI snapshot'
    _order = 'date desc, id desc'

    item_id = fields.Many2one('ax.dashboard.item', required=True, ondelete='cascade', index=True)
    dashboard_id = fields.Many2one(related='item_id.dashboard_id', store=True)
    date = fields.Date(required=True, default=fields.Date.today, index=True)
    value = fields.Float(digits=(16, 4))

    _sql_constraints = [
        ('item_date_unique', 'unique(item_id, date)', 'One snapshot per item and day.'),
    ]


class AxDashboardAlert(models.Model):
    _name = 'ax.dashboard.alert'
    _description = 'Dashboard alert'
    _order = 'id desc'

    item_id = fields.Many2one('ax.dashboard.item', required=True, ondelete='cascade', index=True)
    dashboard_id = fields.Many2one(related='item_id.dashboard_id', store=True)
    kind = fields.Selection([('below', 'Below minimum'), ('above', 'Above maximum'), ('anomaly', 'Unusual change')], required=True)
    value = fields.Float(digits=(16, 4))
    reference = fields.Float(digits=(16, 4), help='The threshold, or the average of the recent snapshots.')
    message = fields.Char()
    state = fields.Selection([('new', 'New'), ('seen', 'Acknowledged')], default='new')

    def action_acknowledge(self):
        self.write({'state': 'seen'})


class AxDashboardItemAlerts(models.Model):
    _inherit = 'ax.dashboard.item'

    snapshot_ids = fields.One2many('ax.dashboard.snapshot', 'item_id')
    alert_ids = fields.One2many('ax.dashboard.alert', 'item_id')
    alert_count = fields.Integer(compute='_compute_alert_count')

    def _compute_alert_count(self):
        data = {}
        if self.ids:
            for alert in self.env['ax.dashboard.alert'].search([('item_id', 'in', self.ids), ('state', '=', 'new')]):
                data[alert.item_id.id] = data.get(alert.item_id.id, 0) + 1
        for rec in self:
            rec.alert_count = data.get(rec.id, 0)

    # ------------------------------------------------------------------ evaluation
    def _snapshot_value(self):
        self.ensure_one()
        preset = self.snapshot_preset if self.date_field_id or self.source_type == 'formula' else 'all'
        return self._kpi_value({'preset': preset})

    def _history(self, days=30):
        self.ensure_one()
        today = fields.Date.today()
        recs = self.env['ax.dashboard.snapshot'].sudo().search([('item_id', '=', self.id), ('date', '<', today)], order='date desc', limit=days)
        return [r.value for r in recs]

    @staticmethod
    def zscore(value, history):
        """(z, mean). z is None when there is not enough history."""
        if len(history) < 7:
            return None, None
        mean = sum(history) / len(history)
        var = sum((v - mean) ** 2 for v in history) / len(history)
        std = math.sqrt(var)
        if std == 0:
            if value == mean:
                return 0.0, mean
            scale = max(abs(mean), 1.0)
            return (math.copysign(10.0, value - mean) if abs(value - mean) / scale > 0.2 else 0.0), mean
        return (value - mean) / std, mean

    def _raise_alert(self, kind, value, reference, message):
        self.ensure_one()
        Alert = self.env['ax.dashboard.alert'].sudo()
        since = fields.Datetime.now() - timedelta(hours=24)
        if Alert.search_count([('item_id', '=', self.id), ('kind', '=', kind), ('create_date', '>=', since)]):
            return False
        alert = Alert.create({'item_id': self.id, 'kind': kind, 'value': value, 'reference': reference, 'message': message})
        partners = (self.alert_user_ids | self.dashboard_id.owner_id).partner_id
        self.dashboard_id.sudo().message_post(
            body='<b>%s</b>: %s' % (_('Dashboard alert'), message), subject=_('Alert on %s', self.name),
            partner_ids=partners.ids, subtype_xmlid='mail.mt_comment')
        self.dashboard_id._log('alert', message[:150], item=self)
        return alert

    def check_alerts(self, value=None):
        """Evaluate thresholds and anomaly rules for one item. Returns the alerts raised."""
        self.ensure_one()
        value = self._snapshot_value() if value is None else value
        raised = []
        if self.alert_enabled:
            if self.use_alert_min and value < self.alert_min:
                a = self._raise_alert('below', value, self.alert_min, _('%(n)s is %(v)s, below the minimum of %(t)s.', n=self.name, v=round(value, 2), t=self.alert_min))
                a and raised.append(a)
            if self.use_alert_max and value > self.alert_max:
                a = self._raise_alert('above', value, self.alert_max, _('%(n)s is %(v)s, above the maximum of %(t)s.', n=self.name, v=round(value, 2), t=self.alert_max))
                a and raised.append(a)
        if self.anomaly_enabled:
            z_limit = float(compat.get_param(self.env, 'ax_dashboard_pro.anomaly_z') or 3.0)
            z, mean = self.zscore(value, self._history())
            if z is not None and abs(z) >= z_limit:
                a = self._raise_alert('anomaly', value, mean, _('%(n)s is %(v)s, unusual compared with the recent average of %(m)s.', n=self.name, v=round(value, 2), m=round(mean, 2)))
                a and raised.append(a)
        return raised

    @api.model
    def _cron_snapshots(self):
        items = self.search(['|', '|', ('snapshot_enabled', '=', True), ('alert_enabled', '=', True), ('anomaly_enabled', '=', True),
                             ('item_type', '=', 'kpi')]).filtered(lambda i: i.item_type == 'kpi' and (i.snapshot_enabled or i.alert_enabled or i.anomaly_enabled))
        for item in items:
            owner = item.dashboard_id.owner_id
            if not owner.active:
                continue
            try:
                with self.env.cr.savepoint():
                    it = item.with_user(owner)
                    value = it._snapshot_value()
                    snap = self.env['ax.dashboard.snapshot'].sudo()
                    existing = snap.search([('item_id', '=', item.id), ('date', '=', fields.Date.today())], limit=1)
                    history = it._history()
                    if existing:
                        existing.value = value
                    else:
                        snap.create({'item_id': item.id, 'value': value})
                    it.check_alerts(value)
            except Exception:  # noqa: BLE001
                _logger.exception('Snapshot failed for item %s', item.id)
        # keep two years of snapshots
        self.env['ax.dashboard.snapshot'].sudo().search([('date', '<', fields.Date.today() - timedelta(days=730))]).unlink()
        self.env['ax.dashboard.perf'].sudo().search([('day', '<', fields.Date.today() - timedelta(days=30))]).unlink()
        self.env['ax.dashboard.log'].sudo().search([('create_date', '<', fields.Datetime.now() - timedelta(days=180))]).unlink()
