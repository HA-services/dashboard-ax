# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
import json
import logging
import re

import requests

from odoo import _, api, models
from odoo.exceptions import UserError

from . import compat, safe

_logger = logging.getLogger(__name__)
# Tests replace this with a function (method, url, headers, body, timeout) -> (status, text)
AI_TRANSPORT = None

SYSTEM = """You design Odoo dashboards. Answer with ONE JSON object and nothing else.
Schema: {"name": str, "items": [ {"name": str, "item_type": "kpi"|"chart"|"list",
 "model": technical model name, "aggregate": "count"|"sum"|"avg"|"min"|"max",
 "measure": numeric field name (not needed for count), "groupby": field name (charts only),
 "date_field": date field name, "date_interval": "day"|"week"|"month"|"quarter"|"year",
 "chart_type": "bar"|"hbar"|"stacked"|"line"|"area"|"pie"|"doughnut"|"polar",
 "domain": Odoo domain as a string like "[('state','=','sale')]", "limit": int,
 "sort_by": "value"|"label", "sort_dir": "asc"|"desc", "number_format": "auto"|"integer"|"decimal"|"monetary"|"percent"|"compact",
 "list_fields": [field names] (lists only) } ]}
Use ONLY the models and fields listed in the catalog. Prefer 4 to 8 items: a few KPIs first, then charts, then one list."""

SUMMARY_SYSTEM = ("You are a careful business analyst. Summarise the data in 3 to 5 short sentences for a manager: the main takeaway, "
                  "the biggest and smallest values, and one thing worth checking. Use only the numbers provided. Do not invent causes.")


class AxDashboardAI(models.AbstractModel):
    _name = 'ax.dashboard.ai'
    _description = 'AI assistant for dashboards'

    # ------------------------------------------------------------------ provider
    @api.model
    def _config(self):
        key = compat.get_param(self.env, 'ax_dashboard_pro.ai_api_key')
        if not key:
            raise UserError(_('The AI assistant is not configured. A Dashboard Manager can add a provider and API key in Settings.'))
        provider = compat.get_param(self.env, 'ax_dashboard_pro.ai_provider') or 'openai'
        base = (compat.get_param(self.env, 'ax_dashboard_pro.ai_base_url') or '').rstrip('/')
        if not base:
            base = 'https://api.anthropic.com' if provider == 'anthropic' else 'https://api.openai.com/v1'
        model = compat.get_param(self.env, 'ax_dashboard_pro.ai_model')
        if not model:
            raise UserError(_('Set the AI model name in the dashboard settings.'))
        return provider, base, key, model

    @api.model
    def _chat(self, system, user, max_tokens=2000):
        provider, base, key, model = self._config()
        if provider == 'anthropic':
            url = base + '/v1/messages'
            headers = {'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
            body = {'model': model, 'max_tokens': max_tokens, 'system': system, 'messages': [{'role': 'user', 'content': user}]}
        else:
            url = base + '/chat/completions'
            headers = {'Authorization': 'Bearer ' + key, 'content-type': 'application/json'}
            body = {'model': model, 'temperature': 0.2, 'max_tokens': max_tokens,
                    'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
        payload = json.dumps(body)
        try:
            if AI_TRANSPORT:
                status, text = AI_TRANSPORT('POST', url, headers, payload, 90)
            else:
                resp = requests.post(url, headers=headers, data=payload, timeout=90)
                status, text = resp.status_code, resp.text
        except requests.RequestException as exc:
            raise UserError(_('The AI provider could not be reached: %s', exc))
        if status != 200:
            raise UserError(_('The AI provider answered with HTTP %(s)s: %(t)s', s=status, t=(text or '')[:200]))
        try:
            data = json.loads(text)
            if provider == 'anthropic':
                return ''.join(p.get('text', '') for p in data.get('content', []) if p.get('type') == 'text')
            return data['choices'][0]['message']['content']
        except (ValueError, KeyError, IndexError, TypeError):
            raise UserError(_('The AI provider returned an answer that could not be read.'))

    @staticmethod
    def _json_from(text):
        a, b = (text or '').find('{'), (text or '').rfind('}')
        if a < 0 or b <= a:
            raise UserError(_('The AI answer did not contain a dashboard definition. Try a more specific request.'))
        try:
            return json.loads(text[a:b + 1])
        except ValueError:
            raise UserError(_('The AI answer was not valid JSON. Try again.'))

    # ------------------------------------------------------------------ catalog
    @api.model
    def _catalog(self, prompt, max_models=8, max_fields=22):
        """The models and fields the AI may use: only those the current user can read."""
        words = set(re.findall(r'[a-z]{3,}', (prompt or '').lower()))
        Model = self.env['ir.model'].sudo()   # the list of models is metadata; access to the data is checked per user below
        cands = []
        for m in Model.search([('transient', '=', False)]):
            name = m.model
            if name.startswith(('ir.', 'base.', 'bus.', 'ax.dashboard', 'res.config', 'mail.', 'web', 'report.', 'auth.')):
                continue
            try:
                compat.check_access(self.env[name], 'read')
            except Exception:  # noqa: BLE001
                continue
            text = ('%s %s' % (name, m.name)).lower()
            score = sum(1 for w in words if w in text or (w.endswith('s') and w[:-1] in text))
            if score:
                cands.append((-score, name, m))
        cands.sort(key=lambda x: (x[0], x[1]))
        chosen = [c[2] for c in cands[:max_models]]
        if not chosen:
            for name in ('sale.order', 'account.move', 'res.partner'):
                if name in self.env:
                    chosen.append(Model._get(name))
        lines = []
        for m in chosen:
            Mod = self.env[m.model]
            flds = []
            for fname, fld in Mod._fields.items():
                if not fld.store or fname.startswith(('message_', 'activity_', 'website_')) or fld.type in ('binary', 'html', 'one2many', 'many2many', 'properties', 'json'):
                    continue
                flds.append('%s:%s' % (fname, fld.type))
            lines.append('%s (%s): %s' % (m.model, m.name, ', '.join(flds[:max_fields * 2][:max_fields])))
        return '\n'.join(lines)

    # ------------------------------------------------------------------ generation
    @api.model
    def _normalise_item(self, spec):
        d = dict(spec)
        d.setdefault('item_type', 'kpi')
        d['source_type'] = 'model'
        if d['item_type'] not in ('kpi', 'chart', 'list'):
            d['item_type'] = 'kpi'
        d['aggregate'] = d.get('aggregate') if d.get('aggregate') in ('count', 'sum', 'avg', 'min', 'max', 'count_distinct') else ('count' if not d.get('measure') else 'sum')
        if not d.get('measure'):
            d['aggregate'] = 'count'
        d['domain'] = d.get('domain') or '[]'
        d['limit'] = int(d.get('limit') or 10)
        return {k: v for k, v in d.items() if k in self.env['ax.dashboard.item']._EXPORT or k in ('model', 'measure', 'groupby', 'groupby2', 'date_field', 'list_fields')}

    @api.model
    def _build_items(self, dashboard, specs):
        """Create the items. Each is validated by computing it once; invalid ones are removed. Returns warnings."""
        warnings = []
        Item = self.env['ax.dashboard.item']
        for spec in specs[:12]:
            if not isinstance(spec, dict):
                continue
            d = self._normalise_item(spec)
            vals, warn = Item.values_from_dict(d, dashboard)
            warnings += warn
            if not vals:
                continue
            try:
                with self.env.cr.savepoint():
                    item = Item.with_context(ax_skip_version=True).create(vals)
                    probe = item.get_data({'preset': 'all'})
                    if probe.get('error'):
                        raise UserError(probe['error'])
            except Exception as exc:  # noqa: BLE001
                warnings.append(_('"%(name)s" was skipped: %(err)s', name=d.get('name'), err=exc.args[0] if exc.args else exc))
        return warnings

    @api.model
    def generate_dashboard(self, prompt):
        prompt = (prompt or '').strip()
        if len(prompt) < 5:
            raise UserError(_('Describe the dashboard you need in a sentence.'))
        catalog = self._catalog(prompt)
        answer = self._chat(SYSTEM, 'Catalog:\n%s\n\nRequest: %s' % (catalog, prompt[:1500]))
        spec = self._json_from(answer)
        items = spec.get('items')
        if not isinstance(items, list) or not items:
            raise UserError(_('The AI did not propose any items. Try a more specific request.'))
        dash = self.env['ax.dashboard'].with_context(ax_skip_version=True).create({'name': str(spec.get('name') or prompt[:60])[:120]})
        warnings = self._build_items(dash, items)
        if not dash.item_ids:
            dash.unlink()
            raise UserError(_('None of the proposed items could be built: %s', '; '.join(str(w) for w in warnings[:3])))
        dash._snapshot_version(_('Generated with AI'))
        dash._log('ai', _('Generated: %s', prompt[:100]))
        return dash, warnings

    @api.model
    def generate_item(self, dashboard, prompt):
        dashboard._check_can_edit()
        catalog = self._catalog(prompt)
        answer = self._chat(SYSTEM, 'Catalog:\n%s\n\nRequest (one item only): %s' % (catalog, (prompt or '')[:800]))
        spec = self._json_from(answer)
        items = spec.get('items') or ([spec] if spec.get('model') else [])
        before = dashboard.item_ids
        warnings = self._build_items(dashboard, items[:1])
        new = dashboard.item_ids - before
        dashboard._snapshot_version(_('Item generated with AI'))
        dashboard._log('ai', _('Item generated: %s', (prompt or '')[:100]))
        if not new:
            raise UserError(_('The item could not be built: %s', '; '.join(str(w) for w in warnings[:3])))
        return new, warnings

    @api.model
    def summarize_item(self, item, filters=None):
        data = item.get_data(filters or {})
        if data.get('error'):
            raise UserError(data['error'])
        compact = {'name': data['name'], 'type': data['item_type']}
        if data['item_type'] == 'kpi':
            compact.update({k: data.get(k) for k in ('value', 'previous', 'change_pct', 'target', 'target_pct') if k in data})
        elif data['item_type'] == 'chart':
            compact['labels'] = data['labels'][:30]
            compact['series'] = [{'name': d['label'], 'values': [round(v, 2) for v in d['data'][:30]]} for d in data['datasets'][:4]]
        elif data['item_type'] == 'list':
            compact['columns'] = [c['label'] for c in data['columns']]
            compact['rows'] = [r['cells'] for r in data['rows'][:15]]
        else:
            raise UserError(_('There is nothing to summarise on this item.'))
        text = self._chat(SUMMARY_SYSTEM, json.dumps(compact, default=str), max_tokens=500)
        item.dashboard_id._log('ai', _('Insight on %s', item.name), item=item)
        return text.strip()
