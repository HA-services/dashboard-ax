# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
from odoo import _, fields, models


class AxDashboardAIWizard(models.TransientModel):
    _name = 'ax.dashboard.ai.wizard'
    _description = 'Generate with AI'

    mode = fields.Selection([('dashboard', 'A new dashboard'), ('item', 'An item on this dashboard')], default='dashboard', required=True)
    dashboard_id = fields.Many2one('ax.dashboard')
    prompt = fields.Text(required=True, help='Example: Show sales by month, top 10 customers and unpaid invoices.')
    model_id = fields.Many2one('ir.model', string='Focus on a model', domain=[('transient', '=', False)],
                               help='Optional. The dashboard is built around the data of this model.')
    keyword = fields.Char(string='Keyword', help='Optional. Only items about this subject are created, for example "refunds".')
    warnings = fields.Text(readonly=True)
    result_id = fields.Many2one('ax.dashboard', readonly=True)

    def action_generate(self):
        self.ensure_one()
        AI = self.env['ax.dashboard.ai']
        prompt = self.prompt
        if self.model_id:
            prompt += '\nUse the model %s (%s) as the main data source.' % (self.model_id.model, self.model_id.name)
        if self.keyword:
            prompt += '\nOnly create items about: %s.' % self.keyword
        if self.mode == 'dashboard' or not self.dashboard_id:
            dash, warnings = AI.generate_dashboard(prompt)
        else:
            dash = self.dashboard_id
            _items, warnings = AI.generate_item(dash, prompt)
        if warnings:
            self.write({'warnings': '\n'.join(str(w) for w in warnings), 'result_id': dash.id})
            return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'target': 'new'}
        return dash.action_open()

    def action_open_result(self):
        return self.result_id.action_open()
