/** @odoo-module **/
import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { AxItem } from "./item";

const ROW_H = 80;
const GAP = 12;

function overlaps(a, b) {
    return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/** Push items down until nothing overlaps. `fixedId` keeps its place. */
export function resolveLayout(items, fixedId) {
    const placed = items.filter((i) => i.id === fixedId);
    const rest = items.filter((i) => i.id !== fixedId).sort((a, b) => a.y - b.y || a.x - b.x);
    for (const it of rest) {
        let guard = 0;
        while (placed.some((p) => overlaps(it, p)) && guard++ < 200) {
            const hit = placed.find((p) => overlaps(it, p));
            it.y = hit.y + hit.h;
        }
        placed.push(it);
    }
}

export class AxDashboard extends Component {
    static template = "ax_dashboard_pro.Dashboard";
    static components = { AxItem };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.grid = useRef("grid");
        this.root = useRef("root");
        this.state = useState({
            ctx: { presets: [], can_build: false, is_manager: false, ai_enabled: false },
            dashboards: [],
            dash: null,
            loading: true,
            preset: "this_month",
            dateFrom: "",
            dateTo: "",
            fieldFilters: {},
            filterOptions: {},
            hideValues: false,
            edit: false,
            tv: false,
            reloadKey: 0,
            layout: [],
            panel: null,
            comments: [],
            newComment: "",
            bookmarkName: "",
            menu: null,
            newName: "",
        });
        this.timer = null;
        this.tvTimer = null;
        onWillStart(async () => {
            this.state.ctx = await this.orm.call("ax.dashboard", "user_context", []);
            await this.loadList();
            const wanted = (this.props.action && this.props.action.params && this.props.action.params.dashboard_id)
                || (this.props.action && this.props.action.context && this.props.action.context.dashboard_id);
            const first = this.state.dashboards.find((d) => d.id === wanted) || this.state.dashboards[0];
            if (first) {
                await this.openDashboard(first.id);
            }
            this.state.loading = false;
        });
        onWillUnmount(() => {
            this.stopTimers();
            document.removeEventListener("pointermove", this._move);
            document.removeEventListener("pointerup", this._up);
        });
        this._move = (ev) => this.onPointerMove(ev);
        this._up = () => this.onPointerUp();
    }

    // ------------------------------------------------------------ loading
    async loadList() {
        this.state.dashboards = await this.orm.call("ax.dashboard", "list_dashboards", []);
    }

    async openDashboard(id) {
        this.state.menu = null;
        this.state.panel = null;
        const data = await this.orm.call("ax.dashboard", "load_dashboard", [[id]]);
        this.state.dash = data;
        this.state.preset = data.default_date_preset || "this_month";
        this.state.hideValues = !!(data.prefs && data.prefs.hide_values);
        this.state.fieldFilters = {};
        this.state.filterOptions = {};
        this.state.layout = data.items.map((i) => ({ id: i.id, x: i.x, y: i.y, w: i.w, h: i.h }));
        this.state.edit = false;
        this.state.reloadKey++;
        this.setupTimers();
        for (const f of data.filters) {
            this.loadOptions(f);
        }
        const def = data.prefs && data.prefs.default_bookmark;
        const bm = def && data.bookmarks.find((b) => b.id === def);
        if (bm) {
            this.applyBookmark(bm);
        }
    }

    async loadOptions(filter, search = "") {
        const opts = await this.orm.call("ax.dashboard.filter", "get_options", [[filter.id], search]);
        this.state.filterOptions[filter.id] = opts;
    }

    async reload() {
        const id = this.state.dash.id;
        await this.openDashboard(id);
    }

    refreshItems() {
        this.state.reloadKey++;
    }

    // ------------------------------------------------------------ timers, TV mode
    stopTimers() {
        browser.clearInterval(this.timer);
        browser.clearInterval(this.tvTimer);
        this.timer = this.tvTimer = null;
    }

    setupTimers() {
        browser.clearInterval(this.timer);
        this.timer = null;
        const secs = this.state.dash && this.state.dash.refresh_seconds;
        if (secs && secs >= 10) {
            this.timer = browser.setInterval(() => this.refreshItems(), secs * 1000);
        }
    }

    async toggleTv() {
        this.state.tv = !this.state.tv;
        browser.clearInterval(this.tvTimer);
        this.tvTimer = null;
        const el = this.root.el;
        if (this.state.tv) {
            this.state.edit = false;
            if (el && el.requestFullscreen) {
                try { await el.requestFullscreen(); } catch (e) { /* not allowed, the page layout still works */ }
            }
            const secs = Math.max(5, (this.state.dash && this.state.dash.tv_seconds) || 30);
            this.tvTimer = browser.setInterval(() => this.tvNext(), secs * 1000);
        } else if (document.fullscreenElement && document.exitFullscreen) {
            document.exitFullscreen();
        }
    }

    async tvNext() {
        const list = this.state.dashboards;
        if (list.length < 2) {
            this.refreshItems();
            return;
        }
        const idx = list.findIndex((d) => d.id === this.state.dash.id);
        await this.openDashboard(list[(idx + 1) % list.length].id);
    }

    // ------------------------------------------------------------ filters
    get filters() {
        const f = { preset: this.state.preset, fields: {} };
        if (this.state.preset === "custom") {
            f.date_from = this.state.dateFrom || false;
            f.date_to = this.state.dateTo || false;
        }
        for (const [id, value] of Object.entries(this.state.fieldFilters)) {
            if (value !== "" && value !== null && value !== undefined) {
                f.fields[id] = value;
            }
        }
        return f;
    }

    onPreset(ev) {
        this.state.preset = ev.target.value;
        if (this.state.preset !== "custom") {
            this.persistPref({ date_preset: this.state.preset });
        }
    }

    onFieldFilter(filter, ev) {
        const raw = ev.target.value;
        const opt = (this.state.filterOptions[filter.id] || []).find((o) => String(o.id) === raw);
        this.state.fieldFilters[filter.id] = raw === "" ? "" : (opt ? opt.id : raw);
    }

    clearFilters() {
        this.state.fieldFilters = {};
        this.state.preset = this.state.dash.default_date_preset || "this_month";
        this.state.dateFrom = this.state.dateTo = "";
    }

    // ------------------------------------------------------------ bookmarks and preferences
    async persistPref(vals) {
        try {
            const prefs = await this.orm.call("ax.dashboard.pref", "set_pref", [this.state.dash.id, vals]);
            this.state.dash.prefs = prefs;
        } catch (e) { /* preferences are a convenience */ }
    }

    toggleHide() {
        this.state.hideValues = !this.state.hideValues;
        this.persistPref({ hide_values: this.state.hideValues });
    }

    async setTheme(ev) {
        this.state.dash.theme = ev.target.value;
        this.persistPref({ theme: ev.target.value });
    }

    async saveBookmark() {
        const name = this.state.bookmarkName.trim();
        if (!name) {
            return;
        }
        await this.orm.call("ax.dashboard.bookmark", "save_bookmark", [this.state.dash.id, name, {
            preset: this.state.preset, date_from: this.state.dateFrom, date_to: this.state.dateTo, fields: this.state.fieldFilters,
        }]);
        this.state.bookmarkName = "";
        this.state.dash.bookmarks = await this.orm.call("ax.dashboard.bookmark", "list_for", [this.state.dash.id]);
    }

    applyBookmark(bm) {
        const f = bm.filters || {};
        this.state.preset = f.preset || "this_month";
        this.state.dateFrom = f.date_from || "";
        this.state.dateTo = f.date_to || "";
        this.state.fieldFilters = Object.assign({}, f.fields || {});
        this.state.menu = null;
    }

    async makeDefaultBookmark(bm) {
        await this.persistPref({ default_bookmark: bm.id });
        this.notification.add("This view will open by default.", { type: "success" });
    }

    async removeBookmark(bm) {
        await this.orm.unlink("ax.dashboard.bookmark", [bm.id]);
        this.state.dash.bookmarks = this.state.dash.bookmarks.filter((b) => b.id !== bm.id);
    }

    // ------------------------------------------------------------ layout editing
    posOf(item) {
        return this.state.layout.find((l) => l.id === item.id) || item;
    }

    itemStyle(item) {
        const p = this.posOf(item);
        return `grid-column: ${p.x + 1} / span ${p.w}; grid-row: ${p.y + 1} / span ${p.h};`;
    }

    get gridRows() {
        return Math.max(4, ...this.state.layout.map((l) => l.y + l.h)) + (this.state.edit ? 2 : 0);
    }

    startEdit() {
        this.state.edit = true;
    }

    startDrag(item, ev, mode) {
        if (!this.state.edit || ev.button) {
            return;
        }
        ev.preventDefault();
        const rect = this.grid.el.getBoundingClientRect();
        const pos = this.posOf(item);
        this.drag = {
            id: item.id, mode, rect,
            colW: (rect.width + GAP) / 12, rowH: ROW_H + GAP,
            startX: ev.clientX, startY: ev.clientY, orig: { x: pos.x, y: pos.y, w: pos.w, h: pos.h },
        };
        document.addEventListener("pointermove", this._move);
        document.addEventListener("pointerup", this._up);
    }

    onPointerMove(ev) {
        const d = this.drag;
        if (!d) {
            return;
        }
        const dx = Math.round((ev.clientX - d.startX) / d.colW);
        const dy = Math.round((ev.clientY - d.startY) / d.rowH);
        const cur = this.state.layout.find((l) => l.id === d.id);
        if (d.mode === "move") {
            cur.x = Math.max(0, Math.min(12 - cur.w, d.orig.x + dx));
            cur.y = Math.max(0, d.orig.y + dy);
        } else {
            cur.w = Math.max(1, Math.min(12 - cur.x, d.orig.w + dx));
            cur.h = Math.max(1, d.orig.h + dy);
        }
        resolveLayout(this.state.layout, d.id);
    }

    onPointerUp() {
        document.removeEventListener("pointermove", this._move);
        document.removeEventListener("pointerup", this._up);
        this.drag = null;
        this.state.reloadKey += 0;
    }

    async saveLayout() {
        const shared = this.state.dash.can_edit;
        await this.orm.call("ax.dashboard", "save_layout", [[this.state.dash.id], this.state.layout, !shared]);
        this.state.edit = false;
        this.notification.add(shared ? "Layout saved for everyone." : "Layout saved for you.", { type: "success" });
        // chart sizes changed, draw them again
        this.state.reloadKey++;
    }

    async cancelEdit() {
        await this.reload();
    }

    async resetMyLayout() {
        await this.persistPref({ layout: {} });
        await this.reload();
    }

    // ------------------------------------------------------------ dashboards and items
    async createDashboard() {
        const name = this.state.newName.trim();
        if (!name) {
            return;
        }
        const [id] = await this.orm.create("ax.dashboard", [{ name }]);
        this.state.newName = "";
        await this.loadList();
        await this.openDashboard(id);
        this.state.menu = null;
    }

    async onSelect(ev) {
        await this.openDashboard(parseInt(ev.target.value, 10));
    }

    async addItem() {
        this.state.menu = null;
        await this.orm.call("ax.dashboard", "action_add_item", [[this.state.dash.id]]).then((act) => this.action.doAction(act));
    }

    async duplicate() {
        this.state.menu = null;
        const act = await this.orm.call("ax.dashboard", "action_duplicate", [[this.state.dash.id]]);
        await this.loadList();
        if (act && act.params && act.params.dashboard_id) {
            await this.openDashboard(act.params.dashboard_id);
        } else if (act) {
            this.action.doAction(act);
        }
    }

    async saveAsTemplate() {
        this.state.menu = null;
        const act = await this.orm.call("ax.dashboard", "action_save_as_template", [[this.state.dash.id]]);
        if (act) {
            this.action.doAction(act);
        }
    }

    openSettings() {
        this.state.menu = null;
        this.action.doAction({ type: "ir.actions.act_window", res_model: "ax.dashboard", res_id: this.state.dash.id, views: [[false, "form"]] });
    }

    openTemplates() {
        this.state.menu = null;
        this.action.doAction("ax_dashboard_pro.action_ax_dashboard_template");
    }

    openImport() {
        this.state.menu = null;
        this.action.doAction("ax_dashboard_pro.action_ax_dashboard_import", { onClose: () => this.afterWizard() });
    }

    openAI() {
        this.state.menu = null;
        this.action.doAction("ax_dashboard_pro.action_ax_dashboard_ai", { onClose: () => this.afterWizard() });
    }

    async afterWizard() {
        await this.loadList();
        if (this.state.dash) {
            await this.reload();
        }
    }

    async archive() {
        this.state.menu = null;
        if (!window.confirm("Archive this dashboard? You can restore it from the list view.")) {
            return;
        }
        await this.orm.write("ax.dashboard", [this.state.dash.id], { active: false });
        await this.loadList();
        this.state.dash = null;
        if (this.state.dashboards.length) {
            await this.openDashboard(this.state.dashboards[0].id);
        }
    }

    async exportJson() {
        this.state.menu = null;
        const text = await this.orm.call("ax.dashboard", "export_json", [[this.state.dash.id]]);
        const blob = new Blob([text], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `${this.state.dash.name}.json`;
        a.click();
        URL.revokeObjectURL(a.href);
    }

    exportAll(fmt) {
        this.state.menu = null;
        const q = new URLSearchParams({ filters: JSON.stringify(this.filters) });
        browser.location.href = `/ax_dashboard/dashboard/${this.state.dash.id}/${fmt}?${q.toString()}`;
    }

    noop() {}

    toggleMenu(name, ev) {
        ev.stopPropagation();
        this.state.menu = this.state.menu === name ? null : name;
    }

    closeMenus() {
        this.state.menu = null;
    }

    // ------------------------------------------------------------ comments
    async togglePanel(name) {
        this.state.menu = null;
        if (this.state.panel === name) {
            this.state.panel = null;
            return;
        }
        this.state.panel = name;
        if (name === "comments") {
            await this.loadComments();
        }
    }

    async loadComments() {
        this.state.comments = await this.orm.call("ax.dashboard.comment", "list_for", [this.state.dash.id]);
    }

    async postComment() {
        const body = this.state.newComment.trim();
        if (!body) {
            return;
        }
        await this.orm.call("ax.dashboard.comment", "post", [this.state.dash.id, body]);
        this.state.newComment = "";
        await this.loadComments();
        this.state.dash.comment_count = this.state.comments.length;
    }

    async openVersions() {
        this.state.menu = null;
        const act = await this.orm.call("ax.dashboard", "action_view_versions", [[this.state.dash.id]]);
        this.action.doAction(act);
    }

    get themeClass() {
        return "ax-theme-" + ((this.state.dash && this.state.dash.theme) || "navy");
    }

    get themes() {
        return [["navy", "Navy"], ["ocean", "Ocean"], ["slate", "Slate"], ["midnight", "Midnight"], ["emerald", "Emerald"], ["sunset", "Sunset"], ["light", "Light"]];
    }

    trackItem(item) {
        return item.id;
    }

    get visibleItems() {
        const dash = this.state.dash;
        if (!dash) {
            return [];
        }
        if (this.state.edit) {
            return dash.items;
        }
        // reading order (phones show one column) follows the layout
        const pos = (i) => this.posOf(i);
        return [...dash.items].sort((a, b) => pos(a).y - pos(b).y || pos(a).x - pos(b).x);
    }
}

registry.category("actions").add("ax_dashboard_pro.client", AxDashboard);
