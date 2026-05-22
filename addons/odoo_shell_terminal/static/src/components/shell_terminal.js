/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { ShellTab } from "./shell_tab";
import { LogViewerTab } from "./log_viewer_tab";

export class ShellTerminal extends Component {
    static template = "odoo_shell_terminal.ShellTerminal";
    static components = { ShellTab, LogViewerTab };
    static props = {
        onClose: { type: Function },
        onMinimize: { type: Function },
        minimized: { type: Boolean },
    };

    setup() {
        this.state = useState({
            activeTab: "shell",
            x: 80,
            y: 80,
            width: 760,
            height: 480,
        });

        this.panelRef = useRef("panel");
        this._drag = null;
        this._resize = null;

        onMounted(() => {
            this._onMouseMove = this._onMouseMove.bind(this);
            this._onMouseUp = this._onMouseUp.bind(this);
            document.addEventListener("mousemove", this._onMouseMove);
            document.addEventListener("mouseup", this._onMouseUp);
        });

        onWillUnmount(() => {
            document.removeEventListener("mousemove", this._onMouseMove);
            document.removeEventListener("mouseup", this._onMouseUp);
        });
    }

    get panelStyle() {
        return [
            `left:${this.state.x}px`,
            `top:${this.state.y}px`,
            `width:${this.state.width}px`,
            `height:${this.state.height}px`,
        ].join(";");
    }

    onMouseDownHeader(ev) {
        if (ev.target.closest("button")) return;
        this._drag = {
            startX: ev.clientX - this.state.x,
            startY: ev.clientY - this.state.y,
        };
        ev.preventDefault();
    }

    onMouseDownResize(ev) {
        this._resize = {
            startX: ev.clientX,
            startY: ev.clientY,
            startW: this.state.width,
            startH: this.state.height,
        };
        ev.preventDefault();
        ev.stopPropagation();
    }

    _onMouseMove(ev) {
        if (this._drag) {
            this.state.x = ev.clientX - this._drag.startX;
            this.state.y = ev.clientY - this._drag.startY;
        }
        if (this._resize) {
            const dx = ev.clientX - this._resize.startX;
            const dy = ev.clientY - this._resize.startY;
            this.state.width = Math.max(400, this._resize.startW + dx);
            this.state.height = Math.max(250, this._resize.startH + dy);
        }
    }

    _onMouseUp() {
        this._drag = null;
        this._resize = null;
    }

    setTab(tab) {
        this.state.activeTab = tab;
    }
}
