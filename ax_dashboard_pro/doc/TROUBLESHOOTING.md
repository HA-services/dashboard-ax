# Troubleshooting

**An item shows an error banner.** The message names the cause: missing field, no access, invalid domain, timeout. Open the item form and fix the named setting. Other items are not affected.

**Nothing loads, blank dashboard.** Hard refresh the browser (Ctrl+Shift+R) so the new assets load. If you use a reverse proxy or CDN, clear its cache.

**SQL item says not allowed.** You need the Manager group and Allow custom SQL items in Settings.

**External connection fails.** Test from the connection form. For MySQL install `pymysql`. Check firewall and that the database user has SELECT.

**JSON API item refused.** The host is private. Enable Allow private hosts if intended.

**Numbers differ from a list view.** Check the item domain, date field and preset, and whether the item uses company currency. Monetary values are shown in the company currency, no conversion between companies.

**Email reports not sent.** Check the cron job is active and an outgoing mail server is configured.

**Slow dashboard.** See Monitoring, Performance. Add a date filter, reduce the list limit, avoid grouping on non-stored fields.

**Map shows empty.** The record needs a country. Items grouped by a field with no country mapping show no shapes.
