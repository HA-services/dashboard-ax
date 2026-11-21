# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
import ipaddress
import json
import logging
import socket
from urllib.parse import urlparse

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import compat, safe
from .sqlrun import clean_cell

_logger = logging.getLogger(__name__)
# Tests replace this with a function (method, url, headers, timeout) -> (status, text)
HTTP_TRANSPORT = None


class AxDashboardConnection(models.Model):
    _name = 'ax.dashboard.connection'
    _description = 'External data connection'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    conn_type = fields.Selection([('postgres', 'PostgreSQL'), ('mysql', 'MySQL / MariaDB'), ('api', 'JSON API')],
                                 required=True, default='postgres', string='Type')
    host = fields.Char()
    port = fields.Integer()
    dbname = fields.Char(string='Database')
    db_user = fields.Char(string='User')
    password = fields.Char(string='Password', groups='ax_dashboard_pro.group_ax_dashboard_manager')
    sslmode = fields.Selection([('prefer', 'Prefer'), ('require', 'Require'), ('verify-full', 'Verify full'), ('disable', 'Disable')],
                               default='prefer')
    base_url = fields.Char(string='Base URL', help='For JSON APIs, for example https://api.example.com/v1')
    auth_header = fields.Char(string='Auth header name', default='Authorization')
    auth_value = fields.Char(string='Auth header value', groups='ax_dashboard_pro.group_ax_dashboard_manager',
                             help='For example: Bearer abc123. Stored in the database, only managers can read it.')
    timeout = fields.Integer(default=10)
    last_test = fields.Char(readonly=True)

    @api.constrains('timeout')
    def _check_timeout(self):
        for rec in self:
            if not 1 <= rec.timeout <= 60:
                raise UserError(_('The timeout must be between 1 and 60 seconds.'))

    # ------------------------------------------------------------------ execution
    def run(self, query, filters=None, limit=200):
        self.ensure_one()
        if self.conn_type == 'api':
            return self._run_api(query, limit)
        text = safe.check_readonly_sql(self.env['ax.dashboard.sqlrun'].fill_tokens(query or '', filters))
        limit = max(1, min(int(limit or 200), 2000))
        wrapped = 'SELECT * FROM (%s) AS ax_dashboard_q LIMIT %d' % (text, limit)
        if self.conn_type == 'postgres':
            return self._run_postgres(wrapped)
        return self._run_mysql(wrapped)

    def _run_postgres(self, sql):
        import psycopg2
        opts = '-c default_transaction_read_only=on -c statement_timeout=%d' % (self.timeout * 1000)
        try:
            conn = psycopg2.connect(host=self.host, port=self.port or 5432, dbname=self.dbname, user=self.db_user,
                                    password=self.password or None, sslmode=self.sslmode or 'prefer',
                                    connect_timeout=self.timeout, options=opts)
        except Exception as exc:  # noqa: BLE001
            raise UserError(_('Could not connect to %(name)s: %(err)s', name=self.name, err=str(exc).splitlines()[0]))
        try:
            conn.set_session(readonly=True, autocommit=False)
            cur = conn.cursor()
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = [[clean_cell(c) for c in r] for r in cur.fetchall()]
            return cols, rows
        except Exception as exc:  # noqa: BLE001
            raise UserError(_('The query failed on %(name)s: %(err)s', name=self.name, err=str(exc).splitlines()[0]))
        finally:
            conn.rollback()
            conn.close()

    def _run_mysql(self, sql):
        try:
            import pymysql
        except ImportError:
            raise UserError(_('MySQL connections need the Python package "pymysql" on the Odoo server. Install it with pip and try again.'))
        try:
            conn = pymysql.connect(host=self.host, port=self.port or 3306, user=self.db_user, password=self.password or '',
                                   database=self.dbname, connect_timeout=self.timeout, read_timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001
            raise UserError(_('Could not connect to %(name)s: %(err)s', name=self.name, err=str(exc)))
        try:
            cur = conn.cursor()
            cur.execute('SET SESSION TRANSACTION READ ONLY')
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            return cols, [[clean_cell(c) for c in r] for r in cur.fetchall()]
        except Exception as exc:  # noqa: BLE001
            raise UserError(_('The query failed on %(name)s: %(err)s', name=self.name, err=str(exc)))
        finally:
            conn.close()

    # ------------------------------------------------------------------ JSON API
    def _check_host(self, url):
        parsed = urlparse(url)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname:
            raise UserError(_('The API address must start with https://'))
        if parsed.scheme == 'http' and compat.get_param(self.env, 'ax_dashboard_pro.allow_private_hosts') != 'True':
            raise UserError(_('Plain http is only allowed when private hosts are enabled in the settings.'))
        if compat.get_param(self.env, 'ax_dashboard_pro.allow_private_hosts') == 'True':
            return
        try:
            infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
        except OSError:
            raise UserError(_('The host %s cannot be resolved.', parsed.hostname))
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise UserError(_('The host %s points to a private network address. Enable private hosts in the settings to allow it.', parsed.hostname))

    def _post_json(self, url, payload, timeout=10):
        """POST a JSON body (alert webhooks). Same host rules as JSON API items."""
        if HTTP_TRANSPORT is None:
            self._check_host(url)
        body = json.dumps(payload)
        headers = {'Content-Type': 'application/json'}
        try:
            if HTTP_TRANSPORT:
                status, _text = HTTP_TRANSPORT('POST', url, headers, timeout, body)
            else:
                resp = requests.post(url, data=body, headers=headers, timeout=timeout, allow_redirects=False)
                status = resp.status_code
        except requests.RequestException as exc:
            raise UserError(_('The webhook call failed: %s', exc))
        if status >= 300:
            raise UserError(_('The webhook answered with HTTP %s.', status))
        return status

    def _run_api(self, path, limit):
        base = (self.base_url or '').rstrip('/')
        url = base + '/' + (path or '').strip().lstrip('/')
        if HTTP_TRANSPORT is None:
            self._check_host(url)
        headers = {'Accept': 'application/json'}
        if self.auth_value:
            headers[self.auth_header or 'Authorization'] = self.auth_value
        try:
            if HTTP_TRANSPORT:
                status, text = HTTP_TRANSPORT('GET', url, headers, self.timeout)
            else:
                resp = requests.get(url, headers=headers, timeout=self.timeout, allow_redirects=False)
                status, text = resp.status_code, resp.text
        except requests.RequestException as exc:
            raise UserError(_('The API call failed: %s', exc))
        if status != 200:
            raise UserError(_('The API answered with HTTP %s.', status))
        try:
            data = json.loads(text)
        except ValueError:
            raise UserError(_('The API did not return JSON.'))
        if isinstance(data, dict) and 'rows' in data and 'columns' in data:
            cols, rows = list(data['columns']), [list(r) for r in data['rows']]
        else:
            if isinstance(data, dict):
                data = data.get('data') or data.get('results') or data.get('items') or []
            if not isinstance(data, list) or (data and not isinstance(data[0], dict)):
                raise UserError(_('The API must return a list of objects, or {"columns": [...], "rows": [[...]]}.'))
            cols = list(data[0].keys()) if data else []
            rows = [[row.get(c) for c in cols] for row in data]
        return cols, [[clean_cell(c) for c in r] for r in rows[:max(1, min(int(limit or 200), 2000))]]

    def action_test(self):
        self.ensure_one()
        try:
            if self.conn_type == 'api':
                cols, rows = self.run('', limit=1)
            else:
                cols, rows = self.run('SELECT 1 AS ok', limit=1)
            msg, kind = _('Connection works.'), 'success'
        except UserError as exc:
            msg, kind = exc.args[0], 'danger'
        self.sudo().last_test = '%s: %s' % (fields.Datetime.now(), msg)
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Connection test'), 'message': msg, 'type': kind, 'sticky': kind == 'danger'}}
