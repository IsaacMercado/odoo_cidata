from odoo import api, models
from odoo.exceptions import ValidationError


class ResGroups(models.Model):
    _inherit = "res.groups"

    @api.constrains("user_ids")
    def _check_shell_terminal_requires_system(self):
        """When users are added to the Shell Terminal group, ensure every one of
        them already belongs to Technical Administrator (group_system).

        This fires whenever user_ids on this group record changes — which covers
        the direct group form, the user form in Settings, and programmatic writes.
        """
        shell_group = self.env.ref(
            "odoo_shell_terminal.group_shell_terminal_user", raise_if_not_found=False
        )
        if not shell_group:
            return
        system_group = self.env.ref("base.group_system", raise_if_not_found=False)
        if not system_group:
            return

        for group in self:
            if group.id != shell_group.id:
                continue
            bad_users = group.user_ids.filtered(
                lambda u: system_group not in u.group_ids
            )
            if bad_users:
                names = ", ".join(bad_users.mapped("name"))
                raise ValidationError(
                    f"Cannot add to 'Odoo Shell User': the following user(s) are not "
                    f"Technical Administrators — {names}. "
                    "Grant Technical Administrator access first."
                )
