# Installation and configuration

## Requirements

- Odoo 16 (any hosting: Odoo.sh, on premise, other). Module depends on base, web and mail.
- Chart library: Chart.js 2.9 (bundled with Odoo 16).
- For MySQL connections only: `pip install pymysql` on the server.
- Excel files (.xlsx) are read with the Python standard library, no extra package needed.

## Install

1. Copy the folder `ax_dashboard_pro` into a directory in your addons path.
2. Restart Odoo, enable developer mode, Apps, Update Apps List.
3. Search for **AXSync Dashboard Pro** and click Install.
4. Reload the browser. A **Dashboards** app appears in the Apps menu.

## Access groups

Open Settings, Users, pick a user, section **AXSync Dashboards**:

- **Dashboard User**: opens dashboards shared with them, uses filters, exports.
- **Dashboard Builder**: creates and edits their own dashboards and items, uses templates.
- **Dashboard Manager**: manages all dashboards, connections, SQL items, settings, logs. Implies Odoo Administration rights.

## Settings

Dashboards, Configuration, Settings.

| Setting | Purpose | Default |
|---|---|---|
| Allow custom SQL items | Master switch for SQL items. Off by default. | Off |
| Allow private hosts for JSON APIs | Lets JSON API items call hosts on private networks. Also applies to the alert webhook. | Off |
| Alert webhook URL | Slack, Teams, Discord or any endpoint accepting JSON with a `text` key. Use Send test message to check it. | Empty |
| Slow item threshold (ms) | Items slower than this are written to the performance log. | 1000 |
| Anomaly sensitivity (z-score) | Higher means fewer anomaly flags. | 3.0 |
| AI provider, base URL, API key, model | Configuration for the AI assistant. | Empty |

## Scheduled actions

Two cron jobs are installed: KPI snapshots, alerts and anomaly checks (daily) and scheduled email reports (hourly). Check they are active under Settings, Technical, Scheduled Actions.

## Uninstall

Uninstalling removes dashboards, items, templates, connections and logs created by the module. Export the dashboards you want to keep first.

> Odoo 16 note: Odoo 16 uses the legacy `tree` view type and `groups_id`.
