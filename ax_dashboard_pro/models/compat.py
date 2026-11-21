# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
"""Everything that differs between Odoo versions lives here."""
from datetime import date, datetime

from odoo import release
from odoo.tools import date_utils

from . import safe

VER = release.version_info[0]
DATE_TYPES = ('date', 'datetime')


def get_param(env, key, default=''):
    """Read a system parameter (get_str on Odoo 20, get_param before)."""
    icp = env['ir.config_parameter'].sudo()
    if hasattr(icp, 'get_str'):
        return icp.get_str(key, default)
    return icp.get_param(key, default)


def set_param(env, key, value):
    icp = env['ir.config_parameter'].sudo()
    if hasattr(icp, 'set_str'):
        return icp.set_str(key, value)
    return icp.set_param(key, value)


def check_access(records, operation):
    """Raise AccessError unless the user may do ``operation`` on ``records`` (rights and record rules)."""
    if hasattr(records, 'check_access'):
        return records.check_access(operation)
    records.check_access_rights(operation)
    records.check_access_rule(operation)


def binary_bytes(value):
    """The bytes of a Binary field value (a BinaryValue on Odoo 20, base64 text or bytes before)."""
    if hasattr(value, 'content'):
        return value.content
    import base64
    return base64.b64decode(value)


def user_group_ids(user):
    return user.all_group_ids if 'all_group_ids' in user._fields else user.groups_id


def user_has_group(user, xmlid):
    return user.has_group(xmlid)


def _label_of(raw):
    if isinstance(raw, (tuple, list)) and len(raw) == 2:
        return raw[1]
    if raw is False or raw is None:
        return None
    return raw


def read_groups(model, domain, groupbys, measure, agg, limit=0):
    """Group ``model`` and aggregate one measure.

    ``groupbys`` is a list of specs such as ``['partner_id']`` or ``['date_order:month']``.
    ``measure`` is a field name or ``None`` for a plain count, ``agg`` one of sum/avg/min/max/count/count_distinct.

    Returns a list of dicts: ``keys`` (raw values, one per group by), ``labels``, ``domain``,
    ``value``, ``count``. Rows are in database order, the caller sorts them. Works on Odoo 16 to 20."""
    use_count = not measure or agg == 'count'
    rows = []
    if VER >= 19:
        aggs = ['__count'] if use_count else ['%s:%s' % (measure, agg), '__count']
        res = model.formatted_read_group(domain, groupby=list(groupbys), aggregates=aggs, limit=limit or None)
        key_agg = aggs[0]
        for r in res:
            rows.append({
                'keys': [r.get(g) for g in groupbys],
                'domain': list(r.get('__extra_domain') or []),
                'value': r.get(key_agg) or 0,
                'count': r.get('__count') or 0,
            })
    else:
        fields_spec = [] if use_count else ['%s:%s' % (measure, agg)]
        res = model.read_group(domain, fields_spec or ['id:count'], list(groupbys), lazy=False, limit=limit or None)
        for r in res:
            if use_count:
                value = r.get('__count') or 0
            else:
                value = r.get(measure)
                if value is None:
                    value = r.get('%s_%s' % (measure, agg))
            rows.append({
                'keys': [r.get(g) for g in groupbys],
                'ranges': [((r.get('__range') or {}).get(g) or {}).get('from') for g in groupbys],
                'domain': list(r.get('__domain') or []),
                'value': value or 0,
                'count': r.get('__count') or 0,
            })
    for r in rows:
        r.setdefault('ranges', [None] * len(groupbys))
        r['labels'] = [_label_of(k) for k in r['keys']]
        r['ids'] = [k[0] if isinstance(k, (tuple, list)) and len(k) == 2 and isinstance(k[0], int) else None
                    for k in r['keys']]
    return rows


def aggregate_one(model, domain, measure, agg):
    """A single number for the whole domain."""
    if not measure or agg == 'count':
        return model.search_count(domain)
    rows = read_groups(model, domain, [], measure, agg)
    if not rows:
        return 0
    return rows[0]['value'] or 0


def parse_bucket(label, interval):
    """Return the first day of a date bucket from a group label or a date string, or None."""
    if isinstance(label, (tuple, list)) and label:     # Odoo 19 and later: (value, display label)
        label = label[0]
    if isinstance(label, datetime):
        return label.date()
    if isinstance(label, date):
        return label
    if isinstance(label, str):
        s = label[:10]
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            return None
    return None
