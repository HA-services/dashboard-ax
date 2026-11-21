# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ax_allow_sql = fields.Boolean(string='Allow custom SQL items', config_parameter='ax_dashboard_pro.allow_sql',
                                  help='Dashboard Managers can then create items from a read-only SQL query.')
    ax_allow_private_hosts = fields.Boolean(string='Allow private hosts for JSON APIs', config_parameter='ax_dashboard_pro.allow_private_hosts')
    ax_slow_ms = fields.Integer(string='Slow item threshold (ms)', config_parameter='ax_dashboard_pro.slow_ms', default=1000)
    ax_anomaly_z = fields.Float(string='Anomaly sensitivity (z-score)', config_parameter='ax_dashboard_pro.anomaly_z', default=3.0)
    ax_ai_provider = fields.Selection([('openai', 'OpenAI compatible'), ('anthropic', 'Anthropic')], string='AI provider',
                                      config_parameter='ax_dashboard_pro.ai_provider', default='openai')
    ax_ai_base_url = fields.Char(string='AI base URL', config_parameter='ax_dashboard_pro.ai_base_url',
                                 help='OpenAI compatible: https://api.openai.com/v1 . Anthropic: https://api.anthropic.com')
    ax_ai_api_key = fields.Char(string='AI API key', config_parameter='ax_dashboard_pro.ai_api_key')
    ax_ai_model = fields.Char(string='AI model', config_parameter='ax_dashboard_pro.ai_model')
