# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
import json
import re

from odoo import http, _
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request
from odoo.http.stream import content_disposition

from ..models import compat, safe


def _filters():
    raw = request.params.get('filters') or '{}'
    try:
        data = json.loads(raw)
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        return {}
    preset = data.get('preset')
    if preset and preset not in safe.PRESET_KEYS:
        data['preset'] = 'all'
    return data


def _safe_name(name):
    return re.sub(r'[^A-Za-z0-9._ -]+', '_', name or 'dashboard')[:80] or 'dashboard'


class AxDashboardController(http.Controller):

    @http.route('/ax_dashboard/item/<int:item_id>/<string:fmt>', type='http', auth='user')
    def export_item(self, item_id, fmt, **kw):
        if fmt not in ('csv', 'xlsx', 'pdf'):
            return request.not_found()
        try:
            item = request.env['ax.dashboard.item'].browse(item_id)
            compat.check_access(item, 'read')
            data = item.get_data(_filters(), {'level': int(request.params.get('level') or 0),
                                              'domain': json.loads(request.params.get('drill_domain') or '[]')})
        except (AccessError, MissingError, ValueError):
            return request.not_found()
        exporter = request.env['ax.dashboard.exporter']
        name = _safe_name(item.name)
        if fmt == 'csv':
            body, mime = exporter.to_csv(data), 'text/csv; charset=utf-8'
        elif fmt == 'xlsx':
            body, mime = exporter.to_xlsx([data], item.name), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        else:
            body, mime = exporter.to_pdf(item.name, [data], item.dashboard_id.name), 'application/pdf'
        item.dashboard_id._log('export', '%s: %s' % (fmt.upper(), item.name), item=item)
        return request.make_response(body, [('Content-Type', mime), ('Content-Disposition', content_disposition('%s.%s' % (name, fmt)))])

    @http.route('/ax_dashboard/dashboard/<int:dashboard_id>/<string:fmt>', type='http', auth='user')
    def export_dashboard(self, dashboard_id, fmt, **kw):
        if fmt not in ('json', 'xlsx', 'pdf'):
            return request.not_found()
        try:
            dash = request.env['ax.dashboard'].browse(dashboard_id)
            compat.check_access(dash, 'read')
            name = _safe_name(dash.name)
            if fmt == 'json':
                body, mime = dash.export_json().encode('utf-8'), 'application/json'
            else:
                datas = [i.get_data(_filters()) for i in dash.item_ids if i.item_type != 'todo']
                exporter = request.env['ax.dashboard.exporter']
                if fmt == 'xlsx':
                    body, mime = exporter.to_xlsx(datas, dash.name), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                else:
                    body, mime = exporter.to_pdf(dash.name, datas, _('Printed %s', request.env.user.name)), 'application/pdf'
                dash._log('export', fmt.upper())
        except (AccessError, MissingError):
            return request.not_found()
        return request.make_response(body, [('Content-Type', mime), ('Content-Disposition', content_disposition('%s.%s' % (name, fmt)))])

    @http.route('/ax_dashboard/template/<int:tpl_id>/download', type='http', auth='user')
    def download_template(self, tpl_id, **kw):
        try:
            tpl = request.env['ax.dashboard.template'].browse(tpl_id)
            compat.check_access(tpl, 'read')
            body = (tpl.data or '{}').encode('utf-8')
            name = _safe_name(tpl.name)
        except (AccessError, MissingError):
            return request.not_found()
        return request.make_response(body, [('Content-Type', 'application/json'), ('Content-Disposition', content_disposition(name + '.json'))])
