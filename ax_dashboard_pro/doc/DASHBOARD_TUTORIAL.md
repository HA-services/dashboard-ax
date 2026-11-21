# Tutorial: build a sales dashboard in 10 minutes

## Option A: from a template

1. Dashboards, Manage, Template library.
2. Open **Sales performance** and click Create dashboard.
3. Open the dashboard. Items are already placed and loaded.

## Option B: from scratch

1. Dashboards, Manage, Dashboards, New. Name it "Sales".
2. Open the dashboard and press **Add item**.
3. KPI tile. Name: Revenue. Model: Sales Order. Measure: Untaxed Amount. Aggregate: Sum. Date field: Order Date. Add a domain such as status is Sales Order. Save.
4. Chart. Name: Revenue by month. Model: Sales Order. Measure: Untaxed Amount. Group by: Order Date, by month. Chart type: Line. Save.
5. Chart. Name: Top customers. Group by: Customer. Chart type: Horizontal bar. Limit 10, sort by value.
6. List. Name: Latest orders. Model: Sales Order. Columns: Number, Customer, Date, Total. Limit 10.
7. Press Edit layout, arrange the four items, Save layout.
8. Open the dashboard form, tab Sharing, and add the Sales team group under Who can open it.

## Add a comparison

On the item form set **Comparison** to Previous period or Same period last year. KPI tiles show the change and line charts draw the earlier range as a dashed series.

## Add an alert

Monitoring, Alerts, New. Pick the Revenue item, condition Below, value 50000, notify the sales manager. The daily job checks it and sends a message when it is true.

## Add an email report

Manage, Email reports, New. Pick the dashboard, recipients and frequency. The report arrives as an email with the dashboard values in the body, with the Excel and PDF files attached (you can turn each attachment off).
