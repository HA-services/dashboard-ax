# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
import csv
import io
import re
from html import escape

from odoo import _, api, models
from odoo.exceptions import UserError


def fmt_value(v, meta, digits=None):
    """Plain text number following the item format (server side, for files and emails)."""
    if v is None or v == '':
        return ''
    if isinstance(v, str):
        return v
    f = meta.get('format') or 'auto'
    dec = meta.get('decimals', 2) if digits is None else digits
    if f == 'integer':
        txt = '{:,.0f}'.format(v)
    elif f == 'percent':
        txt = ('{:,.%df}' % dec).format(v) + '%'
    elif f == 'compact':
        from .safe import humanize
        txt = humanize(v, 1)
    elif f in ('decimal', 'monetary') or (f == 'auto' and meta.get('auto_monetary')):
        txt = ('{:,.%df}' % dec).format(v)
        if f == 'monetary' or meta.get('auto_monetary'):
            sym = meta.get('currency_symbol') or ''
            txt = (sym + txt) if meta.get('currency_position') != 'after' else (txt + ' ' + sym)
    else:
        txt = '{:,.0f}'.format(v) if float(v) == int(v) else '{:,.2f}'.format(v)
    return '%s%s%s' % (meta.get('prefix') or '', txt, meta.get('suffix') or '')


class AxDashboardExporter(models.AbstractModel):
    _name = 'ax.dashboard.exporter'
    _description = 'Dashboard file exporter'

    # ------------------------------------------------------------------ tables
    @api.model
    def item_table(self, data):
        """Return (title, headers, rows) for an item's computed data."""
        meta = data.get('meta') or {}
        title = data.get('name') or _('Item')
        if data.get('error'):
            return title, [_('Error')], [[data['error']]]
        t = data.get('item_type')
        if t == 'kpi':
            rows = [[_('Value'), data.get('value')]]
            if 'previous' in data:
                rows.append([_('Previous'), data['previous']])
                rows.append([_('Change %'), data.get('change_pct')])
            if 'target' in data:
                rows.append([_('Target'), data['target']])
                rows.append([_('Target reached %'), data.get('target_pct')])
            return title, [_('Metric'), _('Value')], rows
        if t == 'chart':
            heads = [_('Group')] + [d['label'] for d in data.get('datasets', [])]
            rows = []
            for i, label in enumerate(data.get('labels', [])):
                rows.append([label] + [d['data'][i] if i < len(d['data']) else None for d in data['datasets']])
            return title, heads, rows
        if t == 'list':
            return title, [c['label'] for c in data.get('columns', [])], [r['cells'] for r in data.get('rows', [])]
        if t == 'todo':
            return title, [_('Task'), _('Done')], [[l['name'], _('Yes') if l['done'] else _('No')] for l in data.get('lines', [])]
        return title, [], []

    @api.model
    def collect(self, items, filters):
        return [i.get_data(filters) for i in items]

    # ------------------------------------------------------------------ CSV and Excel
    @api.model
    def to_csv(self, data):
        title, heads, rows = self.item_table(data)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(heads)
        for r in rows:
            w.writerow([self._csv_safe(c) for c in r])
        return buf.getvalue().encode('utf-8-sig')

    @staticmethod
    def _csv_safe(v):
        """Stop spreadsheet formula injection from record names."""
        if isinstance(v, str) and v[:1] in ('=', '+', '-', '@'):
            return "'" + v
        return v

    @api.model
    def to_xlsx(self, datas, title=None):
        import xlsxwriter
        out = io.BytesIO()
        wb = xlsxwriter.Workbook(out, {'in_memory': True})
        head = wb.add_format({'bold': True, 'bg_color': '#14305a', 'font_color': '#ffffff', 'border': 1})
        used = set()
        for data in datas:
            ttl, heads, rows = self.item_table(data)
            name = re.sub(r'[\[\]:*?/\\]', '_', ttl)[:28] or 'Item'
            base, n = name, 1
            while name.lower() in used:
                n += 1
                name = '%s_%d' % (base[:25], n)
            used.add(name.lower())
            ws = wb.add_worksheet(name)
            for ci, h in enumerate(heads):
                ws.write(0, ci, h, head)
                ws.set_column(ci, ci, max(14, min(40, len(str(h)) + 6)))
            for ri, r in enumerate(rows, start=1):
                for ci, c in enumerate(r):
                    if isinstance(c, str) and c[:1] in ('=', '+', '-', '@'):
                        ws.write_string(ri, ci, c)
                    elif isinstance(c, (int, float)):
                        ws.write_number(ri, ci, c)
                    else:
                        ws.write(ri, ci, '' if c is None else str(c))
            if data.get('item_type') == 'chart' and rows and not data.get('error'):
                ctype = {'bar': 'column', 'hbar': 'bar', 'stacked': 'column', 'line': 'line', 'area': 'area',
                         'pie': 'pie', 'doughnut': 'doughnut', 'polar': 'pie'}.get(data.get('chart_type'), 'column')
                chart = wb.add_chart({'type': ctype, 'subtype': 'stacked'} if (data.get('chart_type') == 'stacked' and ctype == 'column') else {'type': ctype})
                for ci in range(1, len(heads)):
                    chart.add_series({'name': [name, 0, ci], 'categories': [name, 1, 0, len(rows), 0], 'values': [name, 1, ci, len(rows), ci]})
                chart.set_title({'name': ttl})
                ws.insert_chart(1, len(heads) + 1, chart)
        if not datas:
            wb.add_worksheet(title or 'Dashboard')
        wb.close()
        return out.getvalue()

    # ------------------------------------------------------------------ PDF (reportlab, no browser needed)
    @api.model
    def to_pdf(self, title, datas, subtitle=''):
        from reportlab.graphics.charts.barcharts import VerticalBarChart
        from reportlab.graphics.charts.lineplots import LinePlot
        from reportlab.graphics.charts.piecharts import Pie
        from reportlab.graphics.shapes import Drawing
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether

        navy = colors.HexColor('#14305a')
        blue = colors.HexColor('#1e5eff')
        palette = [colors.HexColor(c) for c in ('#1e5eff', '#1fb5a8', '#f4a261', '#8b5cf6', '#e5534b', '#2e9d57', '#f2c14e', '#6b7a93')]
        styles = getSampleStyleSheet()
        h1 = ParagraphStyle('h1', parent=styles['Title'], textColor=navy, fontSize=22, alignment=0, spaceAfter=4)
        sub = ParagraphStyle('sub', parent=styles['Normal'], textColor=colors.HexColor('#6b7a93'), fontSize=9)
        h2 = ParagraphStyle('h2', parent=styles['Heading2'], textColor=navy, fontSize=13, spaceBefore=10, spaceAfter=4)
        cell = ParagraphStyle('cell', parent=styles['Normal'], fontSize=8, leading=10)
        big = ParagraphStyle('big', parent=styles['Normal'], fontSize=22, textColor=blue, leading=26)
        out = io.BytesIO()
        doc = SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                                title=title, author='AXSync Dashboard Pro')
        story = [Paragraph(escape(title), h1), Paragraph(escape(subtitle or ''), sub), Spacer(1, 6)]
        for data in datas:
            ttl, heads, rows = self.item_table(data)
            meta = data.get('meta') or {}
            block = [Paragraph(escape(ttl), h2)]
            t = data.get('item_type')
            if data.get('error'):
                block.append(Paragraph(escape(data['error']), cell))
            elif t == 'kpi':
                block.append(Paragraph(escape(fmt_value(data.get('value'), meta)), big))
                bits = []
                if 'change_pct' in data and data['change_pct'] is not None:
                    bits.append('%+.1f%% %s' % (data['change_pct'], data.get('compare_label') or ''))
                if 'target_pct' in data:
                    bits.append(_('%s%% of target', data['target_pct']))
                if bits:
                    block.append(Paragraph(escape(' | '.join(bits)), sub))
            elif t == 'chart' and data.get('labels') and data.get('datasets'):
                block.append(self._pdf_chart(data, palette, Drawing, VerticalBarChart, Pie, LinePlot, colors))
                block.append(self._pdf_table(heads, rows, meta, cell, Table, TableStyle, Paragraph, colors, navy, limit=12))
            else:
                block.append(self._pdf_table(heads, rows, meta, cell, Table, TableStyle, Paragraph, colors, navy, limit=25))
            story.append(KeepTogether(block))
        if not datas:
            story.append(Paragraph(escape(_('This dashboard has no items.')), cell))
        doc.build(story)
        return out.getvalue()

    @staticmethod
    def _pdf_table(heads, rows, meta, cell, Table, TableStyle, Paragraph, colors, navy, limit=25):
        body = [[Paragraph(escape(str(h)), cell) for h in heads]]
        for r in rows[:limit]:
            body.append([Paragraph(escape(fmt_value(c, meta) if isinstance(c, (int, float)) and not isinstance(c, bool) else str(c if c is not None else '')), cell) for c in r])
        if not heads:
            return Paragraph('', cell)
        t = Table(body, repeatRows=1, hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), navy), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                               ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#d5dde9')),
                               ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f4f7fb')])]))
        return t

    @staticmethod
    def _pdf_chart(data, palette, Drawing, VerticalBarChart, Pie, LinePlot, colors):
        labels = [str(l)[:18] for l in data['labels'][:14]]
        sets = data['datasets']
        ctype = data.get('chart_type') or 'bar'
        d = Drawing(480, 190)
        if ctype in ('pie', 'doughnut', 'polar'):
            pie = Pie()
            pie.x, pie.y, pie.width, pie.height = 140, 15, 160, 160
            pie.data = [max(v, 0) for v in sets[0]['data'][:14]] or [1]
            pie.labels = labels
            for i in range(len(pie.data)):
                pie.slices[i].fillColor = palette[i % len(palette)]
            d.add(pie)
        elif ctype in ('line', 'area'):
            lp = LinePlot()
            lp.x, lp.y, lp.width, lp.height = 40, 25, 420, 140
            lp.data = [[(i, v) for i, v in enumerate(s['data'][:14])] for s in sets] or [[(0, 0)]]
            for i in range(len(lp.data)):
                lp.lines[i].strokeColor = palette[i % len(palette)]
                lp.lines[i].strokeWidth = 2
            d.add(lp)
        else:
            bc = VerticalBarChart()
            bc.x, bc.y, bc.width, bc.height = 40, 30, 420, 135
            bc.data = [s['data'][:14] for s in sets] or [[0]]
            bc.categoryAxis.categoryNames = labels
            bc.categoryAxis.labels.fontSize = 6
            bc.categoryAxis.labels.angle = 20
            bc.categoryAxis.labels.boxAnchor = 'ne'
            bc.valueAxis.labels.fontSize = 6
            for i in range(len(bc.data)):
                bc.bars[i].fillColor = palette[i % len(palette)]
            d.add(bc)
        return d

    # ------------------------------------------------------------------ HTML (emails)
    @api.model
    def dashboard_html(self, dashboard, datas, subtitle=''):
        parts = ['<div style="font-family:Arial,Helvetica,sans-serif;color:#2c3a57;max-width:760px">',
                 '<h2 style="color:#14305a;margin:0 0 4px 0">%s</h2>' % escape(dashboard.name),
                 '<p style="color:#6b7a93;margin:0 0 14px 0">%s</p>' % escape(subtitle)]
        kpis = [d for d in datas if d.get('item_type') == 'kpi' and not d.get('error')]
        if kpis:
            parts.append('<table style="border-collapse:collapse;width:100%"><tr>')
            for d in kpis[:4]:
                meta = d.get('meta') or {}
                change = ''
                if d.get('change_pct') is not None and 'change_pct' in d:
                    color = '#2e9d57' if d['change_pct'] >= 0 else '#e5534b'
                    change = '<div style="font-size:12px;color:%s">%+.1f%%</div>' % (color, d['change_pct'])
                parts.append('<td style="border:1px solid #e3e8f0;padding:12px;text-align:center"><div style="font-size:12px;color:#6b7a93">%s</div>'
                             '<div style="font-size:22px;font-weight:bold;color:#1e5eff">%s</div>%s</td>' % (escape(d['name']), escape(fmt_value(d.get('value'), meta)), change))
            parts.append('</tr></table>')
        for d in datas:
            if d.get('item_type') == 'kpi' and not d.get('error'):
                continue
            title, heads, rows = self.item_table(d)
            meta = d.get('meta') or {}
            parts.append('<h3 style="color:#14305a;margin:18px 0 6px 0;font-size:15px">%s</h3>' % escape(title))
            parts.append('<table style="border-collapse:collapse;width:100%;font-size:12px"><tr>')
            for h in heads:
                parts.append('<th style="background:#14305a;color:#fff;padding:5px 8px;text-align:left">%s</th>' % escape(str(h)))
            parts.append('</tr>')
            for r in rows[:15]:
                parts.append('<tr>' + ''.join('<td style="border-bottom:1px solid #e3e8f0;padding:4px 8px">%s</td>' % escape(
                    fmt_value(c, meta) if isinstance(c, (int, float)) and not isinstance(c, bool) else str(c if c is not None else '')) for c in r) + '</tr>')
            parts.append('</table>')
        parts.append('<p style="color:#9aa5b8;font-size:11px;margin-top:20px">Sent by AXSync Dashboard Pro</p></div>')
        return ''.join(parts)
