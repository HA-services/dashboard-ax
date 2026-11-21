/** @odoo-module **/
import { Component, markup, onWillUnmount, proxy, signal, t, useProps } from "@odoo/owl";
import { useLayoutEffect } from "@web/owl2/utils";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { loadChart, buildConfig, formatNumber, setChartTheme } from "./chart_helper";
import { SVG_TYPES, svgChart } from "./svg_charts";

export class AxItem extends Component {
    static template = "ax_dashboard_pro.Item";
    props = useProps({
        item: t.object(),
        filters: t.object(),
        hideValues: t.boolean(),
        editMode: t.boolean(),
        canBuild: t.boolean(),
        aiEnabled: t.boolean(),
        reloadKey: t.number(),
        onChanged: t.function().optional(),
        onDragStart: t.function().optional(),
        onResizeStart: t.function().optional(),
    });
    canvas = signal.ref();

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = proxy({ data: null, loading: true, menu: false, drill: [], insight: null, insightLoading: false, editName: false, drivers: null });
        this.chart = null;
        this.token = 0;
        useLayoutEffect(
            () => { this.load(); },
            () => [JSON.stringify(this.props.filters), this.props.reloadKey]
        );
        onWillUnmount(() => this.destroyChart());
    }

    get currentDrill() {
        const last = this.state.drill[this.state.drill.length - 1];
        return last ? { level: last.level, domain: last.domain } : {};
    }

    async load() {
        const token = ++this.token;
        this.state.loading = !this.state.data;
        let data;
        try {
            data = await this.orm.call("ax.dashboard.item", "get_data", [[this.props.item.id]], {
                filters: this.props.filters,
                drill: this.currentDrill,
            });
        } catch (error) {
            data = { error: (error.data && error.data.message) || error.message || "Error", item_type: this.props.item.item_type, name: this.props.item.name, meta: {} };
        }
        if (token !== this.token) {
            return;
        }
        this.state.data = data;
        this.state.loading = false;
        if (data.item_type === "chart" && !data.error && !SVG_TYPES.includes(data.chart_type)) {
            await this.renderChart();
        } else {
            this.destroyChart();
        }
    }

    destroyChart() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
    }

    async renderChart() {
        const Chart = await loadChart();
        await new Promise((resolve) => requestAnimationFrame(resolve));
        if (!this.canvas() || !this.state.data || this.state.data.item_type !== "chart") {
            return;
        }
        this.destroyChart();
        const data = this.state.data;
        setChartTheme(document.querySelector(".ax-root") || this.canvas());
        const config = buildConfig(data);
        config.options.onClick = (evt, elements) => {
            if (elements && elements.length) {
                const el = elements[0];
                this.onChartClick(el.index !== undefined ? el.index : el._index);
            }
        };
        config.options.onHover = (evt, elements) => {
            const target = ((evt && evt.native) || evt || {}).target;
            if (target && target.style) {
                target.style.cursor = elements && elements.length ? "pointer" : "default";
            }
        };
        this.chart = new Chart(this.canvas(), config);
    }

    get isSvg() {
        const d = this.state.data;
        return !!d && d.item_type === "chart" && SVG_TYPES.includes(d.chart_type);
    }

    get svgHtml() {
        setChartTheme(document.querySelector(".ax-root") || document.body);
        return markup(svgChart(this.state.data, this.props.hideValues));
    }

    onSvgClick(ev) {
        const node = ev.target.closest && ev.target.closest("[data-i]");
        if (node) {
            this.onChartClick(parseInt(node.dataset.i, 10));
        }
    }

    // ------------------------------------------------------------ formatting
    get isError() {
        return !!(this.state.data && this.state.data.error);
    }

    fmt(value) {
        return formatNumber(value, this.state.data && this.state.data.meta);
    }

    get kpiValue() {
        return this.props.hideValues ? "****" : this.fmt(this.state.data.value);
    }

    get changeClass() {
        const c = this.state.data.change_pct;
        if (c === null || c === undefined) {
            return "";
        }
        return c >= 0 ? "ax-up" : "ax-down";
    }

    get changeText() {
        const c = this.state.data.change_pct;
        if (c === null || c === undefined) {
            return "";
        }
        return (c >= 0 ? "+" : "") + c + "%";
    }

    get sparkPath() {
        const pts = this.state.data.spark || [];
        if (pts.length < 2) {
            return "";
        }
        const min = Math.min(...pts);
        const max = Math.max(...pts);
        const span = max - min || 1;
        return pts.map((v, i) => `${i ? "L" : "M"}${(i / (pts.length - 1)) * 100},${28 - ((v - min) / span) * 24}`).join(" ");
    }

    cell(row, idx) {
        const col = this.state.data.columns[idx];
        const v = row.cells[idx];
        if (this.props.hideValues && col && ["float", "monetary", "integer"].includes(col.type)) {
            return "****";
        }
        if (col && ["float", "monetary"].includes(col.type) && typeof v === "number") {
            return formatNumber(v, this.state.data.meta, col.type === "monetary" ? "monetary" : "decimal");
        }
        return v === false || v === null || v === undefined ? "" : v;
    }

    // ------------------------------------------------------------ drill
    async onChartClick(index) {
        const data = this.state.data;
        const domain = data.domains && data.domains[index];
        if (!domain) {
            return;
        }
        const previous = (data.drill && data.drill.domain) || [];
        const combined = previous.concat(domain);
        if (data.drill && data.drill.level < data.drill.max) {
            this.state.drill.push({ level: data.drill.level + 1, domain: combined, label: data.labels[index] });
            await this.load();
        } else {
            this.openRecords(combined);
        }
    }

    async drillUp() {
        this.state.drill.pop();
        await this.load();
    }

    get breadcrumb() {
        return this.state.drill.map((d) => d.label).join(" / ");
    }

    openRecords(domain) {
        const data = this.state.data;
        if (!data.res_model) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: data.name,
            res_model: data.res_model,
            views: [[false, "list"], [false, "form"]],
            domain: domain || data.domain || [],
        });
    }

    onKpiClick() {
        const data = this.state.data;
        if (data.res_model && data.domain) {
            this.openRecords(data.domain);
        }
    }

    onRowClick(row) {
        const data = this.state.data;
        if (data.res_model && row.id) {
            this.action.doAction({ type: "ir.actions.act_window", res_model: data.res_model, res_id: row.id, views: [[false, "form"]] });
        }
    }

    // ------------------------------------------------------------ menu actions
    noop() {}

    toggleMenu(ev) {
        ev.stopPropagation();
        this.state.menu = !this.state.menu;
    }

    closeMenu() {
        this.state.menu = false;
    }

    async refresh() {
        this.closeMenu();
        await this.load();
    }

    exportUrl(fmt) {
        const q = new URLSearchParams({
            filters: JSON.stringify(this.props.filters),
            level: String(this.currentDrill.level || 0),
            drill_domain: JSON.stringify(this.currentDrill.domain || []),
        });
        return `/ax_dashboard/item/${this.props.item.id}/${fmt}?${q.toString()}`;
    }

    download(fmt) {
        this.closeMenu();
        browser.location.href = this.exportUrl(fmt);
    }

    downloadPng() {
        this.closeMenu();
        if (!this.canvas()) {
            return;
        }
        const link = document.createElement("a");
        link.download = (this.state.data.name || "chart") + ".png";
        const c = this.canvas();
        const tmp = document.createElement("canvas");
        tmp.width = c.width;
        tmp.height = c.height;
        const ctx = tmp.getContext("2d");
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, tmp.width, tmp.height);
        ctx.drawImage(c, 0, 0);
        link.href = tmp.toDataURL("image/png");
        link.click();
    }

    async openForm() {
        this.closeMenu();
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "ax.dashboard.item",
            res_id: this.props.item.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async quick(vals) {
        this.closeMenu();
        try {
            await this.orm.call("ax.dashboard.item", "quick_update", [[this.props.item.id], vals]);
            await this.load();
        } catch (error) {
            this.notification.add((error.data && error.data.message) || error.message, { type: "danger" });
        }
    }

    get chartTypes() {
        return [["bar", "Bar"], ["hbar", "Horizontal bar"], ["stacked", "Stacked"], ["line", "Line"], ["area", "Area"], ["pie", "Pie"], ["doughnut", "Doughnut"], ["polar", "Polar area"]];
    }

    async remove() {
        this.closeMenu();
        if (!window.confirm("Remove this item from the dashboard?")) {
            return;
        }
        await this.orm.unlink("ax.dashboard.item", [this.props.item.id]);
        this.props.onChanged && this.props.onChanged();
    }

    async insight() {
        this.closeMenu();
        this.state.insightLoading = true;
        try {
            this.state.insight = await this.orm.call("ax.dashboard.item", "ai_insight", [[this.props.item.id], this.props.filters]);
        } catch (error) {
            this.notification.add((error.data && error.data.message) || error.message, { type: "danger" });
        }
        this.state.insightLoading = false;
    }

    async openDrivers(fieldName) {
        this.closeMenu();
        try {
            this.state.drivers = await this.orm.call("ax.dashboard.item", "get_drivers", [[this.props.item.id]], {
                filters: this.props.filters,
                field_name: fieldName || false,
            });
        } catch (error) {
            this.state.drivers = { error: (error.data && error.data.message) || error.message || "Error" };
        }
    }

    signed(value) {
        const text = this.fmt(Math.abs(value));
        return (value < 0 ? "-" : value > 0 ? "+" : "") + text;
    }

    get driversChange() {
        const d = this.state.drivers;
        if (!d || d.change_pct === null || d.change_pct === undefined) {
            return "";
        }
        return (d.change_pct > 0 ? "+" : "") + d.change_pct + "%";
    }

    get paceText() {
        const d = this.state.data;
        if (!d || d.pace_pct === undefined) {
            return "";
        }
        return this.fmt(d.pace_value) + " (" + d.pace_pct + "% of target)";
    }

    // ------------------------------------------------------------ to-do
    async toggleTodo(line) {
        await this.orm.call("ax.dashboard.item", "toggle_todo", [[this.props.item.id], line.id, !line.done]);
        await this.load();
    }

    async addTodo(ev) {
        const input = ev.target;
        const text = input.value.trim();
        if (ev.key && ev.key !== "Enter") {
            return;
        }
        if (!text) {
            return;
        }
        input.value = "";
        await this.orm.call("ax.dashboard.item", "add_todo", [[this.props.item.id], text]);
        await this.load();
    }

    async removeTodo(line) {
        await this.orm.call("ax.dashboard.item", "remove_todo", [[this.props.item.id], line.id]);
        await this.load();
    }
}
