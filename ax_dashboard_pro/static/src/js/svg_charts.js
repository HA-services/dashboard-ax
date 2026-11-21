/** @odoo-module **/
// Charts drawn as plain SVG: bullet, flower, radial bar and country map. They do not depend on Chart.js,
// so they look and behave the same on every Odoo version.
import { formatNumber, themeColors } from "./chart_helper";
import { WORLD } from "./world_map";

export const SVG_TYPES = ["bullet", "flower", "radial", "map"];


const esc = (v) => String(v === null || v === undefined ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const short = (v, n) => (String(v).length > n ? String(v).slice(0, n - 1) + "…" : String(v));
const num = (v) => Math.round(v * 10) / 10;

function series(data) {
    const values = (data.datasets[0] && data.datasets[0].data) || [];
    return { labels: data.labels || [], values, max: Math.max(1e-9, ...values.map((v) => Math.abs(v))) };
}

function bullet(data, hide) {
    const { labels, values } = series(data);
    const target = data.target || 0;
    const scale = Math.max(target, ...values, 1e-9) * 1.1;
    const colors = themeColors(data.colors || []);
    const rowH = 34;
    const width = 420;
    const x0 = 120;
    const w = 250;
    const rows = labels.map((label, i) => {
        const y = i * rowH + 6;
        const v = values[i] || 0;
        const color = colors[0] || "#1e5eff";
        const tx = target ? x0 + (target / scale) * w : null;
        return `<g data-i="${i}" class="ax-svg-hit">
            <text x="0" y="${y + 14}" font-size="11" style="fill:var(--ax-text,#0b2545)">${esc(short(label, 18))}</text>
            <rect x="${x0}" y="${y}" width="${w * 0.6}" height="18" style="fill:var(--ax-line,#dfe6f2)" fill-opacity="0.9"/>
            <rect x="${x0 + w * 0.6}" y="${y}" width="${w * 0.25}" height="18" style="fill:var(--ax-line,#e9eef7)" fill-opacity="0.6"/>
            <rect x="${x0 + w * 0.85}" y="${y}" width="${w * 0.15}" height="18" style="fill:var(--ax-line,#f3f6fb)" fill-opacity="0.3"/>
            <rect x="${x0}" y="${y + 6}" width="${num(Math.max(0, (v / scale) * w))}" height="6" fill="${color}"/>
            ${tx !== null ? `<rect x="${num(tx - 1.5)}" y="${y + 2}" width="3" height="14" style="fill:var(--ax-text,#0b2545)"/>` : ""}
            <text x="${x0 + w + 8}" y="${y + 14}" font-size="11" style="fill:var(--ax-text,#0b2545)">${hide ? "****" : esc(formatNumber(v, data.meta, "compact"))}</text>
            <title>${esc(label)}: ${hide ? "****" : esc(formatNumber(v, data.meta))}${target ? " (target " + esc(formatNumber(target, data.meta)) + ")" : ""}</title>
        </g>`;
    }).join("");
    const height = Math.max(40, labels.length * rowH + 10);
    return `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMin meet" class="ax-svg-chart">${rows}</svg>`;
}

function flower(data, hide) {
    const { labels, values, max } = series(data);
    const colors = themeColors(data.colors || ["#1e5eff"]);
    const n = Math.max(1, labels.length);
    const cx = 150;
    const cy = 150;
    const minLen = 30;
    const maxLen = 105;
    const half = Math.min(22, Math.max(7, (Math.PI * (minLen + 50)) / n / 2.6));
    const petals = labels.map((label, i) => {
        const len = minLen + (Math.abs(values[i] || 0) / max) * (maxLen - minLen);
        const angle = (360 / n) * i;
        const color = colors[i % colors.length];
        const tip = (len + 12);
        const rad = ((angle - 90) * Math.PI) / 180;
        const lx = cx + Math.cos(rad) * (tip + 4);
        const ly = cy + Math.sin(rad) * (tip + 4);
        const anchor = Math.abs(Math.cos(rad)) < 0.25 ? "middle" : (Math.cos(rad) > 0 ? "start" : "end");
        return `<g data-i="${i}" class="ax-svg-hit">
            <path d="M${cx} ${cy} C ${cx - half * 1.6} ${cy - len * 0.35}, ${cx - half} ${cy - len * 0.95}, ${cx} ${cy - len} C ${cx + half} ${cy - len * 0.95}, ${cx + half * 1.6} ${cy - len * 0.35}, ${cx} ${cy} Z"
                  fill="${color}" fill-opacity="0.78" stroke="#fff" stroke-width="1.5" transform="rotate(${num(angle)} ${cx} ${cy})"/>
            <text x="${num(lx)}" y="${num(ly)}" font-size="10" style="fill:var(--ax-text,#0b2545)" text-anchor="${anchor}">${esc(short(label, 14))}</text>
            <title>${esc(label)}: ${hide ? "****" : esc(formatNumber(values[i], data.meta))}</title>
        </g>`;
    }).join("");
    return `<svg viewBox="0 0 300 300" preserveAspectRatio="xMidYMid meet" class="ax-svg-chart">${petals}<circle cx="${cx}" cy="${cy}" r="10" style="fill:var(--ax-card,#fff);stroke:var(--ax-text,#0b2545)" stroke-opacity="0.15"/></svg>`;
}

function radial(data, hide) {
    const { labels, values, max } = series(data);
    const colors = themeColors(data.colors || ["#1e5eff"]);
    const count = Math.min(labels.length, 8);
    const cx = 150;
    const cy = 135;
    const step = Math.min(16, 120 / Math.max(1, count));
    const arcs = [];
    for (let i = 0; i < count; i++) {
        const r = 125 - i * step - step / 2;
        const frac = Math.max(0, Math.min(1, (values[i] || 0) / max));
        const sweep = frac * 270;
        const a0 = (-225 * Math.PI) / 180;
        const a1 = a0 + (sweep * Math.PI) / 180;
        const p = (a) => `${num(cx + r * Math.cos(a))} ${num(cy + r * Math.sin(a))}`;
        const track = `M${p(a0)} A${r} ${r} 0 1 1 ${p(a0 + (270 * Math.PI) / 180)}`;
        const bar = frac > 0 ? `M${p(a0)} A${r} ${r} 0 ${sweep > 180 ? 1 : 0} 1 ${p(a1)}` : "";
        arcs.push(`<g data-i="${i}" class="ax-svg-hit">
            <path d="${track}" fill="none" style="stroke:var(--ax-line,#e8edf5)" stroke-width="${step - 3}" stroke-linecap="round"/>
            ${bar ? `<path d="${bar}" fill="none" stroke="${colors[i % colors.length]}" stroke-width="${step - 3}" stroke-linecap="round"/>` : ""}
            <title>${esc(labels[i])}: ${hide ? "****" : esc(formatNumber(values[i], data.meta))}</title>
        </g>`);
    }
    const legend = labels.slice(0, count).map((l, i) => `<g transform="translate(0 ${i * 14})"><rect width="9" height="9" y="-8" rx="2" fill="${colors[i % colors.length]}"/><text x="14" font-size="10" style="fill:var(--ax-text,#0b2545)">${esc(short(l, 14))}</text></g>`).join("");
    return `<svg viewBox="0 0 420 270" preserveAspectRatio="xMidYMid meet" class="ax-svg-chart">${arcs.join("")}<g transform="translate(290 ${135 - count * 7})">${legend}</g></svg>`;
}

function worldMap(data, hide) {
    const codes = data.codes || [];
    const values = (data.datasets[0] && data.datasets[0].data) || [];
    const max = Math.max(1e-9, ...values.map((v) => Math.abs(v)));
    const base = themeColors(data.colors || [])[0] || "#1e5eff";
    const hit = {};
    codes.forEach((c, i) => { if (c) { hit[c] = i; } });
    const paths = Object.keys(WORLD).map((code) => {
        const i = hit[code];
        if (i === undefined) {
            return `<path d="${WORLD[code]}" style="fill:var(--ax-line,#e3e8f1);stroke:var(--ax-card,#fff)" stroke-width="0.5"/>`;
        }
        const op = 0.25 + 0.75 * (Math.abs(values[i] || 0) / max);
        return `<path data-i="${i}" class="ax-svg-hit" d="${WORLD[code]}" fill="${base}" fill-opacity="${num(op)}" stroke="#fff" stroke-width="0.5"><title>${esc(data.labels[i])}: ${hide ? "****" : esc(formatNumber(values[i], data.meta))}</title></path>`;
    }).join("");
    return `<svg viewBox="0 14 1000 398" preserveAspectRatio="xMidYMid meet" class="ax-svg-chart ax-svg-map"><clipPath id="ax-map-clip"><rect x="0" y="14" width="1000" height="398"/></clipPath><g clip-path="url(#ax-map-clip)">${paths}</g></svg>`;
}

export function svgChart(data, hideValues) {
    switch (data.chart_type) {
        case "bullet": return bullet(data, hideValues);
        case "flower": return flower(data, hideValues);
        case "radial": return radial(data, hideValues);
        case "map": return worldMap(data, hideValues);
    }
    return "";
}
