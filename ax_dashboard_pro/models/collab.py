# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class AxDashboardComment(models.Model):
    _name = 'ax.dashboard.comment'
    _description = 'Dashboard comment'
    _order = 'create_date desc, id desc'

    dashboard_id = fields.Many2one('ax.dashboard', required=True, ondelete='cascade', index=True)
    item_id = fields.Many2one('ax.dashboard.item', ondelete='cascade', domain="[('dashboard_id', '=', dashboard_id)]")
    user_id = fields.Many2one('res.users', required=True, default=lambda s: s.env.user, readonly=True)
    body = fields.Text(required=True)
    mention_ids = fields.Many2many('res.users', 'ax_dashboard_comment_mention_rel', 'comment_id', 'user_id', string='Mentions')

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        for rec in recs:
            if rec.mention_ids:
                rec.dashboard_id.message_post(
                    body=_('%(user)s mentioned you in a comment%(item)s: %(body)s', user=rec.user_id.name,
                           item=(_(' on "%s"', rec.item_id.name) if rec.item_id else ''), body=rec.body),
                    partner_ids=rec.mention_ids.partner_id.ids, subtype_xmlid='mail.mt_comment')
            rec.dashboard_id._log('comment', rec.body[:120], item=rec.item_id)
        return recs

    def write(self, vals):
        for rec in self:
            if rec.user_id != self.env.user and not self.env.user.has_group('ax_dashboard_pro.group_ax_dashboard_manager'):
                raise AccessError(_('You can only change your own comments.'))
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.user_id != self.env.user and not self.env.user.has_group('ax_dashboard_pro.group_ax_dashboard_manager'):
                raise AccessError(_('You can only delete your own comments.'))
        return super().unlink()

    @api.model
    def list_for(self, dashboard_id, item_id=False):
        domain = [('dashboard_id', '=', dashboard_id)]
        if item_id:
            domain.append(('item_id', '=', item_id))
        return [{'id': c.id, 'user': c.user_id.name, 'body': c.body, 'item': c.item_id.name or '',
                 'date': fields.Datetime.to_string(c.create_date), 'mine': c.user_id == self.env.user}
                for c in self.search(domain, limit=100)]

    @api.model
    def post(self, dashboard_id, body, item_id=False):
        body = (body or '').strip()
        if not body:
            raise UserError(_('A comment cannot be empty.'))
        if not self.env['ax.dashboard'].search_count([('id', '=', dashboard_id)]):
            raise AccessError(_('You cannot open this dashboard.'))
        mentions = self.env['res.users']
        for word in body.split():
            if word.startswith('@') and len(word) > 1:
                mentions |= self.env['res.users'].search([('login', '=ilike', word[1:]), ('share', '=', False)], limit=1)
        rec = self.sudo().create({'dashboard_id': dashboard_id, 'item_id': item_id or False, 'body': body,
                                  'user_id': self.env.uid, 'mention_ids': [(6, 0, mentions.ids)]})
        return rec.id


class AxDashboardLog(models.Model):
    _name = 'ax.dashboard.log'
    _description = 'Dashboard activity log'
    _order = 'id desc'

    dashboard_id = fields.Many2one('ax.dashboard', ondelete='cascade', index=True)
    item_id = fields.Many2one('ax.dashboard.item', ondelete='set null')
    user_id = fields.Many2one('res.users', ondelete='set null')
    action = fields.Selection([('view', 'Viewed'), ('create', 'Created'), ('edit', 'Edited'), ('share', 'Sharing changed'),
                               ('export', 'Exported'), ('import', 'Imported'), ('restore', 'Version restored'),
                               ('comment', 'Comment'), ('ai', 'AI'), ('sql', 'SQL'), ('alert', 'Alert'),
                               ('email', 'Email report')], required=True)
    detail = fields.Char()


class AxDashboardPerf(models.Model):
    _name = 'ax.dashboard.perf'
    _description = 'Slow or failing dashboard items'
    _order = 'id desc'

    item_id = fields.Many2one('ax.dashboard.item', ondelete='cascade', index=True)
    dashboard_id = fields.Many2one('ax.dashboard', ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', ondelete='set null')
    ms = fields.Integer(string='Duration (ms)')
    error = fields.Char()
    day = fields.Date(default=fields.Date.today, index=True)
