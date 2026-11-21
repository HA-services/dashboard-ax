# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
"""Small, dependency free helpers: date ranges, number formats, the formula evaluator and the SQL guard."""
import ast
import calendar
import operator
import re
from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _
from odoo.exceptions import UserError

PRESETS = [
    ('all', 'All time'), ('today', 'Today'), ('yesterday', 'Yesterday'),
    ('this_week', 'This week'), ('last_week', 'Last week'),
    ('this_month', 'This month'), ('last_month', 'Last month'),
    ('this_quarter', 'This quarter'), ('last_quarter', 'Last quarter'),
    ('this_year', 'This year'), ('last_year', 'Last year'),
    ('last_7', 'Last 7 days'), ('last_30', 'Last 30 days'), ('last_90', 'Last 90 days'),
    ('last_365', 'Last 12 months'), ('ytd', 'Year to date'), ('custom', 'Custom range'),
]
PRESET_KEYS = [p[0] for p in PRESETS]


def _quarter_start(d):
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def date_range(preset, today=None, date_from=None, date_to=None):
    """Return (start, end, prev_start, prev_end) as dates. ``None`` for an open range.

    The previous period has the same length as the current one (or the same calendar unit),
    right before it. ``prev_year_*`` is the same range one year earlier."""
    today = today or date.today()
    if preset in (None, False, '', 'all'):
        return None, None, None, None
    if preset == 'today':
        s = e = today
    elif preset == 'yesterday':
        s = e = today - timedelta(days=1)
    elif preset == 'this_week':
        s = today - timedelta(days=today.weekday())
        e = s + timedelta(days=6)
    elif preset == 'last_week':
        s = today - timedelta(days=today.weekday() + 7)
        e = s + timedelta(days=6)
    elif preset == 'this_month':
        s = today.replace(day=1)
        e = s + relativedelta(months=1, days=-1)
    elif preset == 'last_month':
        s = today.replace(day=1) - relativedelta(months=1)
        e = s + relativedelta(months=1, days=-1)
    elif preset == 'this_quarter':
        s = _quarter_start(today)
        e = s + relativedelta(months=3, days=-1)
    elif preset == 'last_quarter':
        s = _quarter_start(today) - relativedelta(months=3)
        e = s + relativedelta(months=3, days=-1)
    elif preset == 'this_year':
        s = date(today.year, 1, 1)
        e = date(today.year, 12, 31)
    elif preset == 'last_year':
        s = date(today.year - 1, 1, 1)
        e = date(today.year - 1, 12, 31)
    elif preset == 'ytd':
        s = date(today.year, 1, 1)
        e = today
    elif preset in ('last_7', 'last_30', 'last_90', 'last_365'):
        n = {'last_7': 7, 'last_30': 30, 'last_90': 90, 'last_365': 365}[preset]
        e = today
        s = today - timedelta(days=n - 1)
    elif preset == 'custom':
        s = _to_date(date_from)
        e = _to_date(date_to)
        if not s and not e:
            return None, None, None, None
    else:
        raise UserError(_('Unknown date filter: %s', preset))
    if s and e:
        if preset in ('this_month', 'last_month'):
            ps = s - relativedelta(months=1)
            pe = ps + relativedelta(months=1, days=-1)
        elif preset in ('this_quarter', 'last_quarter'):
            ps = s - relativedelta(months=3)
            pe = ps + relativedelta(months=3, days=-1)
        elif preset in ('this_year', 'last_year', 'ytd'):
            ps = s - relativedelta(years=1)
            pe = e - relativedelta(years=1) if preset == 'ytd' else ps + relativedelta(years=1, days=-1)
        else:
            span = (e - s).days + 1
            pe = s - timedelta(days=1)
            ps = pe - timedelta(days=span - 1)
    else:
        ps = pe = None
    return s, e, ps, pe


def _to_date(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], '%Y-%m-%d').date()


def shift_year(s, e):
    if not s or not e:
        return None, None
    return s - relativedelta(years=1), e - relativedelta(years=1)


def bucket_end(start, interval):
    """First day after a bucket that starts at ``start``."""
    if interval == 'day':
        return start + timedelta(days=1)
    if interval == 'week':
        return start + timedelta(days=7)
    if interval == 'month':
        return start + relativedelta(months=1)
    if interval == 'quarter':
        return start + relativedelta(months=3)
    return start + relativedelta(years=1)


def bucket_label(start, interval):
    if interval == 'day':
        return start.strftime('%d %b %Y')
    if interval == 'week':
        return start.strftime('W%V %Y')
    if interval == 'month':
        return start.strftime('%b %Y')
    if interval == 'quarter':
        return 'Q%d %d' % ((start.month - 1) // 3 + 1, start.year)
    return str(start.year)


# --------------------------------------------------------------------------- formulas
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}
CODE_RE = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)\}')


def formula_codes(expr):
    return CODE_RE.findall(expr or '')


def eval_formula(expr, values):
    """Evaluate ``{code_a} / {code_b} * 100`` with numbers only. Division by zero gives 0."""
    if not expr:
        raise UserError(_('The formula is empty.'))
    text = CODE_RE.sub(lambda m: 'v_%s' % m.group(1), expr)
    try:
        tree = ast.parse(text.strip(), mode='eval')
    except SyntaxError:
        raise UserError(_('The formula is not valid: %s', expr))

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id.startswith('v_'):
            code = node.id[2:]
            if code not in values:
                raise UserError(_('The formula refers to an unknown item code: %s', code))
            return float(values[code] or 0.0)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, (ast.Div, ast.Mod)) and right == 0:
                return 0.0
            if isinstance(node.op, ast.Pow) and (abs(right) > 8 or abs(left) > 1e9):
                raise UserError(_('The formula uses a power that is too large.'))
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise UserError(_('The formula may only contain numbers, item codes in braces and + - * / %% ** ( ).'))
    return ev(tree)


# --------------------------------------------------------------------------- SQL guard
_FORBIDDEN = re.compile(
    r'\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|call|do|execute|prepare|'
    r'vacuum|analyze|lock|listen|notify|set|reset|show|begin|commit|rollback|savepoint|'
    r'pg_sleep|pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|pg_terminate_backend|pg_cancel_backend|'
    r'lo_import|lo_export|lo_get|lo_put|dblink|set_config|current_setting|pg_reload_conf|pg_file_write|'
    r'nextval|setval|into)\b', re.I)
BLOCKED_TABLES = (
    'res_users', 'res_users_apikeys', 'res_users_apikeys_description', 'res_users_log', 'res_users_settings',
    'ir_config_parameter', 'auth_oauth_provider', 'auth_totp_device', 'res_device', 'res_device_log',
    'ir_attachment', 'ax_dashboard_connection', 'res_partner_bank', 'pg_shadow', 'pg_authid', 'pg_user',
    'pg_roles', 'pg_settings', 'pg_file_settings', 'pg_hba_file_rules',
)


def check_readonly_sql(sql):
    """Raise UserError unless ``sql`` is a single SELECT/WITH statement without write keywords."""
    if not sql or not sql.strip():
        raise UserError(_('The SQL query is empty.'))
    text = sql.strip()
    if text.endswith(';'):
        text = text[:-1].strip()
    if '\\' in text or '$' in text:
        raise UserError(_('Backslashes and dollar quoting are not allowed in dashboard queries.'))
    low = re.sub(r"'(?:[^']|'')*'", ' _text_ ', text)  # drop string literals before looking for keywords
    if "'" in low:
        raise UserError(_('The SQL query has an unbalanced quote.'))
    if ';' in low:
        raise UserError(_('Only a single SQL statement is allowed.'))
    if '--' in low or '/*' in low or '*/' in low:
        raise UserError(_('SQL comments are not allowed in dashboard queries.'))
    if not re.match(r'^(select|with)\b', low, re.I):
        raise UserError(_('Only SELECT queries are allowed.'))
    bad = _FORBIDDEN.search(low)
    if bad:
        raise UserError(_('The keyword "%s" is not allowed in dashboard queries.', bad.group(1)))
    for table in BLOCKED_TABLES:
        if re.search(r'\b%s\b' % re.escape(table), low, re.I):
            raise UserError(_('The table "%s" cannot be used in dashboard queries.', table))
    if re.search(r'\b(information_schema|pg_catalog)\b', low, re.I):
        raise UserError(_('System catalogs cannot be used in dashboard queries.'))
    return text


def humanize(value, decimals=1):
    """1234567 -> 1.2M"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    for limit, suffix in ((1e12, 'T'), (1e9, 'B'), (1e6, 'M'), (1e3, 'K')):
        if abs(v) >= limit:
            return ('%%.%df%%s' % decimals) % (v / limit, suffix)
    return ('%%.%df' % decimals) % v if v != int(v) else str(int(v))
