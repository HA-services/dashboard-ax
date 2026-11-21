# Smart insights guide

These features are calculated by the module. They need no AI provider and send no data anywhere, except the alert webhook, which posts the alert text to the URL you configure.

## Why did it change?

**Where:** item menu, on KPI and chart items.

**Needs:** a date range other than All time, a date field on the item, an Odoo model source, and a Sum or Count measure (averages, minimums and maximums are not additive, so they cannot be broken down this way).

**How it works:** the module reads the same item for the current period and for the comparison period, grouped by several candidate fields (the item group by, its drill-down fields, then other many2one and selection fields of the model, up to 10). For each field it measures how concentrated the change is in the three biggest movers and shows the most concentrated one first. Each row shows the change in that group and its share of the net change. Groups beyond the top six are summed into All other groups. The Split by buttons switch to another field.

**Rights:** every query runs with the viewer rights. A field the viewer cannot read is skipped.

**Reading the result:** shares can exceed 100 percent or be negative when some groups moved against the net direction. That is information: it means other groups offset part of the change.

## Forecast

See doc/CHART_GUIDE.md. Linear trend, 1 to 12 periods, line, area and bar charts grouped by date. Exports include the forecast as an extra column.

## Target pacing

**Where:** KPI tiles with a Target.

**How it works:** while the selected period is still running, projected value = current value x total days in the period / days elapsed (today counts as a day). The tile shows the projection and its percentage of the target. It is hidden for finished periods, all time, averages, minimums, maximums and non-model sources. It assumes activity is spread evenly over the period, so seasonal businesses should read it with care.

## Alert webhook

**Where:** Configuration, Settings, Alert webhook URL.

**What is sent:** a JSON body `{"text": "[Dashboard name] message", "content": "[Dashboard name] message"}` for every new alert (below minimum, above maximum, unusual change). `text` works for Slack and Teams incoming webhooks and `content` for Discord. Any endpoint that accepts JSON can receive it.

**Rules:** the host must be public unless Allow private hosts is on. A failing webhook is logged and never blocks the alert, the chatter message or the email. Alerts are throttled to one per item and kind every 24 hours, and the webhook follows the same throttle.
