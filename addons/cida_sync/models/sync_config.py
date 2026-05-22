import logging
import xmlrpc.client
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class CidaSyncConfig(models.Model):
    """
    Configuración de conexión al nodo remoto.

    Define la URL, credenciales y parámetros de sincronización
    con la otra sede. Solo debe existir UN registro activo.
    """
    _name = 'cida.sync.config'
    _description = 'Configuración de Sincronización CIDA'
    _rec_name = 'name'

    name = fields.Char(
        string='Nombre de la Sede Remota',
        required=True,
        help='Nombre descriptivo (ej: "Sede Turística")',
    )
    node_role = fields.Selection(
        [('central', 'Sede Central'), ('turistica', 'Sede Turística')],
        string='Este Nodo Es',
        required=True,
        default='central',
        help='Rol de ESTA sede (no la remota)',
    )
    remote_url = fields.Char(
        string='URL Remota',
        required=True,
        help='URL de la otra sede (ej: http://odoo-turistica-001:8069)',
    )
    remote_db = fields.Char(
        string='Base de Datos Remota',
        required=True,
        default='odoo',
    )
    remote_user = fields.Char(
        string='Usuario Remoto',
        required=True,
        default='admin',
    )
    remote_password = fields.Char(
        string='Contraseña Remota',
        required=True,
    )
    active = fields.Boolean(default=True)
    state = fields.Selection(
        [('draft', 'Borrador'), ('connected', 'Conectado'), ('error', 'Error')],
        string='Estado',
        default='draft',
        readonly=True,
    )
    last_sync_date = fields.Datetime(
        string='Última Sincronización',
        readonly=True,
    )
    sync_interval_minutes = fields.Integer(
        string='Intervalo de Sync (minutos)',
        default=15,
        help='Cada cuántos minutos se ejecuta la sincronización automática',
    )
    conflict_resolution = fields.Selection(
        [('central_wins', 'Sede Central Gana'),
         ('newest_wins', 'El Más Reciente Gana'),
         ('manual', 'Resolución Manual')],
        string='Resolución de Conflictos',
        default='central_wins',
        required=True,
    )
    rule_ids = fields.One2many(
        'cida.sync.rule', 'config_id',
        string='Reglas de Sincronización',
    )
    log_ids = fields.One2many(
        'cida.sync.log', 'config_id',
        string='Historial de Sync',
    )
    last_error = fields.Text(
        string='Último Error',
        readonly=True,
    )

    # --- Estadísticas ---
    total_synced = fields.Integer(
        string='Total Sincronizados',
        compute='_compute_stats',
    )
    total_errors = fields.Integer(
        string='Total Errores',
        compute='_compute_stats',
    )
    total_pending = fields.Integer(
        string='Pendientes',
        compute='_compute_stats',
    )

    @api.depends('log_ids')
    def _compute_stats(self):
        for rec in self:
            logs = rec.log_ids
            rec.total_synced = len(logs.filtered(lambda l: l.state == 'done'))
            rec.total_errors = len(logs.filtered(lambda l: l.state == 'error'))
            rec.total_pending = len(logs.filtered(lambda l: l.state == 'pending'))

    def _get_xmlrpc_connection(self):
        """
        Establece conexión XML-RPC con el nodo remoto.

        Returns:
            tuple: (uid, models_proxy) para hacer operaciones
        """
        self.ensure_one()
        try:
            common = xmlrpc.client.ServerProxy(
                f'{self.remote_url}/xmlrpc/2/common',
                allow_none=True,
            )
            uid = common.authenticate(
                self.remote_db,
                self.remote_user,
                self.remote_password,
                {},
            )
            if not uid:
                raise UserError('Autenticación fallida con el nodo remoto')

            models_proxy = xmlrpc.client.ServerProxy(
                f'{self.remote_url}/xmlrpc/2/object',
                allow_none=True,
            )
            return uid, models_proxy

        except xmlrpc.client.Fault as e:
            raise UserError(f'Error XML-RPC: {e.faultString}')
        except ConnectionRefusedError:
            raise UserError(f'No se pudo conectar a {self.remote_url}')
        except Exception as e:
            raise UserError(f'Error de conexión: {str(e)}')

    def action_test_connection(self):
        """Botón: Probar conexión con el nodo remoto."""
        self.ensure_one()
        try:
            uid, _ = self._get_xmlrpc_connection()
            self.write({
                'state': 'connected',
                'last_error': False,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '¡Conexión exitosa!',
                    'message': f'Conectado como usuario ID {uid}',
                    'type': 'success',
                    'sticky': False,
                },
            }
        except Exception as e:
            self.write({
                'state': 'error',
                'last_error': str(e),
            })
            raise

    def action_sync_now(self):
        """Botón: Ejecutar sincronización manual."""
        self.ensure_one()
        engine = self.env['cida.sync.engine']
        result = engine.run_sync(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sincronización completada',
                'message': f'Enviados: {result["pushed"]}, '
                           f'Recibidos: {result["pulled"]}, '
                           f'Errores: {result["errors"]}',
                'type': 'success' if result['errors'] == 0 else 'warning',
                'sticky': True,
            },
        }

    def action_view_logs(self):
        """Botón: Ver historial de sincronización."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Historial de Sync',
            'res_model': 'cida.sync.log',
            'view_mode': 'tree,form',
            'domain': [('config_id', '=', self.id)],
            'context': {'default_config_id': self.id},
        }
