from odoo import models, fields, api
from odoo.exceptions import ValidationError


class CidaSyncRule(models.Model):
    """
    Regla de sincronización — define QUÉ se sincroniza.

    Cada regla mapea un modelo de Odoo y opcionalmente filtra
    qué campos y qué registros se sincronizan.

    Ejemplo:
        Modelo: product.template
        Campos: name, list_price, categ_id, type
        Dominio: [('active', '=', True)]
        Dirección: Bidireccional
    """
    _name = 'cida.sync.rule'
    _description = 'Regla de Sincronización'
    _order = 'sequence, id'

    config_id = fields.Many2one(
        'cida.sync.config',
        string='Configuración',
        required=True,
        ondelete='cascade',
    )
    name = fields.Char(
        string='Nombre',
        compute='_compute_name',
        store=True,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    model_id = fields.Many2one(
        'ir.model',
        string='Modelo',
        required=True,
        ondelete='cascade',
        domain=[('transient', '=', False)],
        help='Modelo de Odoo a sincronizar (ej: product.template)',
    )
    model_name = fields.Char(
        related='model_id.model',
        string='Nombre Técnico',
        store=True,
    )

    direction = fields.Selection(
        [('push', 'Solo Enviar (→ remoto)'),
         ('pull', 'Solo Recibir (← remoto)'),
         ('both', 'Bidireccional (↔)')],
        string='Dirección',
        default='both',
        required=True,
    )

    field_ids = fields.Many2many(
        'ir.model.fields',
        string='Campos a Sincronizar',
        domain="[('model_id', '=', model_id), "
               "('store', '=', True), "
               "('ttype', 'not in', ['one2many', 'binary'])]",
        help='Dejar vacío para sincronizar todos los campos almacenados. '
             'Se excluyen automáticamente: one2many, binary, campos internos.',
    )

    domain = fields.Char(
        string='Filtro (Dominio)',
        default='[]',
        help='Dominio de Odoo para filtrar qué registros sincronizar. '
             'Ej: [("active", "=", True)]',
    )

    sync_on_create = fields.Boolean(
        string='Sync al Crear',
        default=True,
        help='Sincronizar automáticamente cuando se crea un registro',
    )
    sync_on_write = fields.Boolean(
        string='Sync al Modificar',
        default=True,
        help='Sincronizar automáticamente cuando se modifica un registro',
    )
    batch_size = fields.Integer(
        string='Tamaño de Lote',
        default=100,
        help='Cantidad de registros por lote de sincronización',
    )

    # Campo identificador único para matching entre instancias
    match_field = fields.Selection(
        [('sync_uuid', 'UUID de Sync (automático)'),
         ('name', 'Nombre'),
         ('default_code', 'Referencia Interna'),
         ('barcode', 'Código de Barras'),
         ('vat', 'NIF/RIF'),
         ('email', 'Email')],
        string='Campo de Matching',
        default='sync_uuid',
        required=True,
        help='Campo usado para identificar el mismo registro en ambas sedes. '
             'UUID es el más seguro (sin ambigüedades).',
    )

    last_sync_date = fields.Datetime(
        string='Última Sync de esta Regla',
        readonly=True,
    )

    @api.depends('model_id')
    def _compute_name(self):
        for rule in self:
            if rule.model_id:
                rule.name = f'Sync: {rule.model_id.name}'
            else:
                rule.name = 'Nueva Regla'

    def get_sync_fields(self):
        """
        Retorna la lista de campos a sincronizar.

        Si field_ids está vacío, retorna todos los campos
        almacenados excepto los internos y los one2many/binary.
        """
        self.ensure_one()
        EXCLUDED_FIELDS = {
            'id', 'create_uid', 'create_date', 'write_uid',
            '__last_update', 'display_name',
            'message_ids', 'message_follower_ids',
            'message_main_attachment_id', 'website_message_ids',
            'activity_ids', 'activity_state', 'activity_summary',
            'activity_type_id', 'activity_user_id',
        }

        if self.field_ids:
            return [f.name for f in self.field_ids
                    if f.name not in EXCLUDED_FIELDS]

        # Todos los campos almacenados excepto excluidos
        Model = self.env[self.model_name]
        fields_info = Model.fields_get()
        sync_fields = []
        for fname, finfo in fields_info.items():
            if fname in EXCLUDED_FIELDS:
                continue
            if not finfo.get('store', False):
                continue
            if finfo.get('type') in ('one2many', 'binary'):
                continue
            if finfo.get('readonly') and fname != 'write_date':
                continue
            sync_fields.append(fname)
        return sync_fields
