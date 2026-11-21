# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
import json
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from . import compat, safe

_logger = logging.getLogger(__name__)

THEMES = [('navy', 'Navy'), ('ocean', 'Ocean'), ('slate', 'Slate'), ('midnight', 'Midnight'),
          ('emerald', 'Emerald'), ('sunset', 'Sunset'), ('light', 'Light')]
VERSION_LIMIT = 40


class AxDashboard(models.Model):
    _name = 'ax.dashboard'
    _description = 'Dashboard'
    _inherit = ['mail.thread']
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True, tracking=True)
    description = fields.Char(translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    owner_id = fields.Many2one('res.users', string='Owner', default=lambda s: s.env.user, required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Company', help='Leave empty to show the dashboard in every company.')
    shared_all = fields.Boolean(string='Visible to every dashboard user', default=False,
                                help='Off by default: a dashboard is private to its owner until you share it.')
    user_ids = fields.Many2many('res.users', 'ax_dashboard_user_rel', 'dashboard_id', 'user_id', string='Shared with users (view)')
    edit_user_ids = fields.Many2many('res.users', 'ax_dashboard_edit_user_rel', 'dashboard_id', 'user_id', string='Shared with users (edit)')
    group_ids = fields.Many2many('res.groups', 'ax_dashboard_group_rel', 'dashboard_id', 'group_id', string='Shared with groups')
    theme = fields.Selection(THEMES, default='navy', required=True)
    default_date_preset = fields.Selection(safe.PRESETS, default='this_month', required=True, string='Default date filter')
    refresh_seconds = fields.Integer(string='Auto refresh (seconds)', default=0, help='0 switches automatic refresh off. Minimum 15.')
    tv_seconds = fields.Integer(string='TV mode seconds per dashboard', default=30)
    item_ids = fields.One2many('ax.dashboard.item', 'dashboard_id', string='Items', copy=True)
    filter_ids = fields.One2many('ax.dashboard.filter', 'dashboard_id', string='Filters', copy=True)
    schedule_ids = fields.One2many('ax.dashboard.schedule', 'dashboard_id', string='Email reports')
    version_ids = fields.One2many('ax.dashboard.version', 'dashboard_id', string='Versions')
    comment_ids = fields.One2many('ax.dashboard.comment', 'dashboard_id', string='Comments')
    show_in_menu = fields.Boolean(string='Show in the Apps menu', copy=False,
                                  help='Adds a menu entry that opens this dashboard directly.')
    menu_parent_id = fields.Many2one('ir.ui.menu', string='Parent menu', copy=False,
                                     help='Leave empty to add the entry under the Dashboards menu.')
    menu_id = fields.Many2one('ir.ui.menu', string='Menu entry', copy=False, readonly=True, ondelete='set null')
    item_count = fields.Integer(compute='_compute_counts')
    version_count = fields.Integer(compute='_compute_counts')
    comment_count = fields.Integer(compute='_compute_counts')
    can_edit = fields.Boolean(compute='_compute_can_edit')
    share_summary = fields.Char(compute='_compute_share_summary')

    _tv_positive = models.Constraint('CHECK(tv_seconds >= 0)', 'TV seconds cannot be negative.')

    # ------------------------------------------------------------------ computed
    @api.depends('item_ids', 'version_ids', 'comment_ids')
    def _compute_counts(self):
        for rec in self:
            rec.item_count = len(rec.item_ids)
            rec.version_count = len(rec.version_ids)
            rec.comment_count = len(rec.comment_ids)

    @api.depends_context('uid')
    def _compute_can_edit(self):
        user = self.env.user
        manager = user.has_group('ax_dashboard_pro.group_ax_dashboard_manager')
        builder = user.has_group('ax_dashboard_pro.group_ax_dashboard_builder')
        for rec in self:
            rec.can_edit = manager or (builder and (rec.owner_id == user or user in rec.edit_user_ids))

    @api.depends('user_ids', 'edit_user_ids', 'group_ids', 'shared_all')
    def _compute_share_summary(self):
        for rec in self:
            parts = []
            if rec.user_ids or rec.edit_user_ids:
                parts.append(_('%s users', len(rec.user_ids | rec.edit_user_ids)))
            if rec.group_ids:
                parts.append(_('%s groups', len(rec.group_ids)))
            if rec.shared_all:
                parts.append(_('Everyone with dashboard access'))
            rec.share_summary = ', '.join(parts) if parts else _('Private')

    # ------------------------------------------------------------------ logging
    def _log(self, action, detail=False, item=None):
        if self.env.context.get('ax_no_log'):
            return
        vals = []
        for rec in self:
            vals.append({'dashboard_id': rec.id, 'user_id': self.env.uid, 'action': action,
                         'detail': detail or False, 'item_id': item.id if item else False})
        if vals:
            self.env['ax.dashboard.log'].sudo().create(vals)

    # ------------------------------------------------------------------ crud
    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('show_in_menu') or v.get('menu_parent_id') for v in vals_list):
            self._check_menu_rights()
        recs = super().create(vals_list)
        recs._log('create', _('Dashboard created'))
        recs.filtered('show_in_menu')._sync_menu()
        return recs

    @api.model
    def _check_menu_rights(self):
        if not self.env.user.has_group('ax_dashboard_pro.group_ax_dashboard_manager'):
            raise AccessError(_('Only Dashboard Managers can add dashboards to the Apps menu.'))

    def _sync_menu(self):
        """Create, update or remove the menu entry that opens each dashboard. Runs with elevated rights on purpose:
        menus are technical records, and the caller was checked in _check_menu_rights."""
        Menu = self.env['ir.ui.menu'].sudo()
        gfield = 'group_ids' if 'group_ids' in Menu._fields else 'groups_id'
        group = self.env.ref('ax_dashboard_pro.group_ax_dashboard_user')
        for rec in self.sudo():
            if not (rec.show_in_menu and rec.active):
                if rec.menu_id:
                    action = rec.menu_id.action
                    rec.menu_id.unlink()
                    if action and action._name == 'ir.actions.client':
                        action.unlink()
                continue
            parent = rec.menu_parent_id or self.env.ref('ax_dashboard_pro.menu_ax_dashboard_root', raise_if_not_found=False)
            act_vals = {'name': rec.name, 'tag': 'ax_dashboard_pro.client', 'context': "{'dashboard_id': %d}" % rec.id}
            if rec.menu_id:
                action = rec.menu_id.action
                if action and action._name == 'ir.actions.client':
                    action.write(act_vals)
                rec.menu_id.write({'name': rec.name, 'parent_id': parent.id if parent else False})
            else:
                action = self.env['ir.actions.client'].sudo().create(act_vals)
                menu = Menu.create({'name': rec.name, 'parent_id': parent.id if parent else False,
                                    'action': '%s,%d' % (action._name, action.id), 'sequence': 50 + rec.sequence,
                                    gfield: [(6, 0, [group.id])]})
                rec.with_context(ax_skip_version=True).write({'menu_id': menu.id})

    def unlink(self):
        menus = self.mapped('menu_id').sudo()
        actions = self.env['ir.actions.client'].sudo()
        for menu in menus:
            if menu.action and menu.action._name == 'ir.actions.client':
                actions |= menu.action
        res = super().unlink()
        menus.unlink()
        actions.unlink()
        return res

    def write(self, vals):
        if {'show_in_menu', 'menu_parent_id'} & set(vals):
            self._check_menu_rights()
        res = super().write(vals)
        if {'show_in_menu', 'menu_parent_id', 'name', 'active', 'sequence'} & set(vals):
            self.filtered(lambda d: d.show_in_menu or d.menu_id)._sync_menu()
        tracked = set(vals) - {'sequence', 'version_ids', 'comment_ids'}
        if tracked and not self.env.context.get('ax_skip_version'):
            self._snapshot_version(_('Dashboard changed'))
            if {'user_ids', 'edit_user_ids', 'group_ids', 'owner_id', 'shared_all'} & set(vals):
                self._log('share', _('Sharing changed'))
        return res

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault('name', _('%s (copy)', self.name))
        default.setdefault('owner_id', self.env.uid)
        default.setdefault('shared_all', False)
        default.setdefault('user_ids', False)
        default.setdefault('edit_user_ids', False)
        new = super().copy(default)
        # codes must stay unique per dashboard: the copy has its own namespace, so keep them
        new._log('create', _('Duplicated from %s', self.name))
        return new

    def action_duplicate(self):
        self.ensure_one()
        new = self.copy()
        return new.action_open()

    # ------------------------------------------------------------------ versions
    def _snapshot_version(self, note, force_new=False):
        if self.env.context.get('ax_skip_version'):
            return
        Version = self.env['ax.dashboard.version'].sudo()
        for rec in self:
            if not rec.id:
                continue
            data = rec.export_dict()
            last = Version.search([('dashboard_id', '=', rec.id)], order='id desc', limit=1)
            recent = (not force_new) and last and last.user_id.id == self.env.uid and (fields.Datetime.now() - last.create_date) < timedelta(seconds=60)
            if recent:
                # edits made in quick succession by the same person share one version
                last.write({'data': json.dumps(data), 'note': note})
            else:
                number = (last.number + 1) if last else 1
                Version.create({'dashboard_id': rec.id, 'number': number, 'note': note,
                                'data': json.dumps(data), 'user_id': self.env.uid})
            old = Version.search([('dashboard_id', '=', rec.id)], order='id desc', offset=VERSION_LIMIT)
            if old:
                old.unlink()

    def restore_version(self, version_id):
        self.ensure_one()
        version = self.env['ax.dashboard.version'].browse(version_id)
        if version.dashboard_id != self:
            raise AccessError(_('This version belongs to another dashboard.'))
        self._check_can_edit()
        data = json.loads(version.data)     # read first: the snapshot below must never touch the version being restored
        number = version.number
        self._snapshot_version(_('Before restoring version %s', number), force_new=True)
        self.with_context(ax_skip_version=True)._apply_dict(data, replace=True)
        self._snapshot_version(_('Restored version %s', number), force_new=True)
        self._log('restore', _('Restored version %s', number))
        return True

    # ------------------------------------------------------------------ access
    def _check_can_edit(self):
        for rec in self:
            if not rec.can_edit:
                raise AccessError(_('You are not allowed to change the dashboard "%s".', rec.name))
            compat.check_access(rec, 'write')

    # ------------------------------------------------------------------ export / import
    def export_dict(self, with_sql=False):
        self.ensure_one()
        return {
            'format': 'axsync_dashboard', 'format_version': 1,
            'name': self.name, 'description': self.description or '', 'theme': self.theme,
            'default_date_preset': self.default_date_preset, 'refresh_seconds': self.refresh_seconds,
            'tv_seconds': self.tv_seconds,
            'filters': [f.export_dict() for f in self.filter_ids],
            'items': [i.export_dict(with_sql=with_sql) for i in self.item_ids],
        }

    def export_json(self):
        self.ensure_one()
        self._log('export', _('Dashboard exported'))
        return json.dumps(self.export_dict(), indent=2, ensure_ascii=False, default=str)

    def _apply_dict(self, data, replace=False):
        """Create the items and filters of ``data`` in this dashboard. Returns warnings."""
        self.ensure_one()
        warnings = []
        Item = self.env['ax.dashboard.item']
        if replace:
            self.item_ids.unlink()
            self.filter_ids.unlink()
            self.write({k: data[k] for k in ('theme', 'default_date_preset', 'refresh_seconds', 'tv_seconds', 'description') if k in data})
            if data.get('name'):
                self.name = data['name']
        for f in data.get('filters') or []:
            self.env['ax.dashboard.filter'].create({'dashboard_id': self.id, 'name': f.get('name') or f.get('field'),
                                                    'field_name': f['field']})
        for d in data.get('items') or []:
            vals, warn = Item.values_from_dict(d, self)
            warnings += warn
            if vals:
                try:
                    with self.env.cr.savepoint():
                        Item.with_context(ax_skip_version=True).create(vals)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(_('"%(name)s" could not be created: %(err)s', name=d.get('name'), err=exc))
        return warnings

    @api.model
    def import_json(self, text):
        try:
            data = json.loads(text)
        except ValueError:
            raise UserError(_('This file is not a valid dashboard export (invalid JSON).'))
        if not isinstance(data, dict) or data.get('format') != 'axsync_dashboard':
            raise UserError(_('This file is not an AXSync dashboard export.'))
        dash = self.with_context(ax_skip_version=True).create({
            'name': data.get('name') or _('Imported dashboard'), 'description': data.get('description'),
            'theme': data.get('theme') if data.get('theme') in dict(THEMES) else 'navy',
            'default_date_preset': data.get('default_date_preset') if data.get('default_date_preset') in safe.PRESET_KEYS else 'this_month',
            'refresh_seconds': data.get('refresh_seconds') or 0, 'tv_seconds': data.get('tv_seconds') or 30,
        })
        warnings = dash._apply_dict(data)
        dash._snapshot_version(_('Imported'))
        dash._log('import', _('Dashboard imported'))
        return dash, warnings

    # ------------------------------------------------------------------ client API
    @api.model
    def list_dashboards(self):
        """The dashboards the current user may open, for the selector."""
        out = []
        company_ids = self.env.companies.ids
        for d in self.search([]):
            if d.company_id and d.company_id.id not in company_ids:
                continue
            out.append({'id': d.id, 'name': d.name, 'theme': d.theme, 'can_edit': d.can_edit, 'item_count': d.item_count})
        return out

    @api.model
    def user_context(self):
        user = self.env.user
        return {
            'can_build': user.has_group('ax_dashboard_pro.group_ax_dashboard_builder'),
            'is_manager': user.has_group('ax_dashboard_pro.group_ax_dashboard_manager'),
            'ai_enabled': bool(compat.get_param(self.env, 'ax_dashboard_pro.ai_api_key')),
            'presets': [(k, str(v)) for k, v in safe.PRESETS],
            'tz': user.tz or 'UTC',
        }

    def load_dashboard(self):
        """Layout, filters and per-user preferences of one dashboard. Item data is requested separately."""
        self.ensure_one()
        prefs = self.env['ax.dashboard.pref'].get_prefs(self.id)
        layout_over = prefs.get('layout') or {}
        items = []
        for it in self.item_ids:
            pos = layout_over.get(str(it.id)) or {}
            items.append({
                'id': it.id, 'name': it.name, 'item_type': it.item_type, 'chart_type': it.chart_type,
                'x': pos.get('x', it.grid_x), 'y': pos.get('y', it.grid_y),
                'w': pos.get('w', it.grid_w), 'h': pos.get('h', it.grid_h),
                'code': it.code, 'has_alert': it.alert_enabled,
            })
        filters = [{'id': f.id, 'name': f.name, 'field': f.field_name, 'kind': f.kind} for f in self.filter_ids]
        self._log_view()
        return {
            'id': self.id, 'name': self.name, 'description': self.description or '',
            'theme': prefs.get('theme') or self.theme, 'default_date_preset': prefs.get('date_preset') or self.default_date_preset,
            'refresh_seconds': self.refresh_seconds, 'tv_seconds': self.tv_seconds, 'can_edit': self.can_edit,
            'items': items, 'filters': filters, 'prefs': prefs, 'bookmarks': self.env['ax.dashboard.bookmark'].list_for(self.id),
            'comment_count': self.comment_count, 'owner': self.owner_id.name,
        }

    def _log_view(self):
        Log = self.env['ax.dashboard.log'].sudo()
        since = fields.Datetime.now() - timedelta(minutes=10)
        if not Log.search_count([('dashboard_id', '=', self.id), ('user_id', '=', self.env.uid),
                                 ('action', '=', 'view'), ('create_date', '>=', since)]):
            self._log('view')

    def save_layout(self, layout, personal=False):
        """``layout``: list of {id, x, y, w, h}. Personal layouts are only stored for the user."""
        self.ensure_one()
        ids = {i.id for i in self.item_ids}
        clean = {}
        for row in layout or []:
            if row.get('id') in ids:
                clean[str(row['id'])] = {k: max(int(row.get(k) or 0), 0) for k in ('x', 'y', 'w', 'h')}
                clean[str(row['id'])]['w'] = max(1, min(clean[str(row['id'])]['w'], 12))
                clean[str(row['id'])]['h'] = max(1, clean[str(row['id'])]['h'])
        if personal:
            self.env['ax.dashboard.pref'].set_pref(self.id, {'layout': clean})
            return True
        self._check_can_edit()
        for item in self.item_ids:
            pos = clean.get(str(item.id))
            if pos:
                item.with_context(ax_skip_version=True).write({'grid_x': pos['x'], 'grid_y': pos['y'], 'grid_w': pos['w'], 'grid_h': pos['h']})
        self.env['ax.dashboard.pref'].set_pref(self.id, {'layout': {}})
        self._snapshot_version(_('Layout changed'))
        self._log('edit', _('Layout changed'))
        return True

    def action_open(self):
        self.ensure_one()
        return {'type': 'ir.actions.client', 'tag': 'ax_dashboard_pro.client', 'name': self.name,
                'params': {'dashboard_id': self.id}, 'context': {'dashboard_id': self.id}}

    @api.model
    def action_open_default(self):
        return {'type': 'ir.actions.client', 'tag': 'ax_dashboard_pro.client', 'name': _('Dashboards')}

    def action_add_item(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ax.dashboard.item', 'view_mode': 'form',
                'target': 'new', 'context': {'default_dashboard_id': self.id}}

    def action_view_versions(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Versions'), 'res_model': 'ax.dashboard.version',
                'view_mode': 'list,form', 'domain': [('dashboard_id', '=', self.id)]}

    def action_view_logs(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Activity log'), 'res_model': 'ax.dashboard.log',
                'view_mode': 'list,form', 'domain': [('dashboard_id', '=', self.id)]}

    def action_view_comments(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Comments'), 'res_model': 'ax.dashboard.comment',
                'view_mode': 'list,form', 'domain': [('dashboard_id', '=', self.id)],
                'context': {'default_dashboard_id': self.id}}

    def action_save_as_template(self):
        self.ensure_one()
        tpl = self.env['ax.dashboard.template'].create({
            'name': self.name, 'description': self.description or _('Saved from a dashboard'),
            'category': 'custom', 'data': self.export_json(),
        })
        return {'type': 'ir.actions.act_window', 'res_model': 'ax.dashboard.template', 'res_id': tpl.id, 'view_mode': 'form'}
