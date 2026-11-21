# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
import importlib
import json
import logging
import re
import time
from datetime import datetime, time as dtime, timedelta

from dateutil.relativedelta import relativedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

from . import compat, filetable, safe

_se = importlib.import_module('odoo.tools.safe_eval')

_logger = logging.getLogger(__name__)

NUMERIC = ('integer', 'float', 'monetary')
GROUPABLE = ('many2one', 'selection', 'boolean', 'date', 'datetime', 'char', 'integer')
CHART_TYPES = [
    ('bar', 'Bar'), ('hbar', 'Horizontal bar'), ('stacked', 'Stacked bar'), ('line', 'Line'), ('area', 'Area'),
    ('pie', 'Pie'), ('doughnut', 'Doughnut'), ('polar', 'Polar area'),
    ('radar', 'Radar'), ('scatter', 'Scatter'), ('funnel', 'Funnel'), ('bullet', 'Bullet'),
    ('flower', 'Flower'), ('radial', 'Radial bar'), ('map', 'Map (countries)'),
]
SCHEMES = {
    'blue': ['#1e5eff', '#4f86ff', '#7ea6ff', '#a8c2ff', '#2f4b7c', '#5f7fb8', '#8fa6d1', '#bccae6'],
    'navy': ['#0f2a5c', '#1e5eff', '#2f9bff', '#6ec1ff', '#9aa9c7', '#c9d3e6', '#3b4a6b', '#7184ad'],
    'teal': ['#0e7c86', '#1fb5a8', '#4fd1c5', '#8be0d6', '#14305a', '#4a6fa5', '#9db4d4', '#d0dcec'],
    'warm': ['#e5534b', '#f4a261', '#f2c14e', '#e76f51', '#8b5cf6', '#2f6fed', '#2e9d57', '#9aa5b8'],
    'rainbow': ['#2f6fed', '#1fb5a8', '#f4a261', '#8b5cf6', '#e5534b', '#2e9d57', '#f2c14e', '#e056a0'],
    'mono': ['#0f1b33', '#2c3a57', '#4b5a73', '#6b7a93', '#8b9ab3', '#aebbd0', '#cbd5e4', '#e3e8f0'],
}


class AxDashboardTodoLine(models.Model):
    _name = 'ax.dashboard.todo'
    _description = 'Dashboard to-do line'
    _order = 'done, sequence, id'

    item_id = fields.Many2one('ax.dashboard.item', required=True, ondelete='cascade', index=True)
    name = fields.Char(required=True)
    done = fields.Boolean()
    sequence = fields.Integer(default=10)
    user_id = fields.Many2one('res.users', string='Assigned to')


class AxDashboardItem(models.Model):
    _name = 'ax.dashboard.item'
    _description = 'Dashboard item'
    _order = 'dashboard_id, grid_y, grid_x, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(help='Short technical name used by formula items, for example sales_total.')
    description = fields.Char(string='Tooltip', translate=True)
    dashboard_id = fields.Many2one('ax.dashboard', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    item_type = fields.Selection([('kpi', 'KPI tile'), ('chart', 'Chart'), ('list', 'List'), ('todo', 'To-do list')],
                                 required=True, default='kpi')
    source_type = fields.Selection([('model', 'Odoo model'), ('formula', 'Formula'), ('sql', 'Custom SQL'),
                                    ('external', 'External connection'), ('file', 'Excel or CSV file')], required=True, default='model')
    model_id = fields.Many2one('ir.model', string='Model', ondelete='cascade', domain=[('transient', '=', False)])
    model_name = fields.Char(related='model_id.model', store=True, string='Model name')
    domain = fields.Char(default='[]', help='Odoo domain. Example: [("state", "=", "sale")]')
    measure_field_id = fields.Many2one('ir.model.fields', string='Measure', ondelete='cascade',
                                       domain="[('model_id', '=', model_id), ('store', '=', True), ('ttype', 'in', ['integer', 'float', 'monetary'])]")
    aggregate = fields.Selection([('count', 'Count'), ('sum', 'Sum'), ('avg', 'Average'), ('min', 'Minimum'),
                                  ('max', 'Maximum'), ('count_distinct', 'Distinct count')], default='sum', required=True)
    measure2_field_id = fields.Many2one('ir.model.fields', string='Second measure (scatter)', ondelete='set null',
                                        domain="[('model_id', '=', model_id), ('store', '=', True), ('ttype', 'in', ['integer', 'float', 'monetary'])]")
    data_file = fields.Binary(string='Excel or CSV file', attachment=True, groups='ax_dashboard_pro.group_ax_dashboard_builder')
    data_filename = fields.Char(string='File name')
    file_groupby = fields.Char(string='Group by column', help='Column name in the first row of the file.')
    file_measure = fields.Char(string='Measure column', help='Numeric column name. Leave empty to count rows.')
    file_columns = fields.Char(string='List columns', help='Comma separated column names. Leave empty for all columns.')
    groupby_field_id = fields.Many2one('ir.model.fields', string='Group by', ondelete='cascade',
                                       domain="[('model_id', '=', model_id), ('store', '=', True), ('ttype', 'in', ['many2one', 'selection', 'boolean', 'date', 'datetime', 'char', 'integer'])]")
    groupby2_field_id = fields.Many2one('ir.model.fields', string='Then group by', ondelete='cascade',
                                        domain="[('model_id', '=', model_id), ('store', '=', True), ('ttype', 'in', ['many2one', 'selection', 'boolean', 'date', 'datetime', 'char'])]")
    date_interval = fields.Selection([('day', 'Day'), ('week', 'Week'), ('month', 'Month'), ('quarter', 'Quarter'),
                                      ('year', 'Year')], default='month', string='Date interval')
    sort_by = fields.Selection([('value', 'Value'), ('label', 'Label')], default='value', required=True)
    sort_dir = fields.Selection([('desc', 'Descending'), ('asc', 'Ascending')], default='desc', required=True)
    limit = fields.Integer(default=10, help='Maximum number of groups or rows. 0 means no limit (capped at 500).')
    date_field_id = fields.Many2one('ir.model.fields', string='Date field', ondelete='set null',
                                    help='The dashboard date filter is applied to this field.',
                                    domain="[('model_id', '=', model_id), ('store', '=', True), ('ttype', 'in', ['date', 'datetime'])]")
    list_field_ids = fields.Many2many('ir.model.fields', 'ax_dashboard_item_list_field_rel', 'item_id', 'field_id',
                                      string='Columns', domain="[('model_id', '=', model_id), ('store', '=', True)]")
    list_order = fields.Char(string='Sort rows by', help='Example: date_order desc')
    chart_type = fields.Selection(CHART_TYPES, default='bar')
    color_scheme = fields.Selection([('blue', 'Blue'), ('navy', 'Navy'), ('teal', 'Teal'), ('warm', 'Warm'),
                                     ('rainbow', 'Rainbow'), ('mono', 'Monochrome'), ('custom', 'Custom')], default='blue')
    custom_colors = fields.Char(help='Comma separated hex colors, for example #1e5eff,#1fb5a8')
    show_legend = fields.Boolean(default=True)
    show_labels = fields.Boolean(string='Show data labels', default=False)
    kpi_icon = fields.Char(string='Icon', default='fa-line-chart', help='Font Awesome icon class, for example fa-shopping-cart')
    kpi_color = fields.Char(string='Color', default='#1e5eff')
    target_value = fields.Float(string='Target')
    forecast_periods = fields.Integer(string='Forecast periods', default=0,
                                      help='Adds a dashed trend projection of this many future periods to line, area and bar charts grouped by date. 0 switches it off.')
    compare_mode = fields.Selection([('none', 'No comparison'), ('previous_period', 'Previous period'),
                                     ('previous_year', 'Same period last year')], default='none', required=True)
    number_format = fields.Selection([('auto', 'Automatic'), ('integer', 'Whole number'), ('decimal', 'Decimal'),
                                      ('monetary', 'Monetary'), ('percent', 'Percent'), ('compact', 'Compact (1.2K, 3.4M)')],
                                     default='auto', required=True)
    decimals = fields.Integer(default=2)
    prefix = fields.Char()
    suffix = fields.Char()
    currency_id = fields.Many2one('res.currency', string='Currency', help='Empty means the currency of the current company.')
    formula = fields.Char(help='Example: {sales_total} / {orders} * 100. Use the codes of other KPI items.')
    sql_query = fields.Text(string='SQL query', groups='ax_dashboard_pro.group_ax_dashboard_manager')
    connection_id = fields.Many2one('ax.dashboard.connection', string='Connection', groups='ax_dashboard_pro.group_ax_dashboard_manager')
    drill_path = fields.Char(string='Drill-down fields', help='Comma separated fields used for the next levels when a user clicks a chart.')
    snapshot_enabled = fields.Boolean(string='Keep daily snapshots')
    snapshot_preset = fields.Selection([('all', 'All time'), ('today', 'Today'), ('yesterday', 'Yesterday'), ('last_7', 'Last 7 days'), ('last_30', 'Last 30 days'), ('this_month', 'This month')], default='last_30', string='Snapshot period', help='Period used for snapshots, alerts and anomaly detection.')
    alert_enabled = fields.Boolean(string='Threshold alert')
    alert_min = fields.Float(string='Alert below')
    alert_max = fields.Float(string='Alert above')
    use_alert_min = fields.Boolean()
    use_alert_max = fields.Boolean()
    anomaly_enabled = fields.Boolean(string='Detect anomalies')
    alert_user_ids = fields.Many2many('res.users', 'ax_dashboard_item_alert_user_rel', 'item_id', 'user_id', string='Notify')
    todo_line_ids = fields.One2many('ax.dashboard.todo', 'item_id', string='To-do lines')
    grid_x = fields.Integer(default=0)
    grid_y = fields.Integer(default=0)
    grid_w = fields.Integer(default=4)
    grid_h = fields.Integer(default=3)
    last_load_ms = fields.Integer(readonly=True)
    avg_load_ms = fields.Integer(readonly=True)
    load_count = fields.Integer(readonly=True)

    _sql_constraints = [
        ('grid_positive', 'CHECK(grid_w > 0 AND grid_h > 0)', 'The size of an item must be positive.'),
    ]

    # ------------------------------------------------------------------ defaults and checks
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_source_rights(vals)
            if not vals.get('code') and vals.get('name'):
                vals['code'] = self._make_code(vals['name'], vals.get('dashboard_id'))
            if 'grid_w' not in vals and 'grid_h' not in vals:
                itype = vals.get('item_type', 'kpi')
                vals['grid_w'], vals['grid_h'] = {'kpi': (3, 2), 'chart': (6, 4), 'list': (6, 4), 'todo': (3, 4)}.get(itype, (4, 3))
            if 'grid_y' not in vals and vals.get('dashboard_id'):
                vals['grid_x'], vals['grid_y'] = self._free_position(vals['dashboard_id'], vals.get('grid_w', 4), vals.get('grid_h', 3))
        records = super().create(vals_list)
        records.mapped('dashboard_id')._snapshot_version(_('Item added'))
        records.mapped('dashboard_id')._log('edit', _('Item added: %s', ', '.join(records.mapped('name'))))
        return records

    def write(self, vals):
        if 'connection_id' not in vals and ('sql_query' in vals or vals.get('source_type') in ('sql', 'external')):
            # the type of the stored connection decides whether the SQL switch applies
            for rec in self:
                self._check_source_rights(dict(vals, connection_id=rec.connection_id.id))
        else:
            self._check_source_rights(vals)
        res = super().write(vals)
        if not self.env.context.get('ax_skip_version') and set(vals) - {'last_load_ms', 'avg_load_ms', 'load_count', 'grid_x', 'grid_y', 'grid_w', 'grid_h'}:
            self.mapped('dashboard_id')._snapshot_version(_('Item changed'))
        return res

    def unlink(self):
        dashboards = self.mapped('dashboard_id')
        names = ', '.join(self.mapped('name'))
        res = super().unlink()
        dashboards._snapshot_version(_('Item removed'))
        dashboards._log('edit', _('Item removed: %s', names))
        return res

    @api.model
    def _check_source_rights(self, vals):
        if vals.get('source_type') in ('sql', 'external') or vals.get('sql_query') or vals.get('connection_id'):
            if not self.env.user.has_group('ax_dashboard_pro.group_ax_dashboard_manager'):
                raise AccessError(_('Only Dashboard Managers can create or change SQL and external data items.'))
            conn = self.env['ax.dashboard.connection'].browse(vals['connection_id']) if vals.get('connection_id') else False
            is_api = bool(conn and conn.conn_type == 'api')
            if (vals.get('source_type') == 'sql' or vals.get('sql_query')) and not is_api:
                if compat.get_param(self.env, 'ax_dashboard_pro.allow_sql') != 'True':
                    raise UserError(_('Custom SQL items are switched off. A Dashboard Manager can enable them in Settings.'))

    @api.model
    def _make_code(self, name, dashboard_id):
        base = re.sub(r'[^a-z0-9]+', '_', (name or 'item').lower()).strip('_') or 'item'
        base = base[:30]
        code, n = base, 1
        existing = set(self.search([('dashboard_id', '=', dashboard_id)]).mapped('code')) if dashboard_id else set()
        while code in existing:
            n += 1
            code = '%s_%d' % (base, n)
        return code

    @api.model
    def _free_position(self, dashboard_id, width, height=3):
        """First free spot on the 12 column grid, scanning rows from the top and columns from the left."""
        items = self.search([('dashboard_id', '=', dashboard_id)])
        if not items:
            return 0, 0
        width = max(1, min(12, int(width or 4)))
        height = max(1, int(height or 3))
        taken = set()
        for i in items:
            for yy in range(i.grid_y, i.grid_y + max(1, i.grid_h)):
                for xx in range(i.grid_x, min(12, i.grid_x + max(1, i.grid_w))):
                    taken.add((xx, yy))
        bottom = max(i.grid_y + i.grid_h for i in items)
        for y in range(0, bottom + 1):
            for x in range(0, 12 - width + 1):
                if all((xx, yy) not in taken for xx in range(x, x + width) for yy in range(y, y + height)):
                    return x, y
        return 0, bottom

    @api.constrains('domain')
    def _check_domain(self):
        for rec in self:
            if rec.domain and rec.source_type == 'model':
                try:
                    dom = rec._eval_domain()
                except Exception as exc:  # noqa: BLE001
                    raise ValidationError(_('The domain of "%(name)s" is not valid: %(err)s', name=rec.name, err=exc))
                if not isinstance(dom, (list, tuple)):
                    raise ValidationError(_('The domain of "%s" must be a list.', rec.name))

    @api.constrains('code', 'dashboard_id')
    def _check_code(self):
        for rec in self:
            if rec.code:
                if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', rec.code):
                    raise ValidationError(_('The code "%s" may only contain letters, digits and underscores.', rec.code))
                if self.search_count([('dashboard_id', '=', rec.dashboard_id.id), ('code', '=', rec.code), ('id', '!=', rec.id)]):
                    raise ValidationError(_('The code "%s" is already used on this dashboard.', rec.code))

    @api.constrains('item_type', 'source_type', 'model_id', 'measure_field_id', 'groupby_field_id', 'formula', 'aggregate', 'file_groupby')
    def _check_setup(self):
        for rec in self:
            if rec.source_type == 'model':
                if rec.item_type != 'todo' and not rec.model_id:
                    raise ValidationError(_('Choose a model for "%s".', rec.name))
                if rec.aggregate not in ('count',) and rec.item_type in ('kpi', 'chart') and not rec.measure_field_id:
                    raise ValidationError(_('Choose a measure for "%s", or use Count.', rec.name))
                if rec.item_type == 'chart' and not rec.groupby_field_id:
                    raise ValidationError(_('A chart needs a "Group by" field ("%s").', rec.name))
            elif rec.source_type == 'file':
                if not rec.sudo().data_file:
                    raise ValidationError(_('Upload an Excel or CSV file for "%s".', rec.name))
                if rec.item_type == 'chart' and not rec.file_groupby:
                    raise ValidationError(_('Name the column to group by for "%s".', rec.name))
            elif rec.source_type == 'formula' and rec.item_type != 'kpi':
                raise ValidationError(_('Formula items must be KPI tiles ("%s").', rec.name))
            for fld in (rec.measure_field_id, rec.measure2_field_id, rec.groupby_field_id, rec.groupby2_field_id, rec.date_field_id):
                if fld and fld.model_id != rec.model_id:
                    raise ValidationError(_('The field "%(f)s" does not belong to the model of "%(n)s".', f=fld.name, n=rec.name))

    @api.onchange('model_id')
    def _onchange_model_id(self):
        self.measure_field_id = self.groupby_field_id = self.groupby2_field_id = self.date_field_id = False
        self.list_field_ids = False
        if self.model_id:
            cands = self.env['ir.model.fields'].search([('model_id', '=', self.model_id.id), ('store', '=', True), ('ttype', 'in', ['date', 'datetime'])], limit=1)
            self.date_field_id = cands[:1]

    # ------------------------------------------------------------------ domain handling
    def _eval_domain(self):
        self.ensure_one()
        ctx = {
            'uid': self.env.uid, 'user': self.env.user, 'datetime': _se.datetime, 'time': _se.time,
            'context_today': lambda: fields.Date.context_today(self),
            'relativedelta': _se.dateutil.relativedelta.relativedelta,
            'current_date': fields.Date.today().isoformat(),
            'company_id': self.env.company.id, 'company_ids': self.env.companies.ids,
        }
        txt = (self.domain or '[]').strip() or '[]'
        # %UID and %MYCOMPANY stand for the viewer and the viewer's current company
        txt = txt.replace('%UID', str(self.env.uid)).replace('%MYCOMPANIES', str(self.env.companies.ids)).replace('%MYCOMPANY', str(self.env.company.id))
        return safe_eval(txt, ctx)

    def _fy_end(self):
        """(month, day) of the last day of the company's financial year, 31 December when it is not configured."""
        company = self.env.company
        try:
            month = int(getattr(company, 'fiscalyear_last_month', 12) or 12)
            day = int(getattr(company, 'fiscalyear_last_day', 31) or 31)
        except (TypeError, ValueError):
            month, day = 12, 31
        return month, day

    def _date_domain(self, field, start, end):
        out = []
        if field.ttype == 'datetime':
            tz = pytz.timezone(self.env.user.tz or 'UTC')
            if start:
                out.append((field.name, '>=', fields.Datetime.to_string(tz.localize(datetime.combine(start, dtime.min)).astimezone(pytz.utc).replace(tzinfo=None))))
            if end:
                out.append((field.name, '<=', fields.Datetime.to_string(tz.localize(datetime.combine(end, dtime.max.replace(microsecond=0))).astimezone(pytz.utc).replace(tzinfo=None))))
        else:
            if start:
                out.append((field.name, '>=', start))
            if end:
                out.append((field.name, '<=', end))
        return out

    def _filter_range(self, filters, which='current'):
        """Date range for this item's period: (start, end)."""
        preset = (filters or {}).get('preset')
        s, e, ps, pe = safe.date_range(preset, fields.Date.context_today(self), (filters or {}).get('date_from'), (filters or {}).get('date_to'), self._fy_end())
        if which == 'current':
            return s, e
        if which == 'previous_year':
            return safe.shift_year(s, e)
        return ps, pe

    def _full_domain(self, filters, which='current', extra=None):
        self.ensure_one()
        Model = self.env[self.model_name]
        domain = list(self._eval_domain())
        if self.date_field_id and (filters or {}).get('preset') not in (None, '', 'all'):
            s, e = self._filter_range(filters, which)
            domain += self._date_domain(self.date_field_id, s, e)
        for flt in self.dashboard_id.filter_ids:
            value = ((filters or {}).get('fields') or {}).get(str(flt.id))
            if value in (None, False, '', []):
                continue
            fname = flt.field_name
            fld = Model._fields.get(fname)
            if not fld or not fld.store:
                continue
            if fld.type == 'many2one':
                domain.append((fname, 'in' if isinstance(value, list) else '=', value))
            elif fld.type in ('selection', 'char', 'boolean'):
                domain.append((fname, '=', value))
        if extra:
            domain = list(domain) + list(extra)   # two domains written one after the other are combined with AND
        return domain

    # ------------------------------------------------------------------ formatting meta
    def _meta(self):
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        return {
            'format': self.number_format,
            'decimals': self.decimals if self.decimals is not None else 2,
            'prefix': self.prefix or '',
            'suffix': self.suffix or '',
            'currency_symbol': currency.symbol or '',
            'currency_position': currency.position or 'before',
            'currency_name': currency.name,
            'auto_monetary': bool(self.measure_field_id and self.measure_field_id.ttype == 'monetary'),
        }

    def _colors(self):
        self.ensure_one()
        if self.color_scheme == 'custom' and self.custom_colors:
            cols = [c.strip() for c in self.custom_colors.split(',') if c.strip()]
            if cols:
                return cols
        return SCHEMES.get(self.color_scheme if self.color_scheme != 'custom' else 'blue')

    # ------------------------------------------------------------------ public entry point
    def get_data(self, filters=None, drill=None):
        """Data for one item, computed with the rights of the current user."""
        self.ensure_one()
        started = time.time()
        filters = filters or {}
        result = {}
        try:
            with self.env.cr.savepoint():
                result = self._compute(filters, drill or {})
        except (AccessError, UserError, ValidationError) as exc:
            result = {'error': exc.args[0] if exc.args else str(exc)}
        except (ValueError, KeyError, TypeError) as exc:
            # a wrong domain, field name or option written by hand: tell the builder, do not flood the log
            _logger.info('Dashboard item %s has an invalid setup: %s', self.id, exc)
            result = {'error': _('This item has an invalid setup: %s', exc)}
        except Exception as exc:  # noqa: BLE001
            _logger.exception('Dashboard item %s failed', self.id)
            result = {'error': _('This item could not be loaded. The details are in the server log.')}
        ms = int((time.time() - started) * 1000)
        if not result.get('error') and self.item_type in ('kpi', 'chart'):
            result['can_drivers'] = self._drivers_eligible(filters)
        result.update({
            'id': self.id, 'name': self.name, 'item_type': self.item_type, 'chart_type': self.chart_type,
            'description': self.description or '', 'meta': self._meta(), 'ms': ms,
            'kpi_icon': self.kpi_icon, 'kpi_color': self.kpi_color, 'show_legend': self.show_legend,
            'show_labels': self.show_labels, 'colors': self._colors(), 'has_alert': bool(self.alert_enabled),
        })
        self._record_perf(ms, result)
        return result

    def _record_perf(self, ms, result):
        """Best-effort load statistics: a busy row is skipped rather than slowing the user down."""
        cr = self.env.cr
        try:
            with cr.savepoint():
                cr.execute("""UPDATE ax_dashboard_item SET last_load_ms = %s, load_count = COALESCE(load_count, 0) + 1,
                              avg_load_ms = ((COALESCE(avg_load_ms, 0) * LEAST(COALESCE(load_count, 0), 49)) + %s) / (LEAST(COALESCE(load_count, 0), 49) + 1)
                              WHERE id IN (SELECT id FROM ax_dashboard_item WHERE id = %s FOR NO KEY UPDATE SKIP LOCKED)""",
                           (ms, ms, self.id))
        except Exception:  # noqa: BLE001
            _logger.debug('Could not store the load time of item %s', self.id)
        threshold = int(compat.get_param(self.env, 'ax_dashboard_pro.slow_ms') or 1000)
        if ms >= threshold or result.get('error'):
            self.env['ax.dashboard.perf'].sudo().create({
                'item_id': self.id, 'dashboard_id': self.dashboard_id.id, 'user_id': self.env.uid,
                'ms': ms, 'error': result.get('error') or False,
            })

    # ------------------------------------------------------------------ computation
    def _compute(self, filters, drill):
        self.ensure_one()
        if self.item_type == 'todo':
            return self._compute_todo()
        if self.source_type == 'formula':
            return self._compute_formula(filters)
        if self.source_type in ('sql', 'external', 'file'):
            return self._compute_rows_source(filters)
        return {
            'kpi': self._compute_kpi, 'chart': self._compute_chart, 'list': self._compute_list,
        }[self.item_type](filters, drill)

    def _compute_todo(self):
        lines = self.todo_line_ids
        return {'lines': [{'id': l.id, 'name': l.name, 'done': l.done, 'user': l.user_id.name or ''} for l in lines]}

    # -- KPI
    def _kpi_value(self, filters, which='current'):
        self.ensure_one()
        if self.source_type == 'formula':
            return self._formula_value(filters)
        Model = self.env[self.model_name]
        measure = self.measure_field_id.name if self.measure_field_id else None
        return compat.aggregate_one(Model, self._full_domain(filters, which), measure, self.aggregate)

    def _compute_kpi(self, filters, drill):
        Model = self.env[self.model_name]
        value = self._kpi_value(filters)
        out = {'value': value, 'res_model': self.model_name, 'domain': self._full_domain(filters)}
        if self.target_value:
            out['target'] = self.target_value
            out['target_pct'] = round(value / self.target_value * 100.0, 1)
            self._add_pace(out, value, filters)
        if self.compare_mode != 'none' and self.date_field_id and (filters or {}).get('preset') not in (None, '', 'all'):
            prev = self._kpi_value(filters, 'previous_year' if self.compare_mode == 'previous_year' else 'previous')
            out['previous'] = prev
            out['change_pct'] = round((value - prev) / abs(prev) * 100.0, 1) if prev else None
            out['compare_label'] = _('vs previous year') if self.compare_mode == 'previous_year' else _('vs previous period')
        s, e = self._filter_range(filters)
        if self.date_field_id and s and e:
            interval = 'day' if (e - s).days <= 62 else 'month'
            gb = '%s:%s' % (self.date_field_id.name, interval)
            measure = self.measure_field_id.name if self.measure_field_id else None
            rows = compat.read_groups(Model, self._full_domain(filters), [gb], measure, self.aggregate, limit=400)
            pts = []
            for r in rows:
                start = self._bucket_start(r, 0)
                if start:
                    pts.append((start, r['value']))
            pts.sort()
            if len(pts) > 1:
                out['spark'] = [p[1] for p in pts]
        return out

    # ------------------------------------------------------------------ target pacing
    def _add_pace(self, out, value, filters):
        """Projected value at the end of a running period, from the days elapsed so far."""
        if self.source_type != 'model' or self.aggregate not in ('sum', 'count') or value < 0:
            return
        s, e = self._filter_range(filters)
        today = fields.Date.context_today(self)
        if not (s and e and s <= today < e):
            return
        total = (e - s).days + 1
        elapsed = (today - s).days + 1
        pace = value * total / elapsed
        out['pace_value'] = round(pace, 2)
        out['pace_pct'] = round(pace / self.target_value * 100.0, 1)

    # ------------------------------------------------------------------ forecast
    @staticmethod
    def _add_buckets(start, interval, k):
        if interval == 'day':
            return start + timedelta(days=k)
        if interval == 'week':
            return start + timedelta(days=7 * k)
        if interval == 'month':
            return start + relativedelta(months=k)
        if interval == 'quarter':
            return start + relativedelta(months=3 * k)
        return start + relativedelta(years=k)

    @staticmethod
    def _bucket_gap(a, b, interval):
        """Number of buckets between two bucket starts."""
        if interval == 'day':
            return (b - a).days
        if interval == 'week':
            return (b - a).days // 7
        months = (b.year - a.year) * 12 + b.month - a.month
        if interval == 'month':
            return months
        if interval == 'quarter':
            return months // 3
        return b.year - a.year

    def _add_forecast(self, out, rows, first, level, level_fields):
        n = max(0, min(int(self.forecast_periods or 0), 12))
        if (not n or level or len(level_fields) != 1 or first.ttype not in ('date', 'datetime')
                or self.chart_type not in ('line', 'area', 'bar') or not out['labels']):
            return
        interval = self.date_interval or 'month'
        order = self._sorted_labels(rows, first)
        pts = sorted((e['start'], e['total']) for e in order if e['start'])
        if len(pts) < 3 or len(pts) != len(out['labels']):
            return
        fit = pts
        today = fields.Date.context_today(self)
        if safe.bucket_end(pts[-1][0], interval) > today and len(pts) > 3:
            fit = pts[:-1]  # the running period is incomplete and would pull the trend down
        fit = fit[-24:]
        xs = [self._bucket_gap(fit[0][0], p[0], interval) for p in fit]
        ys = [p[1] for p in fit]
        m = len(xs)
        mx, my = sum(xs) / m, sum(ys) / m
        den = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0
        intercept = my - slope * mx
        last_start, last_value = pts[-1]
        positive = all(y >= 0 for y in ys)
        future, future_labels = [], []
        for k in range(1, n + 1):
            start = self._add_buckets(last_start, interval, k)
            x = self._bucket_gap(fit[0][0], start, interval)
            y = intercept + slope * x
            future.append(round(max(y, 0.0) if positive else y, 2))
            future_labels.append(safe.bucket_label(start, interval))
        old = len(out['labels'])
        out['labels'] = out['labels'] + future_labels
        out['domains'] = out['domains'] + [None] * n
        for ds in out['datasets']:
            ds['data'] = list(ds['data']) + [None] * n
        out['datasets'].append({'label': _('Forecast'), 'data': [None] * (old - 1) + [last_value] + future, 'forecast': True})
        out['forecast'] = {'periods': n, 'slope': round(slope, 4), 'points': len(fit)}

    # ------------------------------------------------------------------ why did it change
    def _drivers_eligible(self, filters):
        return bool(self.source_type == 'model' and self.model_name and self.date_field_id and self.aggregate in ('sum', 'count')
                    and (filters or {}).get('preset') not in (None, '', 'all'))

    def _driver_fields(self):
        skip = ('create_uid', 'write_uid', 'message_main_attachment_id', 'activity_user_id', 'activity_type_id', 'activity_state')
        chosen = []
        if self.groupby_field_id and self.groupby_field_id.ttype in ('many2one', 'selection'):
            chosen.append(self.groupby_field_id)
        for part in (self.drill_path or '').split(','):
            fld = self.env['ir.model.fields']._get(self.model_name, part.strip().split(':')[0]) if part.strip() else None
            if fld and fld.ttype in ('many2one', 'selection') and fld not in chosen:
                chosen.append(fld)
        others = self.env['ir.model.fields'].search([('model', '=', self.model_name), ('store', '=', True), ('ttype', 'in', ('many2one', 'selection')),
                                                      ('name', 'not in', skip)], order='id')
        for fld in others:
            if fld not in chosen and not fld.name.startswith(('activity_', 'message_', 'website_')):
                chosen.append(fld)
        return chosen[:10]

    def get_drivers(self, filters=None, field_name=None):
        """What moved a number: the groups that explain most of the change against the comparison period.
        Runs with the rights of the current user. Returns an in-band error like get_data."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                return self._drivers(filters or {}, field_name)
        except (AccessError, UserError, ValidationError) as exc:
            return {'error': exc.args[0] if exc.args else str(exc)}

    def _drivers(self, filters, field_name):
        if not self._drivers_eligible(filters):
            raise UserError(_('Choose a date range other than all time, and use a sum or count on an Odoo model with a date field.'))
        which = 'previous_year' if self.compare_mode == 'previous_year' else 'previous'
        Model = self.env[self.model_name]
        measure = self.measure_field_id.name if self.measure_field_id else None
        cur_total = compat.aggregate_one(Model, self._full_domain(filters, 'current'), measure, self.aggregate)
        prev_total = compat.aggregate_one(Model, self._full_domain(filters, which), measure, self.aggregate)
        candidates = []
        for fld in self._driver_fields():
            try:
                agg = {}
                for idx, w in ((0, 'current'), (1, which)):
                    for r in compat.read_groups(Model, self._full_domain(filters, w), [fld.name], measure, self.aggregate, limit=2000):
                        label, _s = self._label_for(fld, r, 0)
                        agg.setdefault(label, [0.0, 0.0])[idx] += r['value'] or 0
            except (AccessError, UserError):
                continue
            deltas = [abs(v[0] - v[1]) for v in agg.values()]
            total_abs = sum(deltas)
            if len(agg) < 2 or not total_abs:
                continue
            score = sum(sorted(deltas, reverse=True)[:3]) / total_abs
            blank = abs(agg.get(_('Undefined'), [0.0, 0.0])[0] - agg.get(_('Undefined'), [0.0, 0.0])[1]) / total_abs
            candidates.append({'field': fld, 'agg': agg, 'score': score, 'rich': len(agg) >= 5 and blank < 0.5})
        if not candidates:
            return {'error': _('There is no change to explain for this period, or no field splits it into groups.')}
        pick = next((c for c in candidates if c['field'].name == field_name), None)
        if not pick:
            pick = max(candidates, key=lambda c: (c['rich'], round(c['score'], 4), -len(c['agg'])))
        net = cur_total - prev_total
        ranked = sorted(pick['agg'].items(), key=lambda kv: -abs(kv[1][0] - kv[1][1]))
        top = ranked[:6]
        rest = sum(v[0] - v[1] for _k, v in ranked[6:])
        return {
            'current': cur_total, 'previous': prev_total, 'delta': net,
            'change_pct': round(net / abs(prev_total) * 100.0, 1) if prev_total else None,
            'field': pick['field'].field_description, 'field_name': pick['field'].name,
            'compare_label': _('previous year') if which == 'previous_year' else _('previous period'),
            'drivers': [{'label': k, 'current': v[0], 'previous': v[1], 'delta': v[0] - v[1],
                         'share': round((v[0] - v[1]) / net * 100.0, 1) if net else None} for k, v in top],
            'others': rest,
            'fields': [{'name': c['field'].name, 'label': c['field'].field_description} for c in candidates],
            'meta': self._meta(),
        }

    # -- charts and grouping
    def _gb_spec(self, fld):
        if fld.ttype in ('date', 'datetime'):
            return '%s:%s' % (fld.name, self.date_interval or 'month')
        return fld.name

    @staticmethod
    def _bucket_start(row, idx):
        start = compat.parse_bucket(row['ranges'][idx], None) if row.get('ranges') else None
        if not start:
            start = compat.parse_bucket(row['keys'][idx], None)
        return start

    def _label_for(self, fld, row, idx):
        Model = self.env[self.model_name]
        raw = row['keys'][idx]
        if fld.ttype in ('date', 'datetime'):
            start = self._bucket_start(row, idx)
            if start:
                return safe.bucket_label(start, self.date_interval or 'month'), start
            return (raw if isinstance(raw, str) and raw else _('Undefined')), None
        label = row['labels'][idx]
        if label in (None, False, ''):
            return _('Undefined'), None
        if fld.ttype == 'selection':
            mapping = dict(Model._fields[fld.name]._description_selection(self.env))
            return mapping.get(label, label), None
        if fld.ttype == 'boolean':
            return (_('Yes') if label else _('No')), None
        return str(label), None

    def _grouped(self, filters, which='current', extra=None, level_fields=None):
        """Rows for the chart: [(label, sort_key, domain, value)] for one group by,
        or a matrix when a second group by is used."""
        Model = self.env[self.model_name]
        measure = self.measure_field_id.name if self.measure_field_id else None
        domain = self._full_domain(filters, which, extra)
        specs = [self._gb_spec(f) for f in level_fields]
        raw = compat.read_groups(Model, domain, specs, measure, self.aggregate, limit=2000)
        return raw

    def _levels(self, drill):
        """Group by fields for the current drill level."""
        level = int((drill or {}).get('level') or 0)
        fields_ = [self.groupby_field_id]
        if level:
            path = [p.strip() for p in (self.drill_path or '').split(',') if p.strip()]
            if level > len(path):
                level = len(path)
            name = path[level - 1].split(':')[0]
            fld = self.env['ir.model.fields']._get(self.model_name, name)
            if not fld:
                raise UserError(_('The drill-down field "%s" does not exist on %s.', name, self.model_name))
            fields_ = [fld]
        elif self.groupby2_field_id and self.chart_type in ('bar', 'hbar', 'stacked', 'line', 'area'):
            fields_.append(self.groupby2_field_id)
        return fields_, level

    def _sorted_labels(self, rows, fld):
        """Order the first level groups according to the item settings."""
        is_date = fld.ttype in ('date', 'datetime')
        entries = {}
        for r in rows:
            label, start = self._label_for(fld, r, 0)
            e = entries.setdefault(label, {'label': label, 'start': start, 'total': 0.0, 'domain': None, 'ids': r['ids'][0]})
            e['total'] += r['value'] or 0
            e['domain'] = e['domain'] or None
        items = list(entries.values())
        if is_date or self.sort_by == 'label':
            items.sort(key=lambda e: (e['start'] or datetime.min.date(), str(e['label'])), reverse=(self.sort_dir == 'desc' and not is_date))
            if is_date and self.sort_dir == 'desc' and False:
                items.reverse()
        else:
            items.sort(key=lambda e: e['total'], reverse=(self.sort_dir == 'desc'))
        limit = self.limit if self.limit and self.limit > 0 else 500
        return items[:min(limit, 500)]

    def _compute_chart(self, filters, drill):
        Model = self.env[self.model_name]
        level_fields, level = self._levels(drill)
        extra = (drill or {}).get('domain') or []
        rows = self._grouped(filters, 'current', extra, level_fields)
        first = level_fields[0]
        order = self._sorted_labels(rows, first)
        labels = [e['label'] for e in order]
        index = {e['label']: i for i, e in enumerate(order)}
        domains = [None] * len(order)
        datasets = []
        if len(level_fields) == 2:
            second = level_fields[1]
            series = {}
            for r in rows:
                l1, _s1 = self._label_for(first, r, 0)
                if l1 not in index:
                    continue
                l2, _s2 = self._label_for(second, r, 1)
                data = series.setdefault(l2, [0.0] * len(order))
                data[index[l1]] += r['value'] or 0
                domains[index[l1]] = domains[index[l1]]
            # keep the five largest series and merge the rest
            ranked = sorted(series.items(), key=lambda kv: -sum(kv[1]))
            for name, data in ranked[:8]:
                datasets.append({'label': name, 'data': data})
        else:
            values = [0.0] * len(order)
            for r in rows:
                l1, _s = self._label_for(first, r, 0)
                if l1 in index:
                    values[index[l1]] += r['value'] or 0
            datasets.append({'label': self.measure_field_id.field_description if self.measure_field_id else _('Count'), 'data': values})
        # domains for drill-down: one lookup per group, computed from the groups themselves
        label_domain = {}
        for r in rows:
            l1, _s = self._label_for(first, r, 0)
            if l1 in index and l1 not in label_domain:
                label_domain[l1] = self._row_domain(r, first, 0)
        domains = [label_domain.get(l) for l in labels]
        out = {
            'labels': labels, 'datasets': datasets, 'domains': domains, 'res_model': self.model_name,
            'stacked': self.chart_type == 'stacked' or len(datasets) > 1,
            'drill': {'level': level, 'max': len([p for p in (self.drill_path or '').split(',') if p.strip()]),
                      'domain': extra},
        }
        self._chart_extras(out, rows, first, labels, filters, extra, level_fields)
        # compare with another period (single series only, aligned by position for dates and by label otherwise)
        if (self.compare_mode != 'none' and self.date_field_id and len(level_fields) == 1
                and (filters or {}).get('preset') not in (None, '', 'all')):
            which = 'previous_year' if self.compare_mode == 'previous_year' else 'previous'
            prev_rows = self._grouped(filters, which, extra, level_fields)
            prev_order = self._sorted_labels(prev_rows, first)
            is_date = first.ttype in ('date', 'datetime')
            prev_map = {}
            for r in prev_rows:
                l1, _s = self._label_for(first, r, 0)
                prev_map[l1] = prev_map.get(l1, 0.0) + (r['value'] or 0)
            if is_date:
                data = [prev_map.get(e['label'], 0.0) for e in prev_order][:len(labels)]
                data += [0.0] * (len(labels) - len(data))
            else:
                data = [prev_map.get(l, 0.0) for l in labels]
            out['datasets'].append({'label': _('Previous year') if which == 'previous_year' else _('Previous period'), 'data': data, 'compare': True})
        self._add_forecast(out, rows, first, level, level_fields)
        return out

    def _chart_extras(self, out, rows, first, labels, filters, extra, level_fields):
        """Data that only some chart types need: scatter points, map country codes, bullet target."""
        Model = self.env[self.model_name]
        if self.chart_type == 'bullet':
            out['target'] = self.target_value or 0
        elif self.chart_type == 'scatter':
            if not self.measure2_field_id:
                raise UserError(_('A scatter chart needs a second measure ("%s").', self.name))
            raw2 = compat.read_groups(Model, self._full_domain(filters, 'current', extra), [self._gb_spec(first)],
                                      self.measure2_field_id.name, self.aggregate, limit=2000)
            second = {}
            for r in raw2:
                lab, _s = self._label_for(first, r, 0)
                second[lab] = second.get(lab, 0.0) + (r['value'] or 0)
            ys = out['datasets'][0]['data'] if out['datasets'] else []
            out['points'] = [{'x': ys[i] if i < len(ys) else 0, 'y': second.get(lab, 0.0), 'label': lab} for i, lab in enumerate(labels)]
            out['x_label'] = self.measure_field_id.field_description if self.measure_field_id else _('Count')
            out['y_label'] = self.measure2_field_id.field_description
        elif self.chart_type == 'map':
            if first.ttype != 'many2one' or first.relation != 'res.country':
                raise UserError(_('A map groups by a country field ("%s").', self.name))
            ids = {}
            for r in rows:
                lab, _s = self._label_for(first, r, 0)
                if r['ids'][0] and lab not in ids:
                    ids[lab] = r['ids'][0]
            codes = {c['id']: c['code'] for c in self.env['res.country'].browse(list(ids.values())).read(['code'])}
            out['codes'] = [codes.get(ids.get(lab)) for lab in labels]

    def _row_domain(self, row, fld, idx):
        """Domain that selects the records of a group (used by drill-down and 'open records')."""
        if row.get('domain') and idx == 0 and not (len(row['keys']) > 1):
            return row['domain']
        raw = row['keys'][idx]
        name = fld.name
        if fld.ttype in ('date', 'datetime'):
            start = self._bucket_start(row, idx)
            if not start:
                return [(name, '=', False)]
            end = safe.bucket_end(start, self.date_interval or 'month') - timedelta(days=1)
            return self._date_domain(fld, start, end)
        if fld.ttype == 'many2one':
            rid = row['ids'][idx]
            return [(name, '=', rid or False)]
        if raw in (None, False):
            return [(name, '=', False)]
        return [(name, '=', raw)]

    # -- lists
    def _compute_list(self, filters, drill):
        Model = self.env[self.model_name]
        domain = self._full_domain(filters)
        flds = self.list_field_ids.filtered(lambda f: f.name in Model._fields)
        if not flds:
            names = [n for n in ('display_name',) if n in Model._fields] or ['id']
            cols = [{'name': 'display_name', 'label': _('Name'), 'type': 'char'}]
            fnames = []
        else:
            cols = [{'name': f.name, 'label': f.field_description, 'type': f.ttype} for f in flds]
            fnames = flds.mapped('name')
        limit = self.limit if self.limit and self.limit > 0 else 50
        order = self.list_order or False
        recs = Model.search(domain, order=order, limit=min(limit, 200))
        rows = []
        if fnames:
            data = recs.read(fnames)
            by_id = {d['id']: d for d in data}
            for rec in recs:
                d = by_id[rec.id]
                cells = []
                for f in flds:
                    v = d.get(f.name)
                    cells.append(self._cell(Model, f, v))
                rows.append({'id': rec.id, 'cells': cells})
        else:
            for rec in recs:
                rows.append({'id': rec.id, 'cells': [rec.display_name]})
        return {'columns': cols, 'rows': rows, 'res_model': self.model_name, 'domain': domain,
                'total': Model.search_count(domain)}

    def _cell(self, Model, f, v):
        if v is False or v is None:
            return ''
        if f.ttype == 'many2one':
            return v[1] if v else ''
        if f.ttype in ('one2many', 'many2many'):
            return _('%s records', len(v))
        if f.ttype == 'selection':
            return dict(Model._fields[f.name]._description_selection(self.env)).get(v, v)
        if f.ttype in ('date', 'datetime'):
            return str(v)
        if f.ttype == 'boolean':
            return _('Yes') if v else _('No')
        return v

    # -- formula
    def _formula_value(self, filters):
        codes = safe.formula_codes(self.formula)
        values = {}
        siblings = {i.code: i for i in self.dashboard_id.item_ids if i.code}
        for code in codes:
            item = siblings.get(code)
            if not item or item == self:
                raise UserError(_('The formula refers to an unknown item code: %s', code))
            if item.source_type == 'formula':
                raise UserError(_('A formula cannot use another formula item (%s).', code))
            if item.source_type in ('sql', 'external', 'file'):
                values[code] = item._rows_kpi_value(filters)
            else:
                values[code] = item._kpi_value(filters)
        return safe.eval_formula(self.formula, values)

    def _compute_formula(self, filters):
        return {'value': self._formula_value(filters), 'res_model': False}

    # -- SQL and external
    def _rows_source(self, filters):
        self.ensure_one()
        if self.source_type == 'file':
            return self._file_rows()
        if self.source_type == 'sql':
            return self.env['ax.dashboard.sqlrun'].run_local(self.sudo().sql_query, filters, limit=self.limit or 200)
        conn = self.sudo().connection_id
        if not conn:
            raise UserError(_('Choose a connection for "%s".', self.name))
        return conn.run(self.sudo().sql_query, filters, limit=self.limit or 200)

    def _file_rows(self):
        """Rows of an uploaded Excel or CSV file, grouped like a chart when the item is one."""
        self.ensure_one()
        header, data = filetable.read_table(self.sudo().data_file, self.data_filename)
        limit = self.limit if self.limit and self.limit > 0 else 500
        if self.item_type == 'list':
            wanted = [c.strip() for c in (self.file_columns or '').split(',') if c.strip()]
            idx = [filetable.column_index(header, c) for c in wanted] if wanted else list(range(len(header)))
            return [header[i] for i in idx], [[row[i] if i < len(row) else None for i in idx] for row in data[:min(limit, 200)]]
        mi = filetable.column_index(header, self.file_measure) if self.file_measure else None
        if self.item_type == 'kpi':
            gi = None
        else:
            gi = filetable.column_index(header, self.file_groupby)
        out = filetable.aggregate(data, gi, mi, self.aggregate or 'sum')
        if self.item_type == 'kpi':
            return ['value'], [[out.get(None, 0)]]
        rows = sorted(out.items(), key=(lambda kv: str(kv[0])) if self.sort_by == 'label' else (lambda kv: kv[1]),
                      reverse=(self.sort_dir == 'desc'))
        return [header[gi], header[mi] if mi is not None else _('Count')], [[k if k is not None else _('Undefined'), v] for k, v in rows[:min(limit, 500)]]

    def _rows_kpi_value(self, filters):
        cols, rows = self._rows_source(filters)
        for row in rows[:1]:
            for cell in row:
                if isinstance(cell, (int, float)):
                    return cell
        return 0

    def _compute_rows_source(self, filters):
        cols, rows = self._rows_source(filters)
        if self.item_type == 'kpi':
            value = 0
            for row in rows[:1]:
                for cell in row:
                    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
                        value = cell
                        break
            return {'value': value, 'res_model': False}
        if self.item_type == 'list':
            return {'columns': [{'name': c, 'label': c, 'type': 'char'} for c in cols],
                    'rows': [{'id': i, 'cells': [self._plain(c) for c in row]} for i, row in enumerate(rows)],
                    'res_model': False, 'total': len(rows)}
        labels = [str(r[0]) if r and r[0] is not None else _('Undefined') for r in rows]
        datasets = []
        for ci in range(1, len(cols)):
            vals = []
            numeric = True
            for r in rows:
                v = r[ci] if len(r) > ci else 0
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    vals.append(float(v))
                else:
                    numeric = False
                    break
            if numeric:
                datasets.append({'label': cols[ci], 'data': vals})
        out = {'labels': labels, 'datasets': datasets, 'domains': [None] * len(labels), 'res_model': False,
               'stacked': self.chart_type == 'stacked', 'drill': {'level': 0, 'max': 0, 'domain': []}}
        if self.chart_type == 'map':
            out['codes'] = [l.upper() if isinstance(l, str) and len(l) == 2 else None for l in labels]
        elif self.chart_type == 'bullet':
            out['target'] = self.target_value or 0
        elif self.chart_type == 'scatter' and len(datasets) >= 2:
            out['points'] = [{'x': datasets[0]['data'][i], 'y': datasets[1]['data'][i], 'label': l} for i, l in enumerate(labels)]
            out['x_label'], out['y_label'] = datasets[0]['label'], datasets[1]['label']
        return out

    @staticmethod
    def _plain(v):
        if v is None:
            return ''
        if isinstance(v, (int, float, str)):
            return v
        return str(v)

    # ------------------------------------------------------------------ actions
    def action_duplicate_item(self):
        self.ensure_one()
        new = self.copy({'name': _('%s (copy)', self.name), 'code': False})
        return {'type': 'ir.actions.act_window', 'res_model': 'ax.dashboard.item', 'res_id': new.id,
                'view_mode': 'form', 'target': 'new'}

    def action_move_to(self, dashboard_id):
        dashboard = self.env['ax.dashboard'].browse(dashboard_id)
        compat.check_access(dashboard, 'write')
        for item in self:
            x, y = self.env['ax.dashboard.item']._free_position(dashboard.id, item.grid_w, item.grid_h)
            item.write({'dashboard_id': dashboard.id, 'grid_x': x, 'grid_y': y, 'code': False})
        return True

    def toggle_todo(self, line_id, done):
        self.ensure_one()
        compat.check_access(self, 'read')
        line = self.env['ax.dashboard.todo'].sudo().browse(line_id)
        if line.item_id != self:
            raise AccessError(_('This line belongs to another item.'))
        line.write({'done': bool(done)})
        return True

    def add_todo(self, text):
        self.ensure_one()
        compat.check_access(self, 'read')
        text = (text or '').strip()
        if not text:
            raise UserError(_('The task is empty.'))
        self.env['ax.dashboard.todo'].sudo().create({'item_id': self.id, 'name': text[:200], 'user_id': self.env.uid})
        return self.sudo()._compute_todo()

    def remove_todo(self, line_id):
        self.ensure_one()
        compat.check_access(self, 'read')
        line = self.env['ax.dashboard.todo'].sudo().browse(line_id)
        if line.item_id != self:
            raise AccessError(_('This line belongs to another item.'))
        line.unlink()
        return True

    def ai_insight(self, filters=None):
        """Short written summary of this item, written by the configured AI provider."""
        self.ensure_one()
        return self.env['ax.dashboard.ai'].summarize_item(self, filters)

    def quick_update(self, vals):
        """Allowed changes from the quick-edit toolbar."""
        allowed = {'name', 'chart_type', 'color_scheme', 'show_legend', 'show_labels', 'kpi_color', 'kpi_icon', 'number_format'}
        bad = set(vals) - allowed
        if bad:
            raise AccessError(_('This change is not allowed from quick edit: %s', ', '.join(sorted(bad))))
        self.write(vals)
        return True

    # ------------------------------------------------------------------ export and import
    _EXPORT = ['name', 'code', 'description', 'item_type', 'source_type', 'domain', 'aggregate', 'date_interval',
               'sort_by', 'sort_dir', 'limit', 'list_order', 'chart_type', 'color_scheme', 'custom_colors',
               'show_legend', 'show_labels', 'kpi_icon', 'kpi_color', 'target_value', 'forecast_periods', 'compare_mode',
               'number_format', 'decimals', 'prefix', 'suffix', 'formula', 'drill_path', 'snapshot_enabled', 'snapshot_preset',
               'file_groupby', 'file_measure', 'file_columns', 'alert_enabled', 'alert_min', 'alert_max', 'use_alert_min', 'use_alert_max', 'anomaly_enabled',
               'grid_x', 'grid_y', 'grid_w', 'grid_h']

    def export_dict(self, with_sql=False):
        self.ensure_one()
        d = {k: self[k] for k in self._EXPORT}
        d['model'] = self.model_name or False
        for key, out in (('measure_field_id', 'measure'), ('groupby_field_id', 'groupby'),
                         ('groupby2_field_id', 'groupby2'), ('date_field_id', 'date_field'), ('measure2_field_id', 'measure2')):
            d[out] = self[key].name or False
        d['list_fields'] = self.list_field_ids.mapped('name')
        d['currency'] = self.currency_id.name or False
        d['todo'] = [{'name': l.name, 'done': l.done} for l in self.todo_line_ids]
        if with_sql and self.source_type == 'sql':
            d['sql_query'] = self.sudo().sql_query
        return d

    @api.model
    def values_from_dict(self, d, dashboard):
        """Translate an exported item into create() values. Returns (vals, warnings)."""
        warnings = []
        vals = {k: d[k] for k in self._EXPORT if k in d}
        vals['dashboard_id'] = dashboard.id
        Fields = self.env['ir.model.fields']
        if d.get('source_type') in ('sql', 'external', 'file'):
            warnings.append(_('"%s" uses SQL, a file or an external source and was skipped. Add such items by hand.', d.get('name')))
            return None, warnings
        if d.get('model'):
            model = self.env['ir.model']._get(d['model'])
            if not model or d['model'] not in self.env:
                warnings.append(_('"%(name)s" needs the model %(model)s, which is not installed.', name=d.get('name'), model=d['model']))
                return None, warnings
            vals['model_id'] = model.id
            for key in ('measure', 'measure2', 'groupby', 'groupby2', 'date_field'):
                if d.get(key):
                    fld = Fields._get(d['model'], d[key])
                    if not fld:
                        warnings.append(_('"%(name)s" uses the field %(field)s, which does not exist on %(model)s.', name=d.get('name'), field=d[key], model=d['model']))
                        return None, warnings
                    vals[{'measure': 'measure_field_id', 'groupby': 'groupby_field_id', 'groupby2': 'groupby2_field_id', 'date_field': 'date_field_id', 'measure2': 'measure2_field_id'}[key]] = fld.id
            lf = []
            for name in d.get('list_fields') or []:
                fld = Fields._get(d['model'], name)
                if fld:
                    lf.append(fld.id)
            if lf:
                vals['list_field_ids'] = [(6, 0, lf)]
        if d.get('currency'):
            cur = self.env['res.currency'].search([('name', '=', d['currency'])], limit=1)
            if cur:
                vals['currency_id'] = cur.id
        if d.get('todo'):
            vals['todo_line_ids'] = [(0, 0, {'name': t['name'], 'done': t.get('done', False)}) for t in d['todo']]
        return vals, warnings
