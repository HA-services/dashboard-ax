# -*- coding: utf-8 -*-
from datetime import date

from odoo.tests.common import TransactionCase

MODEL = 'res.partner'
PREFIX = 'AXT '


def group_field(env):
    return 'group_ids' if 'group_ids' in env['res.users']._fields else 'groups_id'


class AxCommon(TransactionCase):
    """Deterministic data on res.partner: six rows with known colors, countries and dates."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        be, fr, de = (env.ref('base.be'), env.ref('base.fr'), env.ref('base.de'))
        rows = [
            ('A1', be, 10, 'sales', date(2026, 1, 15)), ('A2', be, 20, 'buyer', date(2026, 1, 20)),
            ('A3', fr, 30, 'sales', date(2026, 2, 10)), ('A4', fr, 40, 'sales', date(2026, 2, 11)),
            ('A5', de, 50, 'sales', date(2025, 1, 15)), ('A6', de, 5, 'buyer', date(2025, 12, 31)),
        ]
        cls.partners = env[MODEL]
        for name, country, color, func, when in rows:
            p = env[MODEL].create({'name': PREFIX + name, 'country_id': country.id, 'color': color, 'function': func})
            env.cr.execute('UPDATE res_partner SET create_date = %s WHERE id = %s', (when.isoformat() + ' 12:00:00', p.id))
            cls.partners |= p
        env[MODEL].invalidate_model()
        cls.dash = env['ax.dashboard'].create({'name': 'Test dashboard', 'owner_id': env.ref('base.user_admin').id})
        cls.JAN = {'preset': 'custom', 'date_from': '2026-01-01', 'date_to': '2026-01-31'}
        cls.ALL = {'preset': 'all'}

    def make_item(self, dash=None, **kw):
        d = {'name': 'Item', 'item_type': 'kpi', 'model': MODEL, 'aggregate': 'count', 'measure': None,
             'date_field': 'create_date', 'domain': "[('name', '=like', '%s%%')]" % PREFIX}
        d.update(kw)
        dash = dash or self.dash
        vals, warn = self.env['ax.dashboard.item'].values_from_dict(d, dash)
        self.assertTrue(vals, warn)
        return self.env['ax.dashboard.item'].create(vals)

    def make_user(self, login, xmlids):
        gf = group_field(self.env)
        groups = [self.env.ref(x).id for x in ['base.group_user'] + xmlids]
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'email': login + '@example.com', gf: [(6, 0, groups)]})

    def values(self, item, filters=None, drill=None):
        res = item.get_data(filters or self.ALL, drill)
        self.assertFalse(res.get('error'), res.get('error'))
        return res


def add_restriction(env, name, model_xmlid, domain):
    """A rule that hides records from everybody (a global record rule; an unrestricted-group access on Odoo 20)."""
    model = env.ref(model_xmlid)
    if 'ir.access' in env:
        return env['ir.access'].create({'name': name, 'model_id': model.id, 'operation': 'crud', 'domain': domain})
    return env['ir.rule'].create({'name': name, 'model_id': model.id, 'domain_force': domain})
