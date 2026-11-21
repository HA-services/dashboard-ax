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

let NAVY = "#0b2545";
let GRID = "rgba(11, 37, 69, 0.08)";
let DARK = false;

const luminance = (hex) => {
    const m = /^#?([0-9a-f]{6})$/i.exec((hex || "").trim());
    if (!m) { return 1; }
    const n = parseInt(m[1], 16);
    return (0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
};
const lighten = (hex) => {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
    if (!m || luminance(hex) > 0.45) { return hex; }
    const n = parseInt(m[1], 16);
    const mix = (c) => Math.round(c + (255 - c) * 0.55).toString(16).padStart(2, "0");
    return "#" + mix(n >> 16) + mix((n >> 8) & 255) + mix(n & 255);
};

/** Read the colours of the dashboard theme from the element the chart sits in. */
export function setChartTheme(el) {
    const cs = getComputedStyle(el);
    const text = cs.getPropertyValue("--ax-text").trim();
    const line = cs.getPropertyValue("--ax-line").trim();
    const bg = cs.getPropertyValue("--ax-bg").trim();
    DARK = bg ? luminance(bg) < 0.3 : false;
    NAVY = text || "#0b2545";
    GRID = DARK ? "rgba(255, 255, 255, 0.12)" : (line ? "rgba(11, 37, 69, 0.08)" : "rgba(11, 37, 69, 0.08)");
}
export const themeColors = (colors) => (DARK ? colors.map(lighten) : colors);
export const isDark = () => DARK;

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


function buildSpecial(data, meta, colors, v4) {
    const type = data.chart_type;
    const base = { responsive: true, maintainAspectRatio: false, animation: { duration: 350 } };
    const textKey = v4 ? "color" : "fontColor";
    const legend = { display: !!data.show_legend && type !== "funnel", position: "bottom", labels: { boxWidth: 12, [textKey]: NAVY } };
    const color = (i) => colors[i % colors.length] || "#1e5eff";
    const options = Object.assign({}, base);
    const setLegend = () => { if (v4) { options.plugins = Object.assign(options.plugins || {}, { legend }); } else { options.legend = legend; } };
    const setTooltip = (cfg) => { if (v4) { options.plugins = Object.assign(options.plugins || {}, { tooltip: cfg }); } else { options.tooltips = cfg; } };
    if (type === "radar") {
        const datasets = data.datasets.map((ds, i) => ({
            label: ds.label, data: ds.data, borderColor: color(i), backgroundColor: color(i) + "33",
            pointBackgroundColor: color(i), pointRadius: 3, borderWidth: 2,
        }));
        if (v4) {
            options.scales = { r: { beginAtZero: true, grid: { color: GRID }, angleLines: { color: GRID }, ticks: { display: false }, pointLabels: { color: NAVY } } };
        } else {
            options.scale = { gridLines: { color: GRID }, angleLines: { color: GRID }, ticks: { display: false, beginAtZero: true }, pointLabels: { fontColor: NAVY } };
        }
        setLegend();
        return { type: "radar", data: { labels: data.labels, datasets }, options };
    }
    if (type === "scatter") {
        const pts = data.points || [];
        const datasets = [{
            label: data.name || "", data: pts.map((p) => ({ x: p.x, y: p.y })),
            backgroundColor: color(0) + "cc", borderColor: color(0), pointRadius: 6, pointHoverRadius: 8,
        }];
        const text = (title) => ({ display: !!title, text: title || "", [textKey]: NAVY });
        const tickFmt = { [textKey]: NAVY, callback: (v) => formatNumber(v, meta, "compact") };
        if (v4) {
            options.scales = {
                x: { title: text(data.x_label), grid: { color: GRID }, ticks: tickFmt },
                y: { title: text(data.y_label), grid: { color: GRID }, ticks: tickFmt },
            };
        } else {
            const lab = (t) => ({ display: !!t, labelString: t || "", fontColor: NAVY });
            options.scales = {
                xAxes: [{ scaleLabel: lab(data.x_label), gridLines: { color: GRID }, ticks: tickFmt }],
                yAxes: [{ scaleLabel: lab(data.y_label), gridLines: { color: GRID }, ticks: tickFmt }],
            };
        }
        const label = (i) => `${(pts[i] || {}).label || ""}: ${formatNumber((pts[i] || {}).x, meta, "compact")}, ${formatNumber((pts[i] || {}).y, meta, "compact")}`;
        setTooltip({ callbacks: { label: v4 ? (ctx) => label(ctx.dataIndex) : (item) => label(item.index) } });
        options.plugins = Object.assign(options.plugins || {}, v4 ? { legend: { display: false } } : {});
        if (!v4) { options.legend = { display: false }; }
        return { type: "scatter", data: { datasets }, options };
    }
    // funnel: a centred, stacked horizontal bar with an invisible spacer
    const vals = (data.datasets[0] && data.datasets[0].data) || [];
    const top = Math.max(1, ...vals);
    const datasets = [
        { label: "", data: vals.map((v) => (top - v) / 2), backgroundColor: "rgba(0,0,0,0)", hoverBackgroundColor: "rgba(0,0,0,0)", borderWidth: 0 },
        { label: (data.datasets[0] && data.datasets[0].label) || "", data: vals, backgroundColor: vals.map((_, i) => color(i)) },
    ];
    const hide = { display: false, stacked: true };
    if (v4) {
        options.indexAxis = "y";
        options.scales = { x: Object.assign({ max: top }, hide), y: { stacked: true, grid: { display: false }, ticks: { color: NAVY } } };
    } else {
        options.scales = {
            xAxes: [{ stacked: true, display: false, ticks: { max: top, min: 0 } }],
            yAxes: [{ stacked: true, gridLines: { display: false }, ticks: { fontColor: NAVY } }],
        };
    }
    options.plugins = options.plugins || {};
    const fl = (i) => `${data.labels[i]}: ${formatNumber(vals[i], meta)}`;
    setTooltip({
        filter: (item) => item.datasetIndex === 1,
        callbacks: { label: v4 ? (ctx) => fl(ctx.dataIndex) : (item) => fl(item.index) },
    });
    if (v4) { options.plugins.legend = { display: false }; } else { options.legend = { display: false }; }
    return { type: v4 ? "bar" : "horizontalBar", data: { labels: data.labels, datasets }, options };
}

export function buildConfig(data) {
    const type = data.chart_type;
    const meta = data.meta || {};
    const circular = ["pie", "doughnut", "polar"].includes(type);
    const colors = themeColors(data.colors || []);
    if (["radar", "scatter", "funnel"].includes(type)) {
        return buildSpecial(data, meta, colors, false);
    }
    const datasets = data.datasets.map((ds, i) => {
        const color = colors[i % colors.length] || "#1e5eff";
        const base = { label: ds.label, data: ds.data };
        if (circular) {
            base.backgroundColor = data.labels.map((_, k) => colors[k % colors.length]);
            base.borderColor = "#ffffff";
            base.borderWidth = 2;
        } else if (ds.forecast) {
            base.type = "line";
            base.borderColor = colors[0] || "#1e5eff";
            base.backgroundColor = "transparent";
            base.borderDash = [3, 4];
            base.borderWidth = 2;
            base.pointRadius = 3;
            base.pointStyle = "triangle";
            base.fill = false;
            base.spanGaps = false;
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
