# Developer guide

## Layout

- `models/item.py`: item definition and the compute methods per type.
- `models/safe.py`: domain and formula evaluation, date presets, SQL guard.
- `models/filetable.py`: CSV and XLSX reader.
- `models/connection.py`: external PostgreSQL and MySQL.
- `models/ai.py`: AI provider client and prompt building.
- `static/src/js`: Owl components, chart helper (Chart.js 4 (bundled with Odoo 19)), SVG charts, world map outlines.
- `tests`: unit and browser tests.

## Data flow

The client calls `ax.dashboard.item.get_data(filters, drill)` once per item. The server returns a payload with the item type, chart type and data, or an in-band error string. No sudo is used, so record rules apply.

## Extending

Add a chart type: add it to `CHART_TYPES` in `models/safe.py`, handle it in `_chart_extras` in `models/item.py`, and render it in `chart_helper.js` or `svg_charts.js`.

## Tests

`odoo-bin -d test -i ax_dashboard_pro --test-tags /ax_dashboard_pro --stop-after-init`. 157 tests cover engine, sources, security, AI with a mock transport, alerts, import and export, and browser flows.
