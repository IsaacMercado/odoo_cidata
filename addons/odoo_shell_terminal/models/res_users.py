from odoo import api, models
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.constrains("group_ids")
    def _check_shell_terminal_requires_system(self):
        """Raise an error if a user is assigned to the Shell Terminal group
        without already belonging to the Technical Administrator group (group_system).

        This covers writes that go through res.users.group_ids directly
        (e.g. programmatic ORM writes). The companion constraint on res.groups.user_ids
        covers the Settings UI path.
        """
        shell_group = self.env.ref(
            "odoo_shell_terminal.group_shell_terminal_user", raise_if_not_found=False
        )
        system_group = self.env.ref("base.group_system", raise_if_not_found=False)
        if not shell_group or not system_group:
            return
        for user in self:
            if shell_group in user.group_ids and system_group not in user.group_ids:
                raise ValidationError(
                    f"User '{user.name}' cannot be added to 'Odoo Shell User' "
                    "because they are not a Technical Administrator (Settings > "
                    "Technical). Grant Technical Administrator access first."
                )
