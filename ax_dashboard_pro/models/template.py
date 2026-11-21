# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AxDashboardTemplate(models.Model):
    _name = 'ax.dashboard.template'
    _description = 'Dashboard template'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    category = fields.Selection([('executive', 'Executive'), ('sales', 'Sales'), ('crm', 'CRM'), ('inventory', 'Inventory'),
                                 ('accounting', 'Accounting'), ('purchase', 'Purchase'), ('hr', 'HR'),
                                 ('manufacturing', 'Manufacturing'), ('custom', 'Custom')], default='custom', required=True)
    description = fields.Text(translate=True)
    data = fields.Text(required=True, help='Dashboard definition in the AXSync export format.')
    group_xmlids = fields.Char(string='Suggested groups', help='Space separated external ids of the groups the dashboard is shared with, for example sales_team.group_sale_manager')
    builtin = fields.Boolean(default=False, readonly=True)
    required_models = fields.Char(compute='_compute_required')
    available = fields.Boolean(compute='_compute_required')
    item_count = fields.Integer(compute='_compute_required')

    @api.depends('data')
    def _compute_required(self):
        for rec in self:
            try:
                d = json.loads(rec.data or '{}')
            except ValueError:
                d = {}
            models_ = sorted({i.get('model') for i in d.get('items', []) if i.get('model')})
            rec.required_models = ', '.join(models_)
            rec.available = all(m in self.env for m in models_)
            rec.item_count = len(d.get('items', []))

    def action_create_dashboard(self):
        self.ensure_one()
        dash, warnings = self.create_dashboard()
        action = dash.action_open()
        if warnings:
            action['context'] = dict(action.get('context') or {}, ax_warnings=warnings)
        return action

    def create_dashboard(self):
        """Create a dashboard from this template. Items that need a missing model are skipped and reported."""
        self.ensure_one()
        if not self.env.user.has_group('ax_dashboard_pro.group_ax_dashboard_builder'):
            raise UserError(_('You need the Dashboard Builder role to create dashboards.'))
        dash, warnings = self.env['ax.dashboard'].import_json(self.data)
        dash.name = self.name
        groups = self.env['res.groups']
        for xmlid in (self.group_xmlids or '').split():
            g = self.env.ref(xmlid, raise_if_not_found=False)
            if g and g._name == 'res.groups':
                groups |= g
        if groups:
            dash.group_ids = [(6, 0, groups.ids)]
        if not dash.item_ids:
            dash.unlink()
            raise UserError(_('This template needs apps that are not installed: %s', self.required_models))
        return dash, warnings

    def action_download(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/ax_dashboard/template/%s/download' % self.id, 'target': 'self'}
