# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
import datetime
import decimal

from odoo import _, api, models, sql_db
from odoo.exceptions import UserError

from . import compat, safe

MAX_ROWS = 2000
TIMEOUT_MS = 10000


def clean_cell(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    if isinstance(v, (bytes, memoryview)):
        return '<binary>'
    return v


class AxDashboardSqlRun(models.AbstractModel):
    _name = 'ax.dashboard.sqlrun'
    _description = 'Read-only SQL runner'

    @api.model
    def fill_tokens(self, sql, filters):
        """Replace {{date_from}}, {{date_to}}, {{company_ids}} and {{user_id}}. Only dates and ints are inserted."""
        s, e, _ps, _pe = safe.date_range((filters or {}).get('preset'), None, (filters or {}).get('date_from'), (filters or {}).get('date_to'))
        sql = sql.replace('{{date_from}}', ("'%s'::date" % s.isoformat()) if s else 'NULL::date')
        sql = sql.replace('{{date_to}}', ("'%s'::date" % e.isoformat()) if e else 'NULL::date')
        sql = sql.replace('{{company_ids}}', ','.join(str(int(c)) for c in self.env.companies.ids) or '0')
        sql = sql.replace('{{user_id}}', str(int(self.env.uid)))
        return sql

    @api.model
    def run_local(self, sql, filters=None, limit=200):
        """Run a SELECT in the Odoo database inside a READ ONLY transaction with a timeout.

        Safeguards: single statement, SELECT/WITH only, no write or system keywords, blocked sensitive tables,
        the database itself refuses writes (READ ONLY transaction), a statement timeout and a row cap."""
        if compat.get_param(self.env, 'ax_dashboard_pro.allow_sql') != 'True':
            raise UserError(_('Custom SQL items are switched off in the dashboard settings.'))
        text = safe.check_readonly_sql(self.fill_tokens(sql or '', filters))
        limit = max(1, min(int(limit or 200), MAX_ROWS))
        wrapped = 'SELECT * FROM (%s) AS ax_dashboard_q LIMIT %d' % (text, limit)
        # A dedicated connection: the query can never touch the transaction of the request.
        ro_cursor = sql_db.db_connect(self.env.cr.dbname).cursor()
        try:
            ro_cursor.execute('SET TRANSACTION READ ONLY')
            ro_cursor.execute('SET LOCAL statement_timeout = %d' % TIMEOUT_MS)
            ro_cursor.execute(wrapped)
            cols = [d[0] for d in ro_cursor.description]
            rows = [[clean_cell(c) for c in row] for row in ro_cursor.fetchall()]
        except Exception as exc:  # noqa: BLE001
            raise UserError(_('The SQL query failed: %s', str(exc).splitlines()[0] if str(exc) else exc))
        finally:
            ro_cursor.rollback()
            ro_cursor.close()
        self.env['ax.dashboard.log'].sudo().create({'action': 'sql', 'user_id': self.env.uid, 'detail': text[:200]})
        return cols, rows
