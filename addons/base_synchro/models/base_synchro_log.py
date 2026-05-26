from odoo import models, fields


class BaseSynchroLog(models.Model):
    _name = "base.synchro.log"
    _description = "Sync Log"
    _order = "create_date desc"

    server_id = fields.Many2one(
        "base.synchro.server",
        string="Servidor",
        required=True,
        ondelete="cascade",
    )
    rule_id = fields.Many2one(
        "base.synchro.obj",
        string="Regla",
        ondelete="set null",
    )
    model_name = fields.Char(string="Modelo")
    operation = fields.Selection(
        [("push", "Envío"), ("pull", "Recepción"), ("full_sync", "Sync Completo")],
        string="Operación",
    )
    state = fields.Selection(
        [("running", "En Proceso"), ("done", "Completado"), ("error", "Error")],
        string="Estado",
        default="running",
    )
    records_sent = fields.Integer(string="Enviados")
    records_received = fields.Integer(string="Recibidos")
    records_created = fields.Integer(string="Creados")
    records_updated = fields.Integer(string="Actualizados")
    records_skipped = fields.Integer(string="Omitidos")
    records_errored = fields.Integer(string="Con Error")
    duration_seconds = fields.Float(string="Duración (seg)")
    error_message = fields.Text(string="Mensaje de Error")
    detail = fields.Text(string="Detalle Técnico")
