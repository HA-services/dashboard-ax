# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
import json

from odoo import _, api, fields, models


class AxDashboardVersion(models.Model):
    _name = 'ax.dashboard.version'
    _description = 'Dashboard version'
    _order = 'dashboard_id, number desc'

    dashboard_id = fields.Many2one('ax.dashboard', required=True, ondelete='cascade', index=True)
    number = fields.Integer(required=True)
    note = fields.Char()
    user_id = fields.Many2one('res.users', string='Saved by')
    data = fields.Text(required=True)
    item_count = fields.Integer(compute='_compute_item_count')

    def _compute_item_count(self):
        for rec in self:
            try:
                rec.item_count = len(json.loads(rec.data).get('items') or [])
            except ValueError:
                rec.item_count = 0

    def action_restore(self):
        self.ensure_one()
        self.dashboard_id.restore_version(self.id)
        return self.dashboard_id.action_open()

    @api.depends('number', 'note')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = _('Version %(n)s %(note)s', n=rec.number, note=('(%s)' % rec.note) if rec.note else '')
