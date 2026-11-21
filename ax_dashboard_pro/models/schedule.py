# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
import logging
from datetime import datetime, timedelta

from odoo import tools, _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from . import safe

_logger = logging.getLogger(__name__)


class AxDashboardSchedule(models.Model):
    _name = 'ax.dashboard.schedule'
    _description = 'Scheduled dashboard email'

    name = fields.Char(required=True)
    dashboard_id = fields.Many2one('ax.dashboard', required=True, ondelete='cascade', index=True)
    active = fields.Boolean(default=True)
    user_ids = fields.Many2many('res.users', 'ax_dashboard_schedule_user_rel', 'schedule_id', 'user_id', string='Recipients')
    extra_emails = fields.Char(string='Other emails', help='Comma separated addresses.')
    frequency = fields.Selection([('daily', 'Daily'), ('weekly', 'Weekly'), ('monthly', 'Monthly')], default='weekly', required=True)
    weekday = fields.Selection([('0', 'Monday'), ('1', 'Tuesday'), ('2', 'Wednesday'), ('3', 'Thursday'), ('4', 'Friday'),
                                ('5', 'Saturday'), ('6', 'Sunday')], default='0')
    month_day = fields.Integer(default=1)
    hour = fields.Integer(default=8, help='Hour of the day (server time, 0 to 23).')
    date_preset = fields.Selection([(k, v) for k, v in safe.PRESETS if k != 'custom'], default='last_30', required=True, string='Period')
    attach_xlsx = fields.Boolean(string='Attach Excel', default=True)
    attach_pdf = fields.Boolean(string='Attach PDF', default=True)
    last_run = fields.Datetime(readonly=True)
    next_run = fields.Datetime(compute='_compute_next_run', store=True, readonly=False)

    @api.constrains('hour', 'month_day')
    def _check_values(self):
        for rec in self:
            if not 0 <= rec.hour <= 23:
                raise ValidationError(_('The hour must be between 0 and 23.'))
            if not 1 <= rec.month_day <= 28:
                raise ValidationError(_('The day of the month must be between 1 and 28.'))

    @api.depends('frequency', 'weekday', 'month_day', 'hour', 'last_run')
    def _compute_next_run(self):
        for rec in self:
            rec.next_run = rec._next_after(rec.last_run or fields.Datetime.now())

    def _next_after(self, base):
        self.ensure_one()
        hour = self.hour or 0
        if self.frequency == 'daily':
            cand = base.replace(hour=hour, minute=0, second=0, microsecond=0)
            if cand <= base:
                cand += timedelta(days=1)
        elif self.frequency == 'weekly':
            wd = int(self.weekday or 0)
            cand = base.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=(wd - base.weekday()) % 7)
            if cand <= base:
                cand += timedelta(days=7)
        else:
            cand = base.replace(day=min(self.month_day or 1, 28), hour=hour, minute=0, second=0, microsecond=0)
            if cand <= base:
                m = cand.month % 12 + 1
                y = cand.year + (1 if cand.month == 12 else 0)
                cand = cand.replace(year=y, month=m)
        return cand

    def _recipients(self):
        self.ensure_one()
        mails = [u.email for u in self.user_ids if u.email]
        mails += tools.email_split(self.extra_emails or '')
        seen, out = set(), []
        for m in mails:
            if m.lower() not in seen:
                seen.add(m.lower())
                out.append(m)
        return out

    def action_send_now(self):
        for rec in self:
            rec._send()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Email report'), 'message': _('The report was queued for sending.'), 'type': 'success'}}

    def _send(self):
        self.ensure_one()
        dash = self.dashboard_id
        owner = dash.owner_id
        if not owner.active:
            raise UserError(_('The owner of this dashboard is archived.'))
        recipients = self._recipients()
        if not recipients:
            raise UserError(_('Add at least one recipient.'))
        dash_o = dash.with_user(owner)
        filters = {'preset': self.date_preset}
        items = dash_o.item_ids.filtered(lambda i: i.item_type != 'todo')
        datas = [i.get_data(filters) for i in items]
        exporter = self.env['ax.dashboard.exporter']
        label = dict(safe.PRESETS).get(self.date_preset, self.date_preset)
        subtitle = '%s | %s' % (label, fields.Date.today())
        attachments = []
        if self.attach_xlsx:
            attachments.append((0, 0, {'name': '%s.xlsx' % dash.name, 'raw': exporter.to_xlsx(datas, dash.name),
                                        'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}))
        if self.attach_pdf:
            attachments.append((0, 0, {'name': '%s.pdf' % dash.name, 'raw': exporter.to_pdf(dash.name, datas, subtitle),
                                        'mimetype': 'application/pdf'}))
        mail = self.env['mail.mail'].sudo().create({
            'subject': _('%(d)s: %(p)s report', d=dash.name, p=label),
            'body_html': exporter.dashboard_html(dash, datas, subtitle),
            'email_to': ','.join(recipients),
            'email_from': owner.email_formatted or self.env.company.email_formatted,
            'attachment_ids': attachments,
            'auto_delete': True,
        })
        self.sudo().write({'last_run': fields.Datetime.now()})
        dash._log('email', _('Report sent to %s recipients', len(recipients)))
        return mail

    @api.model
    def _cron_send_due(self):
        now = fields.Datetime.now()
        for rec in self.search([('active', '=', True), ('next_run', '<=', now)]):
            try:
                with self.env.cr.savepoint():
                    rec._send()
            except Exception:  # noqa: BLE001
                _logger.exception('Dashboard email %s failed', rec.id)
                rec.sudo().write({'last_run': now})
