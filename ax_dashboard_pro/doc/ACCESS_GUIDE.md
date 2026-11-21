# Access and sharing

| Capability | User | Builder | Manager |
|---|---|---|---|
| Open shared dashboards | yes | yes | yes |
| Use filters, export | yes | yes | yes |
| Create dashboards and items | no | yes | yes |
| Edit own dashboards | no | yes | yes |
| Edit all dashboards | no | no | yes |
| Use templates | no | yes | yes |
| SQL items | no | no | yes, if enabled |
| Connections and settings | no | no | yes |
| Menu entries | no | no | yes |
| Logs | no | no | yes |

Dashboards are private to their creator until shared with users or groups. Items inherit the dashboard visibility. Data inside items always follows the viewer's Odoo rights, except SQL and external connection items (see the SQL guide). Multi-company is respected: items use the viewer's allowed companies.
