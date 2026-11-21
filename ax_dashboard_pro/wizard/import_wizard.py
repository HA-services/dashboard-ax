# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
from odoo import _, fields, models
from odoo.exceptions import UserError

from ..models import compat


class AxDashboardImportWizard(models.TransientModel):
    _name = 'ax.dashboard.import.wizard'
    _description = 'Import a dashboard'

    file = fields.Binary(string='Dashboard file (.json)', required=True)
    filename = fields.Char()
    warnings = fields.Text(readonly=True)
    dashboard_id = fields.Many2one('ax.dashboard', readonly=True)

    def action_import(self):
        self.ensure_one()
        try:
            text = compat.binary_bytes(self.file).decode('utf-8')
        except Exception:  # noqa: BLE001
            raise UserError(_('This file cannot be read. Choose a .json file exported from AXSync Dashboard Pro.'))
        dash, warnings = self.env['ax.dashboard'].import_json(text)
        if warnings:
            self.write({'warnings': '\n'.join(str(w) for w in warnings), 'dashboard_id': dash.id})
            return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'target': 'new'}
        return dash.action_open()

    def action_open_dashboard(self):
        return self.dashboard_id.action_open()
