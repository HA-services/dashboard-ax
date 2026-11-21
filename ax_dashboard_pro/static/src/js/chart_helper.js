/** @odoo-module **/
// Chart.js loading and configuration for Odoo 16, which ships Chart.js 2.9.
import { loadJS } from "@web/core/assets";

let chartPromise = null;

export async function loadChart() {
    if (!chartPromise) {
        chartPromise = loadJS("/web/static/lib/Chart/Chart.js").then(() => window.Chart);
    }
    return chartPromise;
}

const NAVY = "#0b2545";
const GRID = "rgba(11, 37, 69, 0.08)";

export function formatNumber(value, meta, compactOverride) {
    if (value === null || value === undefined || Number.isNaN(value)) {
        return "-";
    }
    meta = meta || {};
    const fmt = compactOverride || meta.format || "auto";
    const decimals = meta.decimals === undefined || meta.decimals === null ? 2 : meta.decimals;
    const abs = Math.abs(value);
    let text;
    const locale = (document.documentElement.lang || "en").replace("_", "-");
    const plain = (v, d) => new Intl.NumberFormat(locale, { minimumFractionDigits: d, maximumFractionDigits: d }).format(v);
    const compact = (v) => {
        const a = Math.abs(v);
        if (a >= 1e9) { return plain(v / 1e9, 1) + "B"; }
        if (a >= 1e6) { return plain(v / 1e6, 1) + "M"; }
        if (a >= 1e3) { return plain(v / 1e3, 1) + "K"; }
        return plain(v, a % 1 ? 1 : 0);
    };
    switch (fmt) {
        case "integer": text = plain(Math.round(value), 0); break;
        case "decimal": text = plain(value, decimals); break;
        case "percent": text = plain(value, decimals) + "%"; break;
        case "compact": text = compact(value); break;
        case "monetary":
            text = abs >= 1e6 ? compact(value) : plain(value, decimals);
            text = meta.currency_position === "after" ? text + " " + (meta.currency_symbol || "") : (meta.currency_symbol || "") + text;
            break;
        default:
            text = abs >= 1e6 ? compact(value) : plain(value, Number.isInteger(value) ? 0 : decimals);
            if (meta.auto_monetary) {
                text = meta.currency_position === "after" ? text + " " + (meta.currency_symbol || "") : (meta.currency_symbol || "") + text;
            }
    }
    return (meta.prefix || "") + text + (meta.suffix || "");
}

export function buildConfig(data) {
    const type = data.chart_type;
    const meta = data.meta || {};
    const circular = ["pie", "doughnut", "polar"].includes(type);
    const colors = data.colors || [];
    const datasets = data.datasets.map((ds, i) => {
        const color = colors[i % colors.length] || "#1e5eff";
        const base = { label: ds.label, data: ds.data };
        if (circular) {
            base.backgroundColor = data.labels.map((_, k) => colors[k % colors.length]);
            base.borderColor = "#ffffff";
            base.borderWidth = 2;
        } else if (ds.compare) {
            base.borderColor = "#9aa7b8";
            base.backgroundColor = "rgba(154, 167, 184, 0.35)";
            base.borderDash = [6, 4];
            base.pointRadius = 2;
            base.fill = false;
        } else if (["line", "area"].includes(type)) {
            base.borderColor = color;
            base.backgroundColor = type === "area" ? color + "33" : color;
            base.fill = type === "area";
            base.lineTension = 0.3;
            base.pointRadius = 3;
        } else {
            base.backgroundColor = color;
        }
        return base;
    });
    const chartType = { pie: "pie", doughnut: "doughnut", polar: "polarArea", line: "line", area: "line", hbar: "horizontalBar" }[type] || "bar";
    const options = {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 350 },
        legend: { display: !!data.show_legend, position: circular ? "right" : "bottom", labels: { boxWidth: 12, fontColor: NAVY } },
        tooltips: {
            callbacks: {
                label: (item, chartData) => {
                    const ds = chartData.datasets[item.datasetIndex];
                    const value = ds.data[item.index];
                    const name = circular ? chartData.labels[item.index] : ds.label;
                    return (name ? name + ": " : "") + formatNumber(value, meta);
                },
            },
        },
    };
    if (!circular) {
        const valueAxis = { stacked: !!data.stacked, gridLines: { color: GRID }, ticks: { beginAtZero: true, fontColor: NAVY, callback: (v) => formatNumber(v, meta, "compact") } };
        const labelAxis = { stacked: !!data.stacked, gridLines: { display: false }, ticks: { fontColor: NAVY } };
        options.scales = type === "hbar" ? { xAxes: [valueAxis], yAxes: [labelAxis] } : { xAxes: [labelAxis], yAxes: [valueAxis] };
    } else if (type === "polar") {
        options.scale = { gridLines: { color: GRID }, ticks: { display: false } };
    }
    return { type: chartType, data: { labels: data.labels, datasets }, options };
}
