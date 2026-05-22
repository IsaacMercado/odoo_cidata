/** @odoo-module **/

import { Component, useState, useRef, onMounted, onPatched } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

export class ShellTab extends Component {
    static template = "odoo_shell_terminal.ShellTab";

    setup() {
        this.state = useState({
            history: [],
            input: "",
            cmdHistory: [],
            historyIdx: -1,
            loading: false,
        });
        this.outputRef = useRef("output");
        this.inputRef = useRef("input");
        this._scrollPending = false;

        onMounted(() => {
            this.inputRef.el?.focus();
        });

        onPatched(() => {
            if (this._scrollPending) {
                this._scrollPending = false;
                if (this.outputRef.el) {
                    this.outputRef.el.scrollTop = this.outputRef.el.scrollHeight;
                }
            }
        });
    }

    onTabMouseDown(ev) {
        // Prevent any click inside the tab (output, buttons, etc.) from
        // stealing focus away from the textarea, unless the click IS on the textarea.
        if (ev.target !== this.inputRef.el) {
            ev.preventDefault();
        }
    }

    onInputChange(ev) {
        this.state.input = ev.target.value;
    }

    onKeyDown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.execute();
        } else if (ev.key === "ArrowUp") {
            ev.preventDefault();
            this._navigateHistory(1);
        } else if (ev.key === "ArrowDown") {
            ev.preventDefault();
            this._navigateHistory(-1);
        }
    }

    _navigateHistory(direction) {
        const len = this.state.cmdHistory.length;
        if (!len) return;
        this.state.historyIdx = Math.max(
            -1,
            Math.min(len - 1, this.state.historyIdx + direction)
        );
        if (this.state.historyIdx === -1) {
            this.state.input = "";
        } else {
            this.state.input = this.state.cmdHistory[len - 1 - this.state.historyIdx];
        }
        if (this.inputRef.el) {
            this.inputRef.el.value = this.state.input;
        }
    }

    async execute() {
        const code = this.state.input.trim();
        if (!code || this.state.loading) return;

        this.state.loading = true;
        this.state.cmdHistory.push(code);
        this.state.historyIdx = -1;
        this.state.input = "";
        if (this.inputRef.el) this.inputRef.el.value = "";

        let entry = { input: code, output: "", result: "", error: null };
        try {
            const res = await rpc("/odoo_shell_terminal/execute", { code });
            entry.output = res.output || "";
            entry.result = res.result || "";
            entry.error = res.error || null;
        } catch (e) {
            entry.error = String(e);
        } finally {
            this.state.loading = false;
        }

        this.state.history.push(entry);
        this._scrollToBottom();
    }

    clearHistory() {
        this.state.history = [];
    }

    async resetNamespace() {
        await rpc("/odoo_shell_terminal/reset_namespace", {});
        this.state.history = [];
        this.state.cmdHistory = [];
        this.state.historyIdx = -1;
        this.inputRef.el?.focus();
    }

    _scrollToBottom() {
        this._scrollPending = true;
    }
}
