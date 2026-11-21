# Compatibility report, Odoo 18

Module version 18.0.1.0.0.

| Area | Result |
|---|---|
| Install on a clean database | Passed |
| Unit and browser tests | 157 run, 0 failed, 0 errors |
| Browser interaction suite (Chromium via Playwright) | Passed |
| Chart library | Chart.js 4 (bundled with Odoo 18) |
| Aggregation API | `read_group` |
| Upgrade from an older module version | Not applicable, first release |

## Not verified

- AI calls against live providers. Tested with a mock transport only.
- MySQL connections. Code path present, needs `pymysql`, not run against a live MySQL server. External PostgreSQL was tested against a second local database.
- Right to left layout in the dashboard grid.
- Odoo.sh deployment. Tested on a local server only.
- Large datasets above a few hundred thousand records per item.

Odoo 18 uses the `list` view type and the `card` kanban template.
