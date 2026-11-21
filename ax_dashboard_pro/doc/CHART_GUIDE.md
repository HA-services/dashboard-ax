# Chart guide

All chart types support drill-down and theme colors. PNG export is available for the canvas charts; the SVG charts (bullet, flower, radial bar, map) export through Excel, CSV or PDF.

| Type | Use it for |
|---|---|
| Bar | Compare values across categories. |
| Horizontal bar | Rankings and long labels. |
| Stacked bar | Totals split by a second group. |
| Line | Trends over time, optional previous period overlay. |
| Area | Trend with volume emphasis. |
| Pie | Share of a whole, few slices. |
| Doughnut | Share of a whole with room for a label. |
| Polar area | Categories with radial magnitude. |
| Radar | Compare several measures across categories. |
| Scatter | Two measures per record, correlation. |
| Funnel | Stage conversion such as CRM pipeline. |
| Bullet | Actual against target. |
| Flower | Compact radial comparison. |
| Radial bar | Ranked values on concentric arcs. |
| Map | Values by country on a world map. |

## Choosing quickly

- Trend over time: Line or Area.
- Ranking: Horizontal bar.
- Share of total with up to 6 slices: Doughnut.
- Pipeline stages: Funnel.
- Two numeric measures per record: Scatter.
- Actual against a target: Bullet.
- Geography: Map. The map is country level only and uses the country of the record partner or a country field.

## Forecast

Line, area and bar charts grouped by a date field can show a dashed projection. Set Forecast periods on the item form (1 to 12). The line is a least squares straight line through up to the last 24 completed periods, so it needs at least 3. The running period is left out of the fit. Values never go below zero when all the history is non-negative. The forecast is a trend projection to support a conversation, not a statistical forecast.

## Second grouping

Bar, Stacked bar, Line and Area accept a second group by field and draw one series per value.
