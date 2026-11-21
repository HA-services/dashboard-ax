# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class AxDashboardPref(models.Model):
    """Personal settings of one user on one dashboard: layout, theme, hidden values, default filter."""
    _name = 'ax.dashboard.pref'
    _description = 'Dashboard user preferences'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True, default=lambda s: s.env.user)
    dashboard_id = fields.Many2one('ax.dashboard', required=True, ondelete='cascade', index=True)
    data = fields.Text(default='{}')

    _user_dashboard_unique = models.Constraint('UNIQUE(user_id, dashboard_id)', 'One preference record per user and dashboard.')

    @api.model
    def get_prefs(self, dashboard_id):
        rec = self.search([('user_id', '=', self.env.uid), ('dashboard_id', '=', dashboard_id)], limit=1)
        try:
            return json.loads(rec.data) if rec else {}
        except ValueError:
            return {}

    @api.model
    def set_pref(self, dashboard_id, vals):
        """Merge ``vals`` into the stored preferences. Only a few keys are accepted."""
        allowed = {'layout', 'theme', 'hide_values', 'date_preset', 'default_bookmark'}
        vals = {k: v for k, v in (vals or {}).items() if k in allowed}
        # the dashboard must be readable by the user, the search below applies the record rules
        if not self.env['ax.dashboard'].search_count([('id', '=', dashboard_id)]):
            raise AccessError(_('You cannot open this dashboard.'))
        rec = self.sudo().search([('user_id', '=', self.env.uid), ('dashboard_id', '=', dashboard_id)], limit=1)
        data = json.loads(rec.data) if rec else {}
        data.update(vals)
        if rec:
            rec.write({'data': json.dumps(data)})
        else:
            self.sudo().create({'user_id': self.env.uid, 'dashboard_id': dashboard_id, 'data': json.dumps(data)})
        return data


class AxDashboardBookmark(models.Model):
    """A saved combination of dashboard filters."""
    _name = 'ax.dashboard.bookmark'
    _description = 'Dashboard bookmark'
    _order = 'name'

    name = fields.Char(required=True)
    user_id = fields.Many2one('res.users', required=True, default=lambda s: s.env.user, ondelete='cascade', index=True)
    dashboard_id = fields.Many2one('ax.dashboard', required=True, ondelete='cascade', index=True)
    filters = fields.Text(required=True, default='{}')

    @api.model
    def list_for(self, dashboard_id):
        recs = self.search([('dashboard_id', '=', dashboard_id), ('user_id', '=', self.env.uid)])
        out = []
        for r in recs:
            try:
                out.append({'id': r.id, 'name': r.name, 'filters': json.loads(r.filters)})
            except ValueError:
                continue
        return out

    @api.model
    def save_bookmark(self, dashboard_id, name, filters):
        if not self.env['ax.dashboard'].search_count([('id', '=', dashboard_id)]):
            raise AccessError(_('You cannot open this dashboard.'))
        rec = self.create({'name': name, 'dashboard_id': dashboard_id, 'filters': json.dumps(filters or {})})
        return rec.id
