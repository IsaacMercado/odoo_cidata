import json
import logging
import time
import uuid
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CidaSyncEngine(models.AbstractModel):
    """
    Motor de sincronización — lógica central.

    Coordina el proceso de push/pull de datos entre dos
    instancias de Odoo via XML-RPC.

    Flujo de sincronización:
    1. Leer reglas activas
    2. Para cada regla, buscar registros modificados desde
       la última sincronización
    3. PUSH: Enviar registros locales al nodo remoto
    4. PULL: Traer registros remotos al nodo local
    5. Resolver conflictos según la política configurada
    6. Registrar todo en el log
    """
    _name = 'cida.sync.engine'
    _description = 'Motor de Sincronización CIDA'

    # ----------------------------------------------------------
    # Sync UUID Management
    # ----------------------------------------------------------
    # Odoo no tiene un UUID nativo en todos los modelos.
    # Usamos ir.config_parameter para almacenar el mapeo
    # record_id <-> uuid por modelo.
    # ----------------------------------------------------------

    def _get_or_create_uuid(self, model_name, record_id):
        """
        Obtiene o genera un UUID único para un registro.

        Almacena la relación en ir.config_parameter con el formato:
            cida_sync.uuid.{model_name}.{record_id} = uuid
        """
        param_key = f'cida_sync.uuid.{model_name}.{record_id}'
        ICP = self.env['ir.config_parameter'].sudo()
        sync_uuid = ICP.get_param(param_key)
        if not sync_uuid:
            sync_uuid = str(uuid.uuid4())
            ICP.set_param(param_key, sync_uuid)
        return sync_uuid

    def _find_local_id_by_uuid(self, model_name, sync_uuid):
        """Busca el record_id local dado un UUID de sync."""
        ICP = self.env['ir.config_parameter'].sudo()
        prefix = f'cida_sync.uuid.{model_name}.'
        # Buscar parámetro con este UUID
        param = ICP.search([
            ('key', 'like', prefix),
            ('value', '=', sync_uuid),
        ], limit=1)
        if param:
            # Extraer el record_id del key
            record_id = int(param.key.replace(prefix, ''))
            # Verificar que el registro aún existe
            if self.env[model_name].browse(record_id).exists():
                return record_id
        return False

    def _find_local_id_by_field(self, model_name, match_field, match_value):
        """Busca un registro local por un campo de matching alternativo."""
        if not match_value:
            return False
        records = self.env[model_name].search([
            (match_field, '=', match_value),
        ], limit=1)
        return records.id if records else False

    # ----------------------------------------------------------
    # Serialización / Deserialización
    # ----------------------------------------------------------

    def _serialize_record(self, record, sync_fields, rule):
        """
        Serializa un registro de Odoo a diccionario para envío.

        Maneja campos Many2one, Selection, Date/Datetime, etc.
        Los Many2one se serializan con su UUID de sync para
        poder resolver la referencia en la otra sede.
        """
        data = {}
        fields_info = record.fields_get(sync_fields)

        for fname in sync_fields:
            finfo = fields_info.get(fname, {})
            value = record[fname]

            if finfo.get('type') == 'many2one':
                if value:
                    # Serializar M2O como {model, uuid, display_name}
                    rel_model = finfo.get('relation')
                    rel_uuid = self._get_or_create_uuid(rel_model, value.id)
                    data[fname] = {
                        '_type': 'many2one',
                        'model': rel_model,
                        'uuid': rel_uuid,
                        'display_name': value.display_name,
                        # Fallback: nombre para matching manual
                        'name': getattr(value, 'name', value.display_name),
                    }
                else:
                    data[fname] = False

            elif finfo.get('type') == 'many2many':
                if value:
                    rel_model = finfo.get('relation')
                    uuids = []
                    for rel_rec in value:
                        rel_uuid = self._get_or_create_uuid(rel_model, rel_rec.id)
                        uuids.append({
                            'uuid': rel_uuid,
                            'model': rel_model,
                            'name': getattr(rel_rec, 'name', ''),
                        })
                    data[fname] = {'_type': 'many2many', 'records': uuids}
                else:
                    data[fname] = {'_type': 'many2many', 'records': []}

            elif finfo.get('type') in ('date', 'datetime'):
                data[fname] = str(value) if value else False

            else:
                data[fname] = value

        # Agregar metadata de sync
        data['_sync_uuid'] = self._get_or_create_uuid(
            rule.model_name, record.id
        )
        data['_sync_model'] = rule.model_name
        data['_sync_write_date'] = str(record.write_date)

        return data

    def _deserialize_and_apply(self, data, rule):
        """
        Deserializa datos recibidos y crea/actualiza el registro local.

        Returns:
            tuple: (action, record_id) donde action es
                   'created', 'updated', 'skipped', 'conflict'
        """
        model_name = data.get('_sync_model', rule.model_name)
        sync_uuid = data.get('_sync_uuid')
        remote_write_date = data.get('_sync_write_date')

        if not sync_uuid:
            _logger.warning('Registro sin UUID de sync, omitiendo')
            return 'skipped', False

        Model = self.env[model_name]

        # 1. Buscar registro local por UUID
        local_id = self._find_local_id_by_uuid(model_name, sync_uuid)

        # 2. Si no se encuentra por UUID, buscar por campo alternativo
        if not local_id and rule.match_field != 'sync_uuid':
            match_value = data.get(rule.match_field)
            if match_value:
                local_id = self._find_local_id_by_field(
                    model_name, rule.match_field, match_value
                )
                if local_id:
                    # Registrar el UUID para este registro existente
                    param_key = f'cida_sync.uuid.{model_name}.{local_id}'
                    self.env['ir.config_parameter'].sudo().set_param(
                        param_key, sync_uuid
                    )

        # 3. Preparar valores limpiando metadata de sync
        vals = {}
        fields_info = Model.fields_get()
        for fname, value in data.items():
            if fname.startswith('_sync_'):
                continue
            if fname not in fields_info:
                continue

            finfo = fields_info[fname]

            # Resolver Many2one
            if isinstance(value, dict) and value.get('_type') == 'many2one':
                rel_model = value.get('model')
                rel_uuid = value.get('uuid')
                rel_id = self._find_local_id_by_uuid(rel_model, rel_uuid)
                if not rel_id:
                    # Buscar por nombre como fallback
                    rel_name = value.get('name')
                    if rel_name:
                        rel_id = self._find_local_id_by_field(
                            rel_model, 'name', rel_name
                        )
                vals[fname] = rel_id or False

            # Resolver Many2many
            elif isinstance(value, dict) and value.get('_type') == 'many2many':
                rel_ids = []
                for rel_data in value.get('records', []):
                    rel_id = self._find_local_id_by_uuid(
                        rel_data['model'], rel_data['uuid']
                    )
                    if not rel_id and rel_data.get('name'):
                        rel_id = self._find_local_id_by_field(
                            rel_data['model'], 'name', rel_data['name']
                        )
                    if rel_id:
                        rel_ids.append(rel_id)
                vals[fname] = [(6, 0, rel_ids)]

            else:
                # Convertir fechas de string
                if finfo.get('type') == 'date' and isinstance(value, str):
                    vals[fname] = fields.Date.from_string(value) if value else False
                elif finfo.get('type') == 'datetime' and isinstance(value, str):
                    vals[fname] = fields.Datetime.from_string(value) if value else False
                else:
                    vals[fname] = value

        # 4. Crear o actualizar
        if local_id:
            local_record = Model.browse(local_id)

            # Verificar conflictos (ambos modificados desde última sync)
            config = rule.config_id
            if remote_write_date and local_record.write_date:
                remote_dt = fields.Datetime.from_string(remote_write_date)
                if local_record.write_date > rule.last_sync_date and remote_dt > rule.last_sync_date:
                    # ¡CONFLICTO!
                    return self._resolve_conflict(
                        config, local_record, vals,
                        remote_write_date, rule
                    )

            # Sin conflicto: actualizar
            try:
                local_record.write(vals)
                return 'updated', local_id
            except Exception as e:
                _logger.error(f'Error actualizando {model_name}#{local_id}: {e}')
                return 'error', local_id
        else:
            # Crear nuevo registro
            try:
                new_record = Model.create(vals)
                # Registrar UUID del nuevo registro
                param_key = f'cida_sync.uuid.{model_name}.{new_record.id}'
                self.env['ir.config_parameter'].sudo().set_param(
                    param_key, sync_uuid
                )
                return 'created', new_record.id
            except Exception as e:
                _logger.error(f'Error creando {model_name}: {e}')
                return 'error', False

    def _resolve_conflict(self, config, local_record, remote_vals,
                          remote_write_date, rule):
        """
        Resuelve un conflicto de sincronización.

        Políticas:
        - central_wins: Si somos central, local gana. Si no, remoto gana.
        - newest_wins: El write_date más reciente gana.
        - manual: Se registra como conflicto para revisión.
        """
        resolution = config.conflict_resolution

        if resolution == 'central_wins':
            if config.node_role == 'central':
                # Somos central → nuestro registro gana, no actualizar
                _logger.info(
                    f'Conflicto resuelto: central gana (local). '
                    f'{rule.model_name}#{local_record.id}'
                )
                return 'skipped', local_record.id
            else:
                # Somos turística → el remoto (central) gana
                local_record.write(remote_vals)
                return 'updated', local_record.id

        elif resolution == 'newest_wins':
            remote_dt = fields.Datetime.from_string(remote_write_date)
            if remote_dt > local_record.write_date:
                local_record.write(remote_vals)
                return 'updated', local_record.id
            else:
                return 'skipped', local_record.id

        else:  # manual
            return 'conflict', local_record.id

    # ----------------------------------------------------------
    # Motor Principal
    # ----------------------------------------------------------

    def run_sync(self, config):
        """
        Ejecuta un ciclo completo de sincronización.

        Args:
            config: cida.sync.config record

        Returns:
            dict: {pushed, pulled, errors}
        """
        _logger.info(f'=== Inicio de sincronización: {config.name} ===')
        start_time = time.time()
        result = {'pushed': 0, 'pulled': 0, 'errors': 0}

        try:
            uid, models_proxy = config._get_xmlrpc_connection()
        except Exception as e:
            config.write({'state': 'error', 'last_error': str(e)})
            self._create_log(config, None, 'full_sync', 'error',
                             error_message=str(e))
            return result

        for rule in config.rule_ids.filtered('active'):
            try:
                rule_result = self._sync_rule(config, rule, uid, models_proxy)
                result['pushed'] += rule_result.get('pushed', 0)
                result['pulled'] += rule_result.get('pulled', 0)
                result['errors'] += rule_result.get('errors', 0)
            except Exception as e:
                _logger.exception(f'Error sincronizando regla {rule.name}')
                result['errors'] += 1
                self._create_log(config, rule, 'full_sync', 'error',
                                 error_message=str(e))

        # Actualizar estado
        elapsed = time.time() - start_time
        config.write({
            'state': 'connected',
            'last_sync_date': fields.Datetime.now(),
            'last_error': False,
        })

        self._create_log(
            config, None, 'full_sync', 'done',
            records_sent=result['pushed'],
            records_received=result['pulled'],
            records_errored=result['errors'],
            duration_seconds=elapsed,
        )

        _logger.info(
            f'=== Sync completado en {elapsed:.1f}s: '
            f'push={result["pushed"]}, pull={result["pulled"]}, '
            f'errors={result["errors"]} ==='
        )
        return result

    def _sync_rule(self, config, rule, uid, models_proxy):
        """Sincroniza una regla individual."""
        result = {'pushed': 0, 'pulled': 0, 'errors': 0}
        model_name = rule.model_name
        sync_fields = rule.get_sync_fields()

        if not sync_fields:
            _logger.warning(f'Regla {rule.name}: sin campos para sincronizar')
            return result

        _logger.info(f'Sincronizando: {model_name} ({rule.direction})')

        # --- PUSH: Enviar datos locales al remoto ---
        if rule.direction in ('push', 'both'):
            push_result = self._push_records(
                config, rule, uid, models_proxy, sync_fields
            )
            result['pushed'] = push_result.get('sent', 0)
            result['errors'] += push_result.get('errors', 0)

        # --- PULL: Traer datos remotos al local ---
        if rule.direction in ('pull', 'both'):
            pull_result = self._pull_records(
                config, rule, uid, models_proxy, sync_fields
            )
            result['pulled'] = pull_result.get('received', 0)
            result['errors'] += pull_result.get('errors', 0)

        # Actualizar última fecha de sync de la regla
        rule.write({'last_sync_date': fields.Datetime.now()})

        return result

    def _push_records(self, config, rule, uid, models_proxy, sync_fields):
        """
        PUSH: Envía registros locales modificados al nodo remoto.
        """
        result = {'sent': 0, 'errors': 0}
        model_name = rule.model_name

        # Construir dominio: registros modificados desde última sync
        domain = eval(rule.domain or '[]')
        if rule.last_sync_date:
            domain.append(('write_date', '>', rule.last_sync_date))

        records = self.env[model_name].search(
            domain, limit=rule.batch_size
        )

        if not records:
            return result

        _logger.info(f'PUSH {model_name}: {len(records)} registros')

        for record in records:
            try:
                data = self._serialize_record(record, sync_fields, rule)

                # Enviar al remoto via XML-RPC
                # El remoto debe tener instalado cida_sync y exponer
                # el método receive_sync_data
                remote_result = models_proxy.execute_kw(
                    config.remote_db, uid, config.remote_password,
                    'cida.sync.engine', 'receive_sync_data',
                    [json.dumps(data), rule.model_name, rule.match_field],
                )

                if remote_result.get('success'):
                    result['sent'] += 1
                else:
                    result['errors'] += 1
                    _logger.warning(
                        f'Error enviando {model_name}#{record.id}: '
                        f'{remote_result.get("error")}'
                    )

            except Exception as e:
                result['errors'] += 1
                _logger.error(f'Error serializando {model_name}#{record.id}: {e}')

        return result

    def _pull_records(self, config, rule, uid, models_proxy, sync_fields):
        """
        PULL: Trae registros remotos modificados al nodo local.
        """
        result = {'received': 0, 'errors': 0}
        model_name = rule.model_name

        # Pedir al remoto registros modificados desde última sync
        domain = eval(rule.domain or '[]')
        if rule.last_sync_date:
            domain.append(('write_date', '>', str(rule.last_sync_date)))

        try:
            # Leer registros remotos
            remote_ids = models_proxy.execute_kw(
                config.remote_db, uid, config.remote_password,
                model_name, 'search',
                [domain],
                {'limit': rule.batch_size},
            )

            if not remote_ids:
                return result

            # Leer los datos con los campos de sync
            # Agregar siempre write_date para detección de conflictos
            read_fields = list(set(sync_fields + ['write_date']))
            remote_records = models_proxy.execute_kw(
                config.remote_db, uid, config.remote_password,
                model_name, 'read',
                [remote_ids, read_fields],
            )

            _logger.info(f'PULL {model_name}: {len(remote_records)} registros')

            for remote_data in remote_records:
                try:
                    # Obtener UUID del registro remoto
                    remote_uuid = models_proxy.execute_kw(
                        config.remote_db, uid, config.remote_password,
                        'ir.config_parameter', 'get_param',
                        [f'cida_sync.uuid.{model_name}.{remote_data["id"]}'],
                    )

                    if not remote_uuid:
                        # El registro remoto no tiene UUID aún, generar uno
                        remote_uuid = str(uuid.uuid4())
                        models_proxy.execute_kw(
                            config.remote_db, uid, config.remote_password,
                            'ir.config_parameter', 'set_param',
                            [f'cida_sync.uuid.{model_name}.{remote_data["id"]}',
                             remote_uuid],
                        )

                    # Preparar data con formato de sync
                    sync_data = {
                        '_sync_uuid': remote_uuid,
                        '_sync_model': model_name,
                        '_sync_write_date': remote_data.get('write_date', ''),
                    }
                    # Copiar campos (excluir 'id' del remoto)
                    for fname in sync_fields:
                        if fname in remote_data and fname != 'id':
                            value = remote_data[fname]
                            # Convertir M2O de [id, name] a nuestro formato
                            finfo = self.env[model_name].fields_get([fname])
                            if finfo.get(fname, {}).get('type') == 'many2one':
                                if value and isinstance(value, (list, tuple)):
                                    rel_model = finfo[fname].get('relation')
                                    rel_uuid = models_proxy.execute_kw(
                                        config.remote_db, uid,
                                        config.remote_password,
                                        'ir.config_parameter', 'get_param',
                                        [f'cida_sync.uuid.{rel_model}.{value[0]}'],
                                    ) or str(uuid.uuid4())
                                    sync_data[fname] = {
                                        '_type': 'many2one',
                                        'model': rel_model,
                                        'uuid': rel_uuid,
                                        'name': value[1] if len(value) > 1 else '',
                                    }
                                else:
                                    sync_data[fname] = False
                            else:
                                sync_data[fname] = value

                    # Aplicar localmente
                    action, _ = self._deserialize_and_apply(sync_data, rule)
                    if action in ('created', 'updated'):
                        result['received'] += 1
                    elif action == 'error':
                        result['errors'] += 1

                except Exception as e:
                    result['errors'] += 1
                    _logger.error(
                        f'Error procesando pull {model_name}: {e}'
                    )

        except Exception as e:
            result['errors'] += 1
            _logger.error(f'Error en pull de {model_name}: {e}')

        return result

    # ----------------------------------------------------------
    # API para recibir datos del nodo remoto (endpoint)
    # ----------------------------------------------------------

    @api.model
    def receive_sync_data(self, json_data, model_name, match_field):
        """
        Endpoint XML-RPC para recibir datos de sincronización.

        Llamado por el nodo remoto durante un PUSH.

        Args:
            json_data: string JSON con los datos del registro
            model_name: nombre del modelo (ej: 'product.template')
            match_field: campo usado para matching

        Returns:
            dict: {success: bool, action: str, error: str}
        """
        try:
            data = json.loads(json_data)

            # Buscar o crear una regla temporal para este modelo
            rule = self.env['cida.sync.rule'].search([
                ('model_name', '=', model_name),
                ('active', '=', True),
            ], limit=1)

            if not rule:
                return {
                    'success': False,
                    'error': f'No hay regla de sync activa para {model_name}',
                }

            action, record_id = self._deserialize_and_apply(data, rule)

            return {
                'success': action in ('created', 'updated', 'skipped'),
                'action': action,
                'record_id': record_id,
            }

        except Exception as e:
            _logger.exception(f'Error recibiendo sync data: {e}')
            return {'success': False, 'error': str(e)}

    # ----------------------------------------------------------
    # Cron
    # ----------------------------------------------------------

    @api.model
    def cron_sync(self):
        """Ejecutado por el cron de Odoo periódicamente."""
        configs = self.env['cida.sync.config'].search([
            ('active', '=', True),
            ('state', 'in', ['connected', 'error']),
        ])
        for config in configs:
            try:
                self.run_sync(config)
            except Exception as e:
                _logger.exception(f'Error en cron sync: {e}')

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _create_log(self, config, rule, operation, state, **kwargs):
        """Crea un registro de log."""
        vals = {
            'config_id': config.id,
            'rule_id': rule.id if rule else False,
            'model_name': rule.model_name if rule else 'all',
            'operation': operation,
            'state': state,
        }
        vals.update(kwargs)
        return self.env['cida.sync.log'].sudo().create(vals)
