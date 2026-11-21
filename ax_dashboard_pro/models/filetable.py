# -*- coding: utf-8 -*-
# Part of AXSync. See LICENSE file for full copyright and licensing details.
"""Reads small Excel (.xlsx) and CSV files into rows, with no third party dependency.

Limits keep a hostile or oversized upload from hurting the server: 10 MB of file,
30 MB once unzipped, 50 000 rows and 100 columns.
"""
import csv
import io
import re
import zipfile
from xml.etree import ElementTree as ET

from odoo import _
from odoo.exceptions import UserError

from . import compat

MAX_BYTES = 10 * 1024 * 1024
MAX_UNZIPPED = 30 * 1024 * 1024
MAX_ROWS = 50000
MAX_COLS = 100
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}


def _num(text):
    if text is None:
        return None
    t = str(text).strip()
    if not t:
        return None
    try:
        v = float(t.replace(',', '')) if re.fullmatch(r'[-+]?\d{1,3}(,\d{3})+(\.\d+)?', t) else float(t)
    except ValueError:
        return t
    return int(v) if v.is_integer() and abs(v) < 1e15 and '.' not in t else v


def _col_number(ref):
    letters = re.match(r'[A-Z]+', ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _read_csv(raw):
    for enc in ('utf-8-sig', 'cp1252'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise UserError(_('The file could not be decoded. Save it as UTF-8 CSV.'))
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t|')
    except csv.Error:
        dialect = csv.excel
    rows = []
    for i, row in enumerate(csv.reader(io.StringIO(text), dialect)):
        if i > MAX_ROWS:
            break
        rows.append([_num(c) for c in row[:MAX_COLS]])
    return rows


def _read_xlsx(raw):
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise UserError(_('This is not a valid .xlsx file.'))
    if sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED:
        raise UserError(_('The workbook is too large once unpacked.'))
    names = zf.namelist()
    shared = []
    if 'xl/sharedStrings.xml' in names:
        root = ET.fromstring(zf.read('xl/sharedStrings.xml'))
        for si in root.findall('m:si', NS):
            shared.append(''.join(t.text or '' for t in si.iter('{%s}t' % NS['m'])))
    sheet = None
    if 'xl/workbook.xml' in names and 'xl/_rels/workbook.xml.rels' in names:
        wb = ET.fromstring(zf.read('xl/workbook.xml'))
        first = wb.find('m:sheets/m:sheet', NS)
        if first is not None:
            rid = first.get('{%s}id' % NS['r'])
            rels = ET.fromstring(zf.read('xl/_rels/workbook.xml.rels'))
            for rel in rels:
                if rel.get('Id') == rid:
                    target = rel.get('Target').lstrip('/')
                    sheet = target if target.startswith('xl/') else 'xl/' + target
    sheet = sheet or 'xl/worksheets/sheet1.xml'
    if sheet not in names:
        raise UserError(_('The first sheet of the workbook could not be found.'))
    rows = []
    for ev, row in ET.iterparse(io.BytesIO(zf.read(sheet)), events=('end',)):
        if row.tag != '{%s}row' % NS['m']:
            continue
        cells = {}
        for c in row.findall('m:c', NS):
            idx = _col_number(c.get('r', 'A1'))
            if idx >= MAX_COLS:
                continue
            t = c.get('t')
            v = c.find('m:v', NS)
            if t == 's' and v is not None:
                val = shared[int(v.text)] if v.text and int(v.text) < len(shared) else None
            elif t == 'inlineStr':
                val = ''.join(x.text or '' for x in c.iter('{%s}t' % NS['m']))
            elif t in ('str', 'e'):
                val = v.text if v is not None else None
            elif t == 'b':
                val = bool(int(v.text)) if v is not None and v.text else None
            else:
                val = _num(v.text) if v is not None else None
            cells[idx] = val
        if cells:
            out = [None] * (max(cells) + 1)
            for k, val in cells.items():
                out[k] = val
            rows.append(out)
        row.clear()
        if len(rows) > MAX_ROWS:
            break
    return rows


def read_table(data_b64, filename=None):
    """Return (header, rows) from the value of a Binary field holding an .xlsx or .csv file."""
    if not data_b64:
        raise UserError(_('No file is attached to this item.'))
    raw = compat.binary_bytes(data_b64)
    if len(raw) > MAX_BYTES:
        raise UserError(_('The file is larger than 10 MB.'))
    is_xlsx = raw[:2] == b'PK' or (filename or '').lower().endswith('.xlsx')
    rows = _read_xlsx(raw) if is_xlsx else _read_csv(raw)
    rows = [r for r in rows if any(c not in (None, '') for c in r)]
    if not rows:
        raise UserError(_('The file has no rows.'))
    header = [str(h).strip() if h not in (None, '') else _('Column %s', i + 1) for i, h in enumerate(rows[0])]
    return header, rows[1:]


def column_index(header, name):
    wanted = (name or '').strip().lower()
    for i, h in enumerate(header):
        if h.lower() == wanted:
            return i
    raise UserError(_('The column "%(c)s" is not in the file. Columns found: %(cols)s', c=name, cols=', '.join(header)))


def aggregate(rows, gi, mi, how):
    """Group ``rows`` by column ``gi`` (None for one total) and aggregate column ``mi``."""
    buckets = {}
    for row in rows:
        key = None if gi is None else (row[gi] if gi < len(row) else None)
        if isinstance(key, float) and key.is_integer():
            key = int(key)
        val = row[mi] if mi is not None and mi < len(row) else None
        buckets.setdefault(key, []).append(val)
    out = {}
    for key, vals in buckets.items():
        nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if how == 'count' or mi is None:
            out[key] = float(len(vals))
        elif how == 'count_distinct':
            out[key] = float(len({v for v in vals if v not in (None, '')}))
        elif not nums:
            out[key] = 0.0
        elif how == 'avg':
            out[key] = sum(nums) / len(nums)
        elif how == 'min':
            out[key] = float(min(nums))
        elif how == 'max':
            out[key] = float(max(nums))
        else:
            out[key] = float(sum(nums))
    if gi is None and not out:
        out[None] = 0.0
    return out
