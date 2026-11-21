# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AxDashboardFilter(models.Model):
    """A dashboard level filter. It applies to every item whose model has a stored field with this name."""
    _name = 'ax.dashboard.filter'
    _description = 'Dashboard filter'
    _order = 'sequence, id'

    dashboard_id = fields.Many2one('ax.dashboard', required=True, ondelete='cascade', index=True)
    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    field_name = fields.Char(string='Field name', required=True,
                             help='Technical field name, for example partner_id, user_id or state. '
                                  'Items whose model has this field are filtered.')
    kind = fields.Selection([('many2one', 'Many2one'), ('selection', 'Selection'), ('char', 'Text')], compute='_compute_kind')

    @api.depends('field_name', 'dashboard_id.item_ids.model_name')
    def _compute_kind(self):
        for rec in self:
            fld = rec._first_field()
            rec.kind = fld[1].type if fld and fld[1].type in ('many2one', 'selection') else 'char'

    def _first_field(self):
        self.ensure_one()
        for item in self.dashboard_id.item_ids:
            if item.model_name and item.model_name in self.env:
                f = self.env[item.model_name]._fields.get(self.field_name)
                if f and f.store:
                    return item, f
        return None

    @api.constrains('field_name')
    def _check_field(self):
        for rec in self:
            if rec.dashboard_id.item_ids and not rec._first_field():
                raise UserError(_('No item of this dashboard has a stored field called "%s".', rec.field_name))

    def get_options(self, search=''):
        """Values the user can pick for this filter (uses the user's own access rights)."""
        self.ensure_one()
        found = self._first_field()
        if not found:
            return []
        item, fld = found
        if fld.type == 'selection':
            return [{'id': k, 'name': str(v)} for k, v in fld._description_selection(self.env)]
        if fld.type == 'many2one':
            Co = self.env[fld.comodel_name]
            res = Co.name_search(search or '', limit=40)
            return [{'id': r[0], 'name': r[1]} for r in res]
        return []

    def export_dict(self):
        self.ensure_one()
        return {'name': self.name, 'field': self.field_name}
