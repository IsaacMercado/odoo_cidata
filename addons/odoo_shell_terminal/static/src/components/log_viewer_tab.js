/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount, onWillPatch, onPatched } from "@odoo/owl";

export class LogViewerTab extends Component {
    static template = "odoo_shell_terminal.LogViewerTab";

    setup() {
        this.state = useState({
            lines: [],
            filter: "",
            autoScroll: true,
            connected: false,
            error: null,
        });
        this.outputRef = useRef("logOutput");
        this.bottomRef = useRef("logBottom");
        this.eventSource = null;
        this._scrollPending = false;

        onMounted(() => {
            this._connect();
        });

        onWillUnmount(() => {
            this._disconnect();
        });

        // After every OWL patch, if a scroll was requested, do it now —
        // the DOM is guaranteed to be up to date at this point.
        onPatched(() => {
            if (this._scrollPending) {
                this._scrollPending = false;
                this.bottomRef.el?.scrollIntoView({ block: "end" });
            }
        });
    }

    _connect() {
        this._disconnect();
        this.state.error = null;
        this.state.connected = false;

        this.eventSource = new EventSource("/odoo_shell_terminal/log_stream");

        this.eventSource.onopen = () => {
            this.state.connected = true;
        };

        this.eventSource.onmessage = (ev) => {
            const line = ev.data;
            // Skip keepalive comments (empty data from ": keepalive" SSE comments are not delivered as messages)
            if (!line) return;
            this.state.lines.push(line);
            // Cap at 5000 lines to prevent memory growth
            if (this.state.lines.length > 5000) {
                this.state.lines.splice(0, this.state.lines.length - 5000);
            }
            if (this.state.autoScroll) {
                this._scrollToBottom();
            }
        };

        this.eventSource.onerror = () => {
            this.state.connected = false;
            // Browser will auto-reconnect; we just update state
        };
    }

    _disconnect() {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        this.state.connected = false;
    }

    get filteredLines() {
        const q = this.state.filter.toLowerCase();
        if (!q) return this.state.lines;
        return this.state.lines.filter((l) => l.toLowerCase().includes(q));
    }

    getLineClass(line) {
        const upper = line.toUpperCase();
        if (upper.includes("ERROR") || upper.includes("CRITICAL")) return "o_log_error";
        if (upper.includes("WARNING") || upper.includes("WARN")) return "o_log_warning";
        return "";
    }

    onFilterInput(ev) {
        this.state.filter = ev.target.value;
    }

    toggleAutoScroll() {
        this.state.autoScroll = !this.state.autoScroll;
        if (this.state.autoScroll) {
            this._scrollToBottom();
        }
    }

    clearLines() {
        this.state.lines = [];
    }

    _scrollToBottom() {
        // Mark that a scroll is needed; onPatched() will execute it after
        // OWL has finished updating the DOM.
        this._scrollPending = true;
    }
}
