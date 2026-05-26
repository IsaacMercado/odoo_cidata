import json
import logging
import time
import uuid as uuid_lib
from datetime import datetime

import xmlrpc.client

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BaseSynchroServer(models.Model):
    _name = "base.synchro.server"
    _description = "Synchronized server"

    name = fields.Char("Server name", required=True)
    server_url = fields.Char(required=True)
    server_port = fields.Integer(required=True, default=8069)
    server_db = fields.Char("Server Database", required=True)
    login = fields.Char("Database UserName", required=True)
    password = fields.Char(required=True)

    node_role = fields.Selection(
        [("central", "Central"), ("remote", "Remoto")],
        string="Rol de este nodo",
        default="central",
        help="Define cómo se resuelven conflictos. Central = sus datos prevalecen.",
    )
    state = fields.Selection(
        [("draft", "Borrador"), ("connected", "Conectado"), ("error", "Error")],
        string="Estado",
        default="draft",
        readonly=True,
    )
    last_error = fields.Text(readonly=True)
    last_sync_date = fields.Datetime(readonly=True)
    sync_interval_minutes = fields.Integer(
        string="Intervalo automático (min)",
        default=0,
        help="0 = solo sincronización manual",
    )
    conflict_resolution = fields.Selection(
        [("newest_wins", "El más reciente gana"),
         ("central_wins", "El nodo central gana"),
         ("manual", "Resolver manualmente")],
        string="Resolución de conflictos",
        default="newest_wins",
        required=True,
    )
    active = fields.Boolean(default=True)
    obj_ids = fields.One2many(
        "base.synchro.obj", "server_id", "Models",
    )
    log_ids = fields.One2many(
        "base.synchro.log", "server_id", "Historial",
    )
    total_synced = fields.Integer(compute="_compute_stats")
    total_errors = fields.Integer(compute="_compute_stats")

    @api.depends("log_ids.state")
    def _compute_stats(self):
        for rec in self:
            rec.total_synced = len(rec.log_ids.filtered(lambda l: l.state == "done"))
            rec.total_errors = len(rec.log_ids.filtered(lambda l: l.state == "error"))

    def action_test_connection(self):
        self.ensure_one()
        try:
            common = xmlrpc.client.ServerProxy(
                f"{self.server_url}:{self.server_port}/xmlrpc/2/common",
                allow_none=True,
            )
            uid = common.authenticate(self.server_db, self.login, self.password, {})
            if not uid:
                raise UserError("Autenticación fallida con el servidor remoto")
            self.write({"state": "connected", "last_error": False})
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "¡Conexión exitosa!",
                    "message": f"Conectado como usuario ID {uid}",
                    "type": "success",
                    "sticky": False,
                },
            }
        except Exception as e:
            self.write({"state": "error", "last_error": str(e)})
            raise

    def action_sync_now(self):
        self.ensure_one()
        engine = self.env["base.synchro.engine"]
        result = engine.run_sync(self)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Sincronización completada",
                "message": (
                    f"Enviados: {result['sent']}, "
                    f"Recibidos: {result['received']}, "
                    f"Errores: {result['errors']}"
                ),
                "type": "success" if result["errors"] == 0 else "warning",
                "sticky": True,
            },
        }

    def action_view_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Historial de Sync",
            "res_model": "base.synchro.log",
            "view_mode": "tree,form",
            "domain": [("server_id", "=", self.id)],
            "context": {"default_server_id": self.id},
        }

    def action_sync_by_module(self):
        self.ensure_one()
        engine = self.env["base.synchro.engine"]
        module = self.env.context.get("active_module_id")
        if module:
            rules = self.obj_ids.filtered(lambda r: r.module_id.id == module)
        else:
            return self.action_sync_now()
        result = {"sent": 0, "received": 0, "errors": 0}
        try:
            uid, models_proxy = engine._connect(self)
        except Exception as e:
            self.write({"state": "error", "last_error": str(e)})
            return {"type": "ir.actions.client", "tag": "display_notification",
                    "params": {"title": "Error", "message": str(e), "type": "danger", "sticky": False}}
        for rule in rules.filtered("active"):
            try:
                r = engine._sync_rule(self, rule, uid, models_proxy)
                result["sent"] += r.get("sent", 0)
                result["received"] += r.get("received", 0)
                result["errors"] += r.get("errors", 0)
            except Exception as e:
                result["errors"] += 1
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Sincronización por módulo completada",
                "message": f"Enviados: {result['sent']}, Recibidos: {result['received']}, Errores: {result['errors']}",
                "type": "success" if result["errors"] == 0 else "warning",
                "sticky": True,
            },
        }

    def action_generate_rules_from_module(self):
        self.ensure_one()
        IrModel = self.env["ir.model"]
        created = 0
        for obj in self.obj_ids.filtered(lambda o: o.module_id):
            module = obj.module_id
            existing_models = self.obj_ids.filtered(
                lambda o: o.module_id == module
            ).mapped("model_id.model")
            models = IrModel.search([
                ("model", "not in", existing_models),
                ("transient", "=", False),
            ])
            module_models = models.filtered(
                lambda m: module.name in (m.modules or "").split(",")
            )
            next_sequence = max(self.obj_ids.mapped("sequence") or [0]) + 10
            for m in module_models:
                self.env["base.synchro.obj"].create({
                    "name": f"{module.name}: {m.name}",
                    "domain": "[]",
                    "server_id": self.id,
                    "model_id": m.id,
                    "action": "b",
                    "module_id": module.id,
                    "sequence": next_sequence,
                })
                next_sequence += 10
                created += 1
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Reglas generadas",
                "message": f"Se generaron {created} reglas para los modelos de los módulos seleccionados.",
                "type": "success",
                "sticky": False,
            },
        }


class BaseSynchroObj(models.Model):
    _name = "base.synchro.obj"
    _description = "Register Class"
    _order = "sequence"

    name = fields.Char(required=True)
    domain = fields.Char(required=True, default="[]")
    server_id = fields.Many2one(
        "base.synchro.server", "Server", ondelete="cascade", required=True,
    )
    model_id = fields.Many2one("ir.model", "Object to synchronize")
    action = fields.Selection(
        [("d", "Download"), ("u", "Upload"), ("b", "Both")],
        "Synchronization direction",
        required=True,
        default="d",
    )
    sequence = fields.Integer("Sequence")
    active = fields.Boolean(default=True)
    synchronize_date = fields.Datetime("Latest Synchronization", readonly=True)
    batch_size = fields.Integer(
        string="Lote",
        default=0,
        help="0 = sincronizar todos en una sola operación",
    )
    match_field = fields.Selection(
        [("sync_uuid", "UUID de Sync"),
         ("login", "Login"),
         ("name", "Nombre"),
         ("default_code", "Referencia Interna"),
         ("barcode", "Código de Barras"),
         ("vat", "RIF/NIF"),
         ("email", "Email")],
        string="Campo de matching",
        default="sync_uuid",
        required=True,
        help="Campo usado para identificar el mismo registro en ambas instancias.",
    )
    module_id = fields.Many2one(
        "ir.module.module",
        string="Módulo",
        help="Si se selecciona, esta regla se agrupa bajo ese módulo. "
             "Sirve para sincronizar todo un módulo de una sola vez.",
    )
    line_id = fields.One2many(
        "base.synchro.obj.line", "obj_id", "IDs Affected",
    )
    avoid_ids = fields.One2many(
        "base.synchro.obj.avoid", "obj_id", "Fields Not Sync.",
    )

    def get_sync_fields(self):
        self.ensure_one()
        Model = self.env[self.model_id.model]
        fields_info = Model.fields_get()
        exclude = {
            "id", "create_uid", "create_date", "write_uid",
            "__last_update", "display_name",
            "message_ids", "message_follower_ids",
            "message_main_attachment_id", "website_message_ids",
            "activity_ids", "activity_state", "activity_summary",
            "activity_type_id", "activity_user_id",
            "password",
            "totp_last_counter",
        }
        avoid = self.avoid_ids.mapped("name")
        sync_fields = []
        for fname, finfo in fields_info.items():
            if fname in exclude or fname in avoid:
                continue
            if fname.startswith("totp_"):
                continue
            if not finfo.get("store", False):
                continue
            if finfo.get("type") in ("one2many", "binary"):
                continue
            sync_fields.append(fname)
        return sync_fields


class BaseSynchroObjAvoid(models.Model):
    _name = "base.synchro.obj.avoid"
    _description = "Fields to not synchronize"

    name = fields.Char("Field Name", required=True)
    obj_id = fields.Many2one(
        "base.synchro.obj", "Object", required=True, ondelete="cascade",
    )


class BaseSynchroObjLine(models.Model):
    _name = "base.synchro.obj.line"
    _description = "Synchronized instances"

    name = fields.Datetime(
        "Date",
        required=True,
        default=lambda self: fields.Datetime.now(),
    )
    obj_id = fields.Many2one(
        "base.synchro.obj", "Object", ondelete="cascade",
    )
    local_id = fields.Integer("Local ID", readonly=True)
    remote_id = fields.Integer("Remote ID", readonly=True)
    uuid = fields.Char("UUID", readonly=True)


class BaseSynchroUuid(models.Model):
    _name = "base.synchro.uuid"
    _description = "Sync UUID Mapping"
    _rec_name = "uuid"

    model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    uuid = fields.Char(required=True, index=True)

    _base_synchro_uuid_uniq = models.Constraint(
        "unique(uuid)",
        "UUID must be unique!",
    )
    _base_synchro_model_res_uniq = models.Constraint(
        "unique(model, res_id)",
        "Only one UUID per record!",
    )

    @api.model
    def get_or_create(self, model, res_id):
        record = self.search(
            [("model", "=", model), ("res_id", "=", res_id)], limit=1,
        )
        if record:
            return record.uuid
        new_uuid = str(uuid_lib.uuid4())
        self.create({"model": model, "res_id": res_id, "uuid": new_uuid})
        return new_uuid

    @api.model
    def find_by_uuid(self, model, uuid):
        record = self.search(
            [("model", "=", model), ("uuid", "=", uuid)], limit=1,
        )
        return record.res_id if record else False

    @api.model
    def find_by_field(self, model, field, value):
        records = self.env[model].search([(field, "=", value)], limit=1)
        return records.id if records else False


class BaseSynchroEngine(models.AbstractModel):
    _name = "base.synchro.engine"
    _description = "Sync Engine"

    @staticmethod
    def _to_datetime(value):
        if not value:
            return False
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return fields.Datetime.to_datetime(value)

    def _bind_uuid(self, model, res_id, sync_uuid):
        uuid_model = self.env["base.synchro.uuid"].sudo()
        mapping = uuid_model.search(
            [("model", "=", model), ("res_id", "=", res_id)],
            limit=1,
        )
        if mapping:
            if sync_uuid and mapping.uuid != sync_uuid:
                mapping.write({"uuid": sync_uuid})
            return mapping.uuid
        return uuid_model.create({
            "model": model,
            "res_id": res_id,
            "uuid": sync_uuid,
        }).uuid

    @api.model
    def run_sync(self, server):
        _logger.info("=== Inicio sync: %s ===", server.name)
        start = time.time()
        result = {"sent": 0, "received": 0, "errors": 0}

        log = self.env["base.synchro.log"].create({
            "server_id": server.id,
            "operation": "full_sync",
            "state": "running",
        })

        try:
            uid, models_proxy = self._connect(server)
        except Exception as e:
            server.write({"state": "error", "last_error": str(e)})
            log.write({"state": "error", "error_message": str(e)})
            return result

        for rule in server.obj_ids.filtered("active"):
            try:
                r = self._sync_rule(server, rule, uid, models_proxy)
                result["sent"] += r.get("sent", 0)
                result["received"] += r.get("received", 0)
                result["errors"] += r.get("errors", 0)
            except Exception as e:
                _logger.exception("Error en regla %s", rule.name)
                result["errors"] += 1
                self.env["base.synchro.log"].create({
                    "server_id": server.id,
                    "rule_id": rule.id,
                    "model_name": rule.model_id.model,
                    "operation": "full_sync",
                    "state": "error",
                    "error_message": str(e),
                })

        elapsed = time.time() - start
        server.write({
            "state": "connected",
            "last_sync_date": fields.Datetime.now(),
            "last_error": False,
        })
        log.write({
            "state": "done",
            "duration_seconds": elapsed,
            "records_sent": result["sent"],
            "records_received": result["received"],
            "records_errored": result["errors"],
        })
        _logger.info(
            "=== Sync completado %.1fs: sent=%d recv=%d err=%d ===",
            elapsed, result["sent"], result["received"], result["errors"],
        )
        return result

    def _connect(self, server):
        common = xmlrpc.client.ServerProxy(
            f"{server.server_url}:{server.server_port}/xmlrpc/2/common",
            allow_none=True,
        )
        uid = common.authenticate(
            server.server_db, server.login, server.password, {},
        )
        if not uid:
            raise UserError("Autenticación fallida con el servidor remoto")
        models_proxy = xmlrpc.client.ServerProxy(
            f"{server.server_url}:{server.server_port}/xmlrpc/2/object",
            allow_none=True,
        )
        return uid, models_proxy

    def _sync_rule(self, server, rule, uid, models_proxy):
        result = {"sent": 0, "received": 0, "errors": 0}
        model = rule.model_id.model
        fields_to_sync = rule.get_sync_fields()
        if not fields_to_sync:
            return result

        if rule.action in ("u", "b"):
            s = self._push(server, rule, uid, models_proxy, fields_to_sync)
            result["sent"] += s.get("sent", 0)
            result["errors"] += s.get("errors", 0)

        if rule.action in ("d", "b"):
            r = self._pull(server, rule, uid, models_proxy, fields_to_sync)
            result["received"] += r.get("received", 0)
            result["errors"] += r.get("errors", 0)

        rule.write({"synchronize_date": fields.Datetime.now()})
        return result

    def _push(self, server, rule, uid, models_proxy, fields_to_sync):
        result = {"sent": 0, "errors": 0}
        model = rule.model_id.model
        domain = eval(rule.domain or "[]")
        if rule.synchronize_date:
            domain += [("write_date", ">", rule.synchronize_date)]

        records = self.env[model].search(
            domain, limit=rule.batch_size or None,
        )
        if not records:
            return result

        _logger.info("PUSH %s: %d registros", model, len(records))

        for record in records:
            try:
                data = self._serialize(record, fields_to_sync, rule)
                remote_result = models_proxy.execute_kw(
                    server.server_db, uid, server.password,
                    "base.synchro.engine", "receive_sync_data",
                    [json.dumps(data), model, rule.match_field],
                )
                if remote_result.get("success"):
                    result["sent"] += 1
                else:
                    result["errors"] += 1
                    _logger.warning(
                        "Error remoto %s#%d: %s",
                        model, record.id, remote_result.get("error"),
                    )
            except Exception as e:
                result["errors"] += 1
                _logger.error("Error PUSH %s#%d: %s", model, record.id, e)
        return result

    def _pull(self, server, rule, uid, models_proxy, fields_to_sync):
        result = {"received": 0, "errors": 0}
        model = rule.model_id.model
        domain = eval(rule.domain or "[]")
        if rule.synchronize_date:
            domain += [("write_date", ">", str(rule.synchronize_date))]

        try:
            remote_ids = models_proxy.execute_kw(
                server.server_db, uid, server.password,
                model, "search", [domain],
                {"limit": rule.batch_size or None},
            )
            if not remote_ids:
                return result

            read_fields = list(set(fields_to_sync + ["write_date"]))
            remote_records = models_proxy.execute_kw(
                server.server_db, uid, server.password,
                model, "read", [remote_ids, read_fields],
            )

            _logger.info("PULL %s: %d registros", model, len(remote_records))

            for remote_data in remote_records:
                try:
                    remote_uuid = models_proxy.execute_kw(
                        server.server_db, uid, server.password,
                        "base.synchro.uuid", "get_or_create",
                        [model, remote_data["id"]],
                    )
                    sync_data = self._transform_remote(
                        remote_data, fields_to_sync, model,
                        server, uid, models_proxy,
                    )
                    sync_data["_sync_uuid"] = remote_uuid
                    sync_data["_sync_model"] = model
                    sync_data["_sync_write_date"] = (
                        remote_data.get("write_date") or ""
                    )

                    action, _ = self._apply_remote(sync_data, rule)
                    if action in ("created", "updated"):
                        result["received"] += 1
                    elif action == "error":
                        result["errors"] += 1
                except Exception as e:
                    result["errors"] += 1
                    _logger.error("Error PULL %s: %s", model, e)
        except Exception as e:
            result["errors"] += 1
            _logger.error("Error PULL %s: %s", model, e)
        return result

    def _serialize(self, record, fields_to_sync, rule):
        data = {}
        fields_info = record.fields_get(fields_to_sync)
        model_name = rule.model_id.model

        for fname in fields_to_sync:
            finfo = fields_info.get(fname, {})
            value = record[fname]

            if finfo.get("type") == "many2one":
                if value:
                    rel_model = finfo.get("relation")
                    rel_uuid = self.env["base.synchro.uuid"].get_or_create(
                        rel_model, value.id,
                    )
                    data[fname] = {
                        "_type": "many2one",
                        "model": rel_model,
                        "uuid": rel_uuid,
                        "name": value.display_name or "",
                    }
                else:
                    data[fname] = False

            elif finfo.get("type") == "many2many":
                if value:
                    records_data = []
                    for rel_rec in value:
                        rel_uuid = self.env["base.synchro.uuid"].get_or_create(
                            finfo["relation"], rel_rec.id,
                        )
                        records_data.append({
                            "uuid": rel_uuid,
                            "model": finfo["relation"],
                            "name": rel_rec.display_name or "",
                        })
                    data[fname] = {"_type": "many2many", "records": records_data}
                else:
                    data[fname] = {"_type": "many2many", "records": []}

            elif finfo.get("type") in ("date", "datetime"):
                data[fname] = str(value) if value else False
            else:
                try:
                    json.dumps(value)
                except TypeError:
                    _logger.debug(
                        "Skipping non-serializable field %s on %s",
                        fname,
                        model_name,
                    )
                    continue
                data[fname] = value

        uuid_val = self.env["base.synchro.uuid"].get_or_create(
            model_name, record.id,
        )
        data["_sync_uuid"] = uuid_val
        data["_sync_model"] = model_name
        data["_sync_write_date"] = str(record.write_date)
        return data

    def _transform_remote(self, remote_data, fields_to_sync, model,
                          server, uid, models_proxy):
        data = {}
        fields_info = self.env[model].fields_get(fields_to_sync)
        for fname in fields_to_sync:
            if fname not in remote_data or fname == "id":
                continue
            value = remote_data[fname]
            finfo = fields_info.get(fname, {})
            if finfo.get("type") == "many2one":
                if value and isinstance(value, (list, tuple)):
                    rel_uuid = models_proxy.execute_kw(
                        server.server_db, uid, server.password,
                        "base.synchro.uuid", "get_or_create",
                        [finfo["relation"], value[0]],
                    )
                    data[fname] = {
                        "_type": "many2one",
                        "model": finfo["relation"],
                        "uuid": rel_uuid,
                        "name": value[1] if len(value) > 1 else "",
                    }
                else:
                    data[fname] = False
            else:
                data[fname] = value
        return data

    def _apply_remote(self, data, rule):
        model = data.get("_sync_model", rule.model_id.model)
        sync_uuid = data.get("_sync_uuid")
        remote_write = data.get("_sync_write_date")
        if not sync_uuid:
            return "skipped", False

        Model = self.env[model]
        local_id = self.env["base.synchro.uuid"].find_by_uuid(model, sync_uuid)

        if not local_id and rule.match_field != "sync_uuid":
            val = data.get(rule.match_field)
            if val:
                local_id = self.env["base.synchro.uuid"].find_by_field(
                    model, rule.match_field, val,
                )
                if local_id:
                    self._bind_uuid(model, local_id, sync_uuid)

        if not local_id and model == "res.users" and data.get("login"):
            local_id = self.env[model].search(
                [("login", "=", data["login"])],
                limit=1,
            ).id
            if local_id:
                self._bind_uuid(model, local_id, sync_uuid)

        vals = {}
        fields_info = Model.fields_get()
        for fname, value in data.items():
            if fname.startswith("_sync_") or fname not in fields_info:
                continue
            finfo = fields_info[fname]

            if isinstance(value, dict) and value.get("_type") == "many2one":
                rel_id = self.env["base.synchro.uuid"].find_by_uuid(
                    value["model"], value["uuid"],
                )
                if not rel_id and value.get("name"):
                    rel_id = self.env["base.synchro.uuid"].find_by_field(
                        value["model"], "name", value["name"],
                    )
                vals[fname] = rel_id or False

            elif isinstance(value, dict) and value.get("_type") == "many2many":
                ids = []
                for r in value.get("records", []):
                    rid = self.env["base.synchro.uuid"].find_by_uuid(
                        r["model"], r["uuid"],
                    )
                    if not rid and r.get("name"):
                        rid = self.env["base.synchro.uuid"].find_by_field(
                            r["model"], "name", r["name"],
                        )
                    if rid:
                        ids.append(rid)
                vals[fname] = [(6, 0, ids)]

            elif finfo.get("type") == "date" and isinstance(value, str):
                vals[fname] = fields.Date.to_date(value) if value else False
            elif finfo.get("type") == "datetime" and isinstance(value, str):
                vals[fname] = (
                    self._to_datetime(value) if value else False
                )
            else:
                vals[fname] = value

        if local_id:
            local = Model.browse(local_id)
            if self._check_conflict(rule, local, remote_write) == "skip":
                return "skipped", local_id
            try:
                with self.env.cr.savepoint():
                    local.write(vals)
                return "updated", local_id
            except Exception as e:
                _logger.error("Error actualizando %s#%d: %s", model, local_id, e)
                return "error", local_id
        else:
            try:
                if model == "res.users" and not vals.get("name"):
                    vals["name"] = (
                        vals.get("login")
                        or vals.get("email")
                        or "Synchronized User"
                    )
                with self.env.cr.savepoint():
                    new = Model.create(vals)
                self._bind_uuid(model, new.id, sync_uuid)
                return "created", new.id
            except Exception as e:
                _logger.error("Error creando %s: %s", model, e)
                return "error", False

    def _check_conflict(self, rule, local_record, remote_write_date):
        if not remote_write_date or not rule.synchronize_date:
            return "apply"
        server = rule.server_id
        remote_dt = self._to_datetime(remote_write_date)
        if (
            local_record.write_date > rule.synchronize_date
            and remote_dt > rule.synchronize_date
        ):
            if server.conflict_resolution == "central_wins":
                return "skip" if server.node_role == "central" else "apply"
            elif server.conflict_resolution == "newest_wins":
                return "apply" if remote_dt > local_record.write_date else "skip"
            else:
                return "skip"
        return "apply"

    @api.model
    def receive_sync_data(self, json_data, model_name, match_field):
        try:
            data = json.loads(json_data)
            rule = self.env["base.synchro.obj"].search([
                ("model_id.model", "=", model_name),
                ("active", "=", True),
                ("action", "in", ["d", "b"]),
            ], limit=1)
            if not rule:
                return {
                    "success": False,
                    "error": f"No hay regla activa para {model_name}",
                }
            action, record_id = self._apply_remote(data, rule)
            return {
                "success": action in ("created", "updated", "skipped"),
                "action": action,
                "record_id": record_id,
            }
        except Exception as e:
            _logger.exception("Error en receive_sync_data")
            return {"success": False, "error": str(e)}

    @api.model
    def cron_sync(self):
        servers = self.env["base.synchro.server"].search([
            ("active", "=", True),
            ("sync_interval_minutes", ">", 0),
            ("state", "in", ["connected", "error"]),
        ])
        for server in servers:
            try:
                self.run_sync(server)
            except Exception as e:
                _logger.exception("Error en cron sync para %s", server.name)
