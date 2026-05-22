from odoo import models, fields


class CidaSyncLog(models.Model):
    """
    Log de sincronización — auditoría de cada operación.

    Registra cada intento de sincronización con su resultado,
    datos enviados/recibidos, y errores si los hubo.
    """
    _name = 'cida.sync.log'
    _description = 'Log de Sincronización'
    _order = 'create_date desc'

    config_id = fields.Many2one(
        'cida.sync.config',
        string='Configuración',
        required=True,
        ondelete='cascade',
    )
    rule_id = fields.Many2one(
        'cida.sync.rule',
        string='Regla',
        ondelete='set null',
    )
    model_name = fields.Char(string='Modelo')
    operation = fields.Selection(
        [('push', 'Envío (→)'),
         ('pull', 'Recepción (←)'),
         ('conflict', 'Conflicto'),
         ('full_sync', 'Sync Completo')],
        string='Operación',
    )
    state = fields.Selection(
        [('pending', 'Pendiente'),
         ('running', 'En Proceso'),
         ('done', 'Completado'),
         ('error', 'Error'),
         ('conflict', 'Conflicto')],
        string='Estado',
        default='pending',
    )
    records_sent = fields.Integer(string='Registros Enviados')
    records_received = fields.Integer(string='Registros Recibidos')
    records_created = fields.Integer(string='Creados')
    records_updated = fields.Integer(string='Actualizados')
    records_skipped = fields.Integer(string='Omitidos')
    records_errored = fields.Integer(string='Con Error')

    duration_seconds = fields.Float(string='Duración (seg)')
    error_message = fields.Text(string='Mensaje de Error')
    detail = fields.Text(
        string='Detalle',
        help='Detalle técnico de la operación (JSON)',
    )

    # Para tracking de registros individuales
    res_model = fields.Char(string='Modelo del Recurso')
    res_id = fields.Integer(string='ID del Recurso')
    sync_uuid = fields.Char(string='UUID de Sync')
