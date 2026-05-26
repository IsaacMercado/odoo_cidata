import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class BaseSynchro(models.TransientModel):
    _name = "base.synchro"
    _description = "Base Synchronization"

    server_url = fields.Many2one(
        "base.synchro.server",
        "Server URL",
        required=True,
    )
    user_id = fields.Many2one(
        "res.users",
        "Send Result To",
        default=lambda self: self.env.user,
    )

    def upload_download(self):
        self.ensure_one()
        engine = self.env["base.synchro.engine"]
        result = engine.run_sync(self.server_url)
        _logger.info(
            "Sync result: sent=%d received=%d errors=%d",
            result["sent"], result["received"], result["errors"],
        )
        return {}

    def upload_download_multi_thread(self):
        self.upload_download()
        id2 = self.env.ref("base_synchro.view_base_synchro_finish", False)
        if not id2:
            return {}
        return {
            "binding_view_types": "form",
            "view_mode": "form",
            "res_model": "base.synchro",
            "views": [(id2.id, "form")],
            "view_id": False,
            "type": "ir.actions.act_window",
            "target": "new",
        }
