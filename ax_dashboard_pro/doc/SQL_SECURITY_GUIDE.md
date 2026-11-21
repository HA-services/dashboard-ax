# SQL items and security

SQL items are powerful and off by default.

## Requirements to use

1. Dashboard Manager group.
2. **Allow custom SQL items** enabled in Settings.

## Protections

- Only a single SELECT or WITH statement is accepted. Extra statements, comments, backslashes, dollar quoting, write and DDL keywords, COPY, SET, file and sleep functions, system catalogs and a list of sensitive tables (users, API keys, system parameters, attachments, bank accounts, connections) are rejected.
- The statement runs inside a read-only transaction with a statement timeout and a row limit.
- Parameters use placeholders, never string concatenation.
- Results are shown to everyone with access to the dashboard. SQL bypasses Odoo record rules, so a SQL item can expose data a viewer could not otherwise read. Share SQL dashboards with care.

## External connections

Configuration, Connections. PostgreSQL works with the Odoo Python environment. MySQL needs `pymysql`. Use a database user with SELECT rights only. The password field is readable by Dashboard Managers only. It is stored in the database as entered, not encrypted, so use a dedicated read-only database user.

## JSON API items

Calls are made from the Odoo server. Private and loopback hosts are blocked unless **Allow private hosts** is enabled.

## Other security notes

- All Odoo model items use the viewer's own rights and record rules. No sudo.
- Domains and formulas are evaluated with a restricted evaluator.
- Uploaded files are limited to 10 MB, 50,000 rows and 100 columns and are parsed without executing macros.
