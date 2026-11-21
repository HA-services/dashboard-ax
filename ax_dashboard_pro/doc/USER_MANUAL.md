# User manual

## 1. Opening a dashboard

Open **Dashboards** from the Apps menu. Use the dashboard selector at the top left. Each item loads independently, so a slow item never blocks the page.

Toolbar, left to right: dashboard selector, date preset, reset filters, Views (saved filter sets), refresh all, auto refresh, comments, TV mode, export, edit layout, more.

## 2. Filters

- **Date preset**: All time, Today, Yesterday, This week, Last week, This month, Last month, This quarter, Last quarter, This year, Last year, Last 7 days, Last 30 days, Last 90 days, Last 12 months, Year to date, This financial year, Last financial year, Tomorrow, Next week, Next month, Next quarter, Next year, Custom range.
- **Global filters**: dashboards can expose field filters (customer, salesperson, company). Choosing a value applies it to every item that has the field.
- **Views**: save the current filter set under a name and switch back with one click.
- **Financial year**: the financial presets follow the fiscal year end set on the company in Odoo.

## 3. Items

Hover an item and open the menu:

- Refresh the item.
- Drill down to the records behind the number.
- Export: Excel, CSV, PDF, and PNG for canvas charts (bar, line, pie and similar; not the SVG charts bullet, flower, radial bar and map).
- Quick edit: change title, chart type and grouping in place.
- Copy to another dashboard or move it.
- Edit or delete (builders and managers).

Clicking a chart bar, slice or point opens the matching records. Clicking a KPI tile opens its records.

## 4. Edit layout

Press **Edit layout**. Drag items by the header, resize from the corner. The grid has 12 columns and items snap to it. New items take the first free space. Press **Save layout**.

## 5. Sharing

Dashboards are private to their creator by default. Open the dashboard form, tab Sharing. Under Who can open it, add users or groups, or tick Visible to every dashboard user. Under Who can change it, add users who may edit. Viewers see the dashboard with their own access rights: for Odoo model items they only see data they are allowed to read.

## 6. Smart insights

- **Why did it change?** Open the item menu on a KPI or chart and choose it. The module compares the current period with the comparison period (previous period, or same period last year when set on the item) and lists the groups that moved the number most, with the amount and share of the net change. Use the Split by buttons to switch the dimension. Needs a date range other than all time, a date field on the item and a sum or count measure. See doc/INSIGHTS_GUIDE.md.
- **Forecast.** On the item form set Forecast periods (1 to 12) on a line, area or bar chart grouped by date.
- **Target pacing.** Set a target on a KPI. When the period is still running, the tile shows what the period is on pace to reach.

## 7. TV mode

Full screen, hides the menus, rotates through the dashboards you choose, refreshes on the interval you set.

## 8. Version history

Changes to a dashboard create version snapshots (the latest 40 are kept). Open a version to restore it; the current state is saved as a new version first.

## 9. Menu entries

On the dashboard form, group Apps menu, tick **Show in the Apps menu** to give a dashboard its own menu entry. Only managers can do this.

## 10. Themes

Each dashboard has a theme: Navy, Ocean, Slate, Midnight, Emerald, Sunset or Light. Charts follow the theme colors.

## 11. Activity and performance

Managers see who opened, edited or exported what under Monitoring, Activity log. Items slower than the threshold appear under Monitoring, Performance.
