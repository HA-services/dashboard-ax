# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
from odoo import fields, models


class AxDashboardMoveWizard(models.TransientModel):
    _name = 'ax.dashboard.move.wizard'
    _description = 'Move an item to another dashboard'

    item_id = fields.Many2one('ax.dashboard.item', required=True)
    dashboard_id = fields.Many2one('ax.dashboard', string='Move to', required=True)

    def action_move(self):
        self.ensure_one()
        source = self.item_id.dashboard_id
        self.item_id.action_move_to(self.dashboard_id.id)
        return self.dashboard_id.action_open()
