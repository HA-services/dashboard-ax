# -*- coding: utf-8 -*-
import io
import json
import zipfile
from datetime import timedelta
from unittest.mock import patch

import psycopg2

from odoo import fields, tools
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.ax_dashboard_pro.models import connection as conn_mod, safe, sqlrun
from odoo.addons.ax_dashboard_pro.models.compat import set_param
from .common import add_restriction, AxCommon


@tagged('post_install', '-at_install', 'ax_dashboard_pro')
class TestSql(AxCommon):

    GOOD = ["SELECT 1 AS a", "select name as label, id as value from res_company", "WITH x AS (SELECT 1 AS n) SELECT n FROM x;",
            "SELECT 'drop table x; --' AS text_literal"]
    BAD = ["DROP TABLE res_partner", "SELECT 1; DELETE FROM res_partner", "UPDATE res_partner SET name = 'x'", "SELECT 1 -- hidden",
           "SELECT 1 /* c */", "INSERT INTO res_partner (name) VALUES ('x')", "SELECT * FROM res_users", "SELECT value FROM ir_config_parameter",
           "SELECT * FROM information_schema.tables", "SELECT * FROM pg_catalog.pg_tables", "COPY res_partner TO '/tmp/x'",
           "WITH d AS (DELETE FROM res_partner RETURNING 1) SELECT * FROM d", "SELECT pg_read_file('/etc/passwd')", "", "   ",
           "SELECT * FROM res_users_apikeys", "SELECT E'\\'' ; DROP TABLE res_partner; SELECT 'x'", "SELECT $$a$$", "SELECT 'unbalanced", "CREATE TABLE x (a int)", "SELECT set_config('x', 'y', false); SELECT 1"]

    def test_guard_accepts_selects(self):
        for sql in self.GOOD:
            self.assertTrue(safe.check_readonly_sql(sql), sql)

    def test_guard_rejects_everything_else(self):
        for sql in self.BAD:
            with self.assertRaises(UserError, msg=sql):
                safe.check_readonly_sql(sql)

    def _allow(self):
        set_param(self.env, 'ax_dashboard_pro.allow_sql', 'True')

    def test_switched_off_by_default(self):
        set_param(self.env, 'ax_dashboard_pro.allow_sql', 'False')
        with self.assertRaises(UserError):
            self.env['ax.dashboard.sqlrun'].run_local('SELECT 1 AS a')

    def test_run_local_returns_rows(self):
        self._allow()
        cols, rows = self.env['ax.dashboard.sqlrun'].run_local('SELECT count(*) AS total FROM res_company')
        self.assertEqual(cols, ['total'])
        self.assertGreaterEqual(rows[0][0], 1)

    def test_row_cap_and_timeout(self):
        self._allow()
        cols, rows = self.env['ax.dashboard.sqlrun'].run_local('SELECT generate_series(1, 5000) AS n', limit=999999)
        self.assertEqual(len(rows), sqlrun.MAX_ROWS)
        with patch.object(sqlrun, 'TIMEOUT_MS', 300):
            with self.assertRaises(UserError):
                self.env['ax.dashboard.sqlrun'].run_local('SELECT pg_sleep(3) AS s')

    def test_database_itself_refuses_writes(self):
        self._allow()
        # the guard is bypassed on purpose: the READ ONLY transaction must still stop a write
        with patch.object(safe, '_FORBIDDEN', __import__('re').compile(r'(?!x)x')):
            with self.assertRaises(UserError):
                self.env['ax.dashboard.sqlrun'].run_local("SELECT (SELECT 1 FROM (SELECT nextval('res_partner_id_seq')) q)")

    def test_tokens_insert_only_dates_and_ints(self):
        sql = self.env['ax.dashboard.sqlrun'].fill_tokens('{{date_from}} {{date_to}} {{company_ids}} {{user_id}}',
                                                           {'preset': 'custom', 'date_from': "2026-01-01'; DROP", 'date_to': '2026-01-31'})
        self.assertNotIn('DROP', sql)

    def test_sql_items_render_as_list_chart_and_kpi(self):
        self._allow()
        Item = self.env['ax.dashboard.item']
        q = "SELECT name AS label, 3 AS value FROM res_company ORDER BY id"
        base = {'dashboard_id': self.dash.id, 'source_type': 'sql', 'sql_query': q}
        lst = Item.create(dict(base, name='l', item_type='list'))
        self.assertEqual(self.values(lst)['columns'][0]['name'], 'label')
        chart = Item.create(dict(base, name='c', item_type='chart', chart_type='bar'))
        res = self.values(chart)
        self.assertEqual(res['datasets'][0]['data'][0], 3.0)
        kpi = Item.create(dict(base, name='k', item_type='kpi', sql_query='SELECT 42 AS answer'))
        self.assertEqual(self.values(kpi)['value'], 42)

    def test_bad_sql_shows_error_in_the_item(self):
        self._allow()
        item = self.env['ax.dashboard.item'].create({'dashboard_id': self.dash.id, 'name': 'bad', 'item_type': 'list', 'source_type': 'sql', 'sql_query': 'SELECT 1; SELECT 2'})
        self.assertTrue(item.get_data({}).get('error'))


@tagged('post_install', '-at_install', 'ax_dashboard_pro')
class TestConnections(AxCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ext_db = 'ax_ext_test_%d' % (abs(hash(cls.env.cr.dbname)) % 100000)
        cls.ext_ok = False
        try:
            cfg = tools.config
            cls.pg = dict(host=cfg['db_host'] or None, port=cfg['db_port'] or None, user=cfg['db_user'] or None, password=cfg['db_password'] or None)
            admin = psycopg2.connect(dbname='postgres', **{k: v for k, v in cls.pg.items() if v})
            admin.autocommit = True
            admin.cursor().execute('DROP DATABASE IF EXISTS "%s"' % cls.ext_db)
            admin.cursor().execute('CREATE DATABASE "%s"' % cls.ext_db)
            admin.close()
            ext = psycopg2.connect(dbname=cls.ext_db, **{k: v for k, v in cls.pg.items() if v})
            cur = ext.cursor()
            cur.execute("CREATE TABLE sales (region text, total numeric); INSERT INTO sales VALUES ('North', 120.5), ('South', 80)")
            ext.commit()
            ext.close()
            cls.ext_ok = True
        except Exception:  # noqa: BLE001
            cls.ext_ok = False

    @classmethod
    def tearDownClass(cls):
        try:
            if cls.ext_ok:
                admin = psycopg2.connect(dbname='postgres', **{k: v for k, v in cls.pg.items() if v})
                admin.autocommit = True
                admin.cursor().execute('DROP DATABASE IF EXISTS "%s"' % cls.ext_db)
                admin.close()
        finally:
            super().tearDownClass()

    def _pg(self):
        if not self.ext_ok:
            self.skipTest('cannot create a second PostgreSQL database here')
        return self.env['ax.dashboard.connection'].create({
            'name': 'ext', 'conn_type': 'postgres', 'host': self.pg['host'] or '/var/run/postgresql', 'port': int(self.pg['port'] or 5432),
            'dbname': self.ext_db, 'db_user': self.pg['user'] or 'odoo', 'password': self.pg['password'] or '', 'sslmode': 'prefer'})

    def test_postgres_second_database(self):
        conn = self._pg()
        cols, rows = conn.run('SELECT region AS label, total AS value FROM sales ORDER BY 1')
        self.assertEqual(cols, ['label', 'value'])
        self.assertEqual(rows[0][0], 'North')
        self.assertAlmostEqual(float(rows[0][1]), 120.5)

    def test_postgres_is_read_only_and_guarded(self):
        conn = self._pg()
        for sql in ("DELETE FROM sales", "SELECT 1; DROP TABLE sales", "UPDATE sales SET total = 0"):
            with self.assertRaises(UserError):
                conn.run(sql)
        self.assertEqual(len(conn.run('SELECT * FROM sales')[1]), 2)
        # even if a write got through the text guard, the session itself is read only
        with patch.object(safe, '_FORBIDDEN', __import__('re').compile(r'(?!x)x')):
            with self.assertRaises(UserError):
                conn.run('SELECT 1 FROM (SELECT 1) q; ')
                conn._run_postgres('DELETE FROM sales')
        self.assertEqual(len(conn.run('SELECT * FROM sales')[1]), 2)

    def test_connection_failure_is_a_clean_error(self):
        conn = self.env['ax.dashboard.connection'].create({'name': 'bad', 'conn_type': 'postgres', 'host': '127.0.0.1', 'port': 1, 'dbname': 'x', 'db_user': 'x', 'timeout': 2})
        with self.assertRaises(UserError):
            conn.run('SELECT 1')
        res = conn.action_test()
        self.assertEqual(res['params']['type'], 'danger')

    def test_external_item(self):
        conn = self._pg()
        with self.assertRaises(UserError):     # off by default
            self.env['ax.dashboard.item'].create({'dashboard_id': self.dash.id, 'name': 'blocked', 'item_type': 'list', 'source_type': 'external',
                                                   'connection_id': conn.id, 'sql_query': 'SELECT 1 AS a'})
        set_param(self.env, 'ax_dashboard_pro.allow_sql', 'True')
        item = self.env['ax.dashboard.item'].create({'dashboard_id': self.dash.id, 'name': 'ext chart', 'item_type': 'chart', 'chart_type': 'bar',
                                                      'source_type': 'external', 'connection_id': conn.id, 'sql_query': 'SELECT region, total FROM sales ORDER BY 1'})
        res = self.values(item)
        self.assertEqual(res['labels'], ['North', 'South'])
        self.assertEqual(res['datasets'][0]['data'], [120.5, 80.0])

    def test_mysql_without_driver_explains_itself(self):
        conn = self.env['ax.dashboard.connection'].create({'name': 'my', 'conn_type': 'mysql', 'host': 'localhost', 'dbname': 'x', 'db_user': 'x'})
        try:
            import pymysql  # noqa: F401
        except ImportError:
            with self.assertRaises(UserError) as cm:
                conn.run('SELECT 1')
            self.assertIn('pymysql', str(cm.exception))

    def test_api_connection(self):
        conn = self.env['ax.dashboard.connection'].create({'name': 'api', 'conn_type': 'api', 'base_url': 'https://api.example.com/v1', 'auth_value': 'Bearer t0k'})
        seen = []

        def transport(method, url, headers, timeout):
            seen.append((url, headers))
            return 200, json.dumps({'data': [{'region': 'N', 'total': 5}, {'region': 'S', 'total': 7}]})
        with patch.object(conn_mod, 'HTTP_TRANSPORT', transport):
            cols, rows = conn.run('/sales')
            self.assertEqual(cols, ['region', 'total'])
            self.assertEqual(rows, [['N', 5], ['S', 7]])
            self.assertEqual(seen[0][0], 'https://api.example.com/v1/sales')
            self.assertEqual(seen[0][1]['Authorization'], 'Bearer t0k')
            item = self.env['ax.dashboard.item'].create({'dashboard_id': self.dash.id, 'name': 'api', 'item_type': 'chart', 'chart_type': 'bar',
                                                          'source_type': 'external', 'connection_id': conn.id, 'sql_query': '/sales'})
            self.assertEqual(self.values(item)['datasets'][0]['data'], [5.0, 7.0])
        for status, body in ((500, '{}'), (200, 'not json'), (200, '"text"')):
            with patch.object(conn_mod, 'HTTP_TRANSPORT', lambda *a, s=status, b=body: (s, b)):
                with self.assertRaises(UserError):
                    conn.run('/x')

    def test_api_blocks_private_networks(self):
        conn = self.env['ax.dashboard.connection'].create({'name': 'api', 'conn_type': 'api', 'base_url': 'https://localhost'})
        set_param(self.env, 'ax_dashboard_pro.allow_private_hosts', 'False')
        for url in ('https://localhost/x', 'https://127.0.0.1/x', 'http://example.com/x', 'ftp://example.com/x', 'https://169.254.169.254/latest', 'https://[::1]/x'):
            with self.assertRaises(UserError, msg=url):
                conn._check_host(url)

    def test_timeout_limits(self):
        with self.assertRaises(UserError):
            self.env['ax.dashboard.connection'].create({'name': 't', 'conn_type': 'api', 'base_url': 'https://x.example.com', 'timeout': 500})


@tagged('post_install', '-at_install', 'ax_dashboard_pro')
class TestExportsAndSchedules(AxCommon):

    def _datas(self):
        k = self.make_item(name='Rows', aggregate='count')
        c = self.make_item(name='By country', item_type='chart', chart_type='bar', groupby='country_id', aggregate='count')
        l = self.make_item(name='List', item_type='list', list_fields=['name', 'color'], list_order='name')
        return [i.get_data(self.ALL) for i in (k, c, l)]

    def test_csv(self):
        exp = self.env['ax.dashboard.exporter']
        data = self._datas()
        text = exp.to_csv(data[1]).decode() if isinstance(exp.to_csv(data[1]), bytes) else exp.to_csv(data[1])
        self.assertIn('Belgium', text)
        self.assertIn('France', text)

    def test_csv_formula_injection_is_neutralised(self):
        exp = self.env['ax.dashboard.exporter']
        self.env['res.partner'].create({'name': 'AXT inj', 'function': '=HYPERLINK("http://evil")', 'color': 1})
        item = self.make_item(item_type='list', list_fields=['function'], list_order='function')
        out = exp.to_csv(item.get_data(self.ALL))
        text = out.decode() if isinstance(out, bytes) else out
        self.assertNotIn('\n=HYPERLINK', text)
        self.assertNotIn(',=HYPERLINK', text)
        self.assertIn("'=HYPERLINK", text)

    def test_xlsx_has_sheets_and_native_charts(self):
        exp = self.env['ax.dashboard.exporter']
        blob = exp.to_xlsx(self._datas(), 'Test dashboard')
        z = zipfile.ZipFile(io.BytesIO(blob))
        names = z.namelist()
        self.assertIn('xl/workbook.xml', names)
        self.assertTrue(any(n.startswith('xl/charts/') for n in names), 'charts are native Excel charts')
        self.assertTrue(len([n for n in names if n.startswith('xl/worksheets/sheet')]) >= 3)

    def test_pdf(self):
        exp = self.env['ax.dashboard.exporter']
        blob = exp.to_pdf('Test dashboard', self._datas(), 'subtitle')
        self.assertTrue(blob.startswith(b'%PDF'))
        self.assertGreater(len(blob), 1500)

    def test_html_summary(self):
        exp = self.env['ax.dashboard.exporter']
        html = exp.dashboard_html(self.dash, self._datas(), 'sub')
        self.assertIn('Test dashboard', html)
        self.assertIn('Belgium', html)

    def test_next_run_calculation(self):
        Sched = self.env['ax.dashboard.schedule']
        base = fields.Datetime.to_datetime('2026-11-21 10:00:00')      # a Saturday
        s = Sched.create({'name': 'd', 'dashboard_id': self.dash.id, 'frequency': 'daily', 'hour': 8})
        self.assertEqual(s._next_after(base), fields.Datetime.to_datetime('2026-11-22 08:00:00'))
        s.hour = 12
        self.assertEqual(s._next_after(base), fields.Datetime.to_datetime('2026-11-21 12:00:00'))
        s.write({'frequency': 'weekly', 'weekday': '0', 'hour': 9})
        self.assertEqual(s._next_after(base), fields.Datetime.to_datetime('2026-11-23 09:00:00'))
        s.write({'frequency': 'monthly', 'month_day': 5, 'hour': 7})
        self.assertEqual(s._next_after(base), fields.Datetime.to_datetime('2026-12-05 07:00:00'))
        s.month_day = 25
        self.assertEqual(s._next_after(base), fields.Datetime.to_datetime('2026-11-25 07:00:00'))
        with self.assertRaises(Exception):
            s.hour = 24
        s2 = Sched.create({'name': 'dec', 'dashboard_id': self.dash.id, 'frequency': 'monthly', 'month_day': 1, 'hour': 6})
        self.assertEqual(s2._next_after(fields.Datetime.to_datetime('2026-12-15 10:00:00')), fields.Datetime.to_datetime('2027-01-01 06:00:00'))

    def test_send_report(self):
        self.make_item(name='Rows', aggregate='count')
        user = self.make_user('ax_reader', ['ax_dashboard_pro.group_ax_dashboard_user'])
        s = self.env['ax.dashboard.schedule'].create({'name': 'Weekly', 'dashboard_id': self.dash.id, 'user_ids': [(6, 0, [user.id])],
                                                       'extra_emails': 'boss@example.com, bad address', 'date_preset': 'all'})
        mail = s._send()
        self.assertIn('ax_reader@example.com', mail.email_to)
        self.assertIn('boss@example.com', mail.email_to)
        self.assertNotIn('bad address', mail.email_to)
        self.assertEqual(sorted(a.name.rsplit('.', 1)[1] for a in mail.attachment_ids), ['pdf', 'xlsx'])
        self.assertTrue(s.last_run)
        self.assertIn('Test dashboard', mail.subject)

    def test_send_requires_recipients(self):
        s = self.env['ax.dashboard.schedule'].create({'name': 'none', 'dashboard_id': self.dash.id})
        with self.assertRaises(UserError):
            s._send()

    def test_cron_sends_due_reports_only(self):
        due = self.env['ax.dashboard.schedule'].create({'name': 'due', 'dashboard_id': self.dash.id, 'extra_emails': 'a@example.com', 'date_preset': 'all'})
        later = self.env['ax.dashboard.schedule'].create({'name': 'later', 'dashboard_id': self.dash.id, 'extra_emails': 'b@example.com', 'date_preset': 'all'})
        due.next_run = fields.Datetime.now() - timedelta(minutes=5)
        later.next_run = fields.Datetime.now() + timedelta(days=3)
        before = self.env['mail.mail'].search_count([('email_to', 'in', ['a@example.com', 'b@example.com'])])
        self.env['ax.dashboard.schedule']._cron_send_due()
        self.assertEqual(self.env['mail.mail'].search_count([('email_to', 'in', ['a@example.com', 'b@example.com'])]) - before, 1)
        self.assertTrue(due.last_run)
        self.assertFalse(later.last_run)

    def test_report_runs_with_the_owners_rights(self):
        owner = self.make_user('ax_sched_owner', ['ax_dashboard_pro.group_ax_dashboard_builder'])
        d = self.env['ax.dashboard'].create({'name': 'Owner dash', 'owner_id': owner.id})
        self.make_item(dash=d, name='Rows', aggregate='count')
        add_restriction(self.env, 'only BE', 'base.model_res_partner', "[('country_id.code', '=', 'BE')]")
        s = self.env['ax.dashboard.schedule'].create({'name': 'o', 'dashboard_id': d.id, 'extra_emails': 'x@example.com', 'date_preset': 'all', 'attach_pdf': False, 'attach_xlsx': False})
        mail = s._send()
        self.assertIn('>2<', mail.body_html.replace(' ', '').replace('\n', ''))
