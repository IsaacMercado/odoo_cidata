/** @odoo-module **/

import { Component, useState, onWillStart, useEnv } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { rpc } from "@web/core/network/rpc";
import { ShellTerminal } from "./shell_terminal";

export class ShellSystray extends Component {
    static template = "odoo_shell_terminal.ShellSystray";
    static components = { ShellTerminal };

    setup() {
        this.env = useEnv();
        this.state = useState({ visible: false, terminalOpen: false, minimized: false });
        onWillStart(async () => {
            const hasGroup = await user.hasGroup(
                "odoo_shell_terminal.group_shell_terminal_user"
            );
            // Only show the systray icon when BOTH conditions are true:
            //   1. The user belongs to the Shell Terminal group (implies group_system)
            //   2. Odoo is running in debug mode (?debug=1 or ?debug=assets)
            this.state.visible = hasGroup && !!this.env.debug;
        });
    }

    onSystrayClick() {
        if (!this.state.terminalOpen) {
            this.state.terminalOpen = true;
            this.state.minimized = false;
        } else if (this.state.minimized) {
            this.state.minimized = false;
        } else {
            this.state.minimized = true;
        }
    }

    async closeTerminal() {
        try {
            await Promise.all([
                rpc("/odoo_shell_terminal/reset_namespace", {}),
                rpc("/odoo_shell_terminal/clear_log_buffer", {}),
            ]);
        } catch (_) {}
        this.state.terminalOpen = false;
        this.state.minimized = false;
    }
}

registry.category("systray").add(
    "odoo_shell_terminal.shell_systray",
    { Component: ShellSystray },
    { sequence: 5 }
);
