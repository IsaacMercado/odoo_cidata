-- ============================================================
-- SymmetricDS — Configuración de Sincronización
-- ============================================================
-- Este SQL se ejecuta en el nodo CENTRAL después de que
-- SymmetricDS crea sus tablas internas (sym_*).
--
-- Define:
--   1. Canales de datos (qué tipo de datos se sincronizan)
--   2. Grupos de nodos (central, turistica)
--   3. Enlaces entre grupos (bidireccional)
--   4. Triggers (qué tablas capturar)
--   5. Routers (cómo fluyen los datos)
--   6. Trigger-Router links
--   7. Conflictos (central siempre gana)
--
-- USO: Ejecutar DESPUÉS de que SymmetricDS arranque por
--      primera vez y cree las tablas sym_*.
--
--   podman exec symmetricds-central-001 \
--     psql -U odoo -d odoo -f /opt/init-central.sql
-- ============================================================

-- =========================
-- 1. CANALES
-- =========================
INSERT INTO sym_channel (channel_id, processing_order, max_batch_size, enabled, description)
VALUES
    ('partner',  10, 10000, 1, 'Contactos y partners'),
    ('product',  20, 10000, 1, 'Productos y categorías'),
    ('stock',    30, 10000, 1, 'Inventario y movimientos de stock'),
    ('pos',      40, 10000, 1, 'Punto de venta'),
    ('sale',     50, 10000, 1, 'Órdenes de venta'),
    ('purchase', 60, 10000, 1, 'Órdenes de compra'),
    ('config',   70, 5000,  1, 'Configuración compartida (monedas, impuestos)'),
    ('security', 80, 5000,  1, 'Usuarios, grupos, permisos y reglas desde central')
ON CONFLICT (channel_id) DO NOTHING;

-- =========================
-- 2. GRUPOS DE NODOS
-- =========================
INSERT INTO sym_node_group (node_group_id, description)
VALUES
    ('central',   'Sede Central - Administrativa'),
    ('turistica', 'Sede Turística - POS e Inventario')
ON CONFLICT (node_group_id) DO NOTHING;

-- =========================
-- 3. ENLACES (bidireccional con Push)
-- =========================
INSERT INTO sym_node_group_link
    (source_node_group_id, target_node_group_id, data_event_action)
VALUES
    ('central',   'turistica', 'P'),
    ('turistica', 'central',   'P')
ON CONFLICT DO NOTHING;

-- =========================
-- 4. ROUTERS
-- =========================
INSERT INTO sym_router
    (router_id, source_node_group_id, target_node_group_id,
     router_type, create_time, last_update_time)
VALUES
    ('central_to_turistica', 'central', 'turistica', 'default',
     current_timestamp, current_timestamp),
    ('central_to_turistica_non_user_partners', 'central', 'turistica', 'subselect',
     current_timestamp, current_timestamp),
    ('turistica_to_central', 'turistica', 'central', 'default',
     current_timestamp, current_timestamp),
    ('turistica_to_central_non_user_partners', 'turistica', 'central', 'subselect',
     current_timestamp, current_timestamp)
ON CONFLICT (router_id) DO NOTHING;

UPDATE sym_router
   SET router_type = 'subselect',
       router_expression = 'not exists (select 1 from res_users u where u.partner_id = :ID)',
       last_update_time = current_timestamp
 WHERE router_id IN ('central_to_turistica_non_user_partners', 'turistica_to_central_non_user_partners');

-- =========================
-- 5. TRIGGERS — Tablas a sincronizar
-- =========================
-- Estrategia:
--   - Capturar automáticamente casi todas las tablas de Odoo en `public`
--   - Excluir tablas técnicas/locales que NO deben replicarse
--   - Permitir que módulos nuevos entren solos sin tocar este SQL
--
-- Tablas excluidas intencionalmente:
--   - sym_*        : internas de SymmetricDS (además SymmetricDS ya las evita)
--   - ir_*         : metadatos, vistas, módulos, secuencias, crons, config técnica
--   - mail_*       : colas/notificaciones/chatter técnico
--   - bus_*        : websocket/presencia/eventos en tiempo real
--   - auth_*       : autenticación local (TOTP, passkeys, etc.)
--   - res_users*   : se sincroniza de forma explícita y unidireccional desde central
--   - res_partner  : se maneja por triggers explícitos para separar partners de usuarios
--   - res_device*  : dispositivos/sesiones locales
--   - ir_attachment: requiere estrategia separada de filestore
--   - base_import_*, iap_*, fetchmail_*, queue_job* : tablas técnicas/servicio
--   - pos_session  : sesiones activas muy sensibles; evaluar luego si hace falta
--   - *_wizard*    : modelos transitorios/auxiliares
--
-- Inventario queda incluido por wildcard, porque la sede turística también
-- recibe y procesa inventario. Si más adelante `stock_quant` genera ruido,
-- será la primera tabla a reevaluar.
INSERT INTO sym_trigger
    (trigger_id, source_schema_name, source_table_name, channel_id,
     sync_on_incoming_batch, last_update_time, create_time, description)
VALUES
    ('trig_odoo_operational',
     'public',
     '*,!sym_*,!ir_*,!mail_*,!bus_*,!auth_*,!res_users*,!res_partner,!res_device*,!ir_attachment,!base_import_*,!iap_*,!fetchmail_*,!queue_job*,!pos_session,!*_wizard*',
     'default',
     1,
     current_timestamp,
     current_timestamp,
      'Wildcard para tablas operativas de Odoo con exclusión de tablas técnicas/locales')
ON CONFLICT (trigger_id) DO NOTHING;

INSERT INTO sym_trigger
    (trigger_id, source_schema_name, source_table_name, channel_id,
     sync_on_incoming_batch, last_update_time, create_time, description)
VALUES
    ('trig_res_partner_non_user', 'public', 'res_partner', 'partner', 1,
     current_timestamp, current_timestamp,
     'Partners operativos sin usuario asociado, bidireccional'),
    ('trig_res_partner_user_profile', 'public', 'res_partner', 'security', 1,
     current_timestamp, current_timestamp,
     'Partners ligados a usuarios, solo desde central hacia turistica')
ON CONFLICT (trigger_id) DO NOTHING;

-- Usuarios, grupos y permisos se sincronizan por una vía separada.
-- La sede central es la única fuente de verdad para administración.
INSERT INTO sym_trigger
    (trigger_id, source_schema_name, source_table_name, channel_id,
     sync_on_incoming_batch, last_update_time, create_time, description)
VALUES
    ('trig_res_users', 'public', 'res_users', 'security', 1,
     current_timestamp, current_timestamp,
     'Usuarios Odoo desde central hacia turistica'),
    ('trig_res_groups', 'public', 'res_groups', 'security', 1,
     current_timestamp, current_timestamp,
     'Grupos de seguridad desde central hacia turistica'),
    ('trig_res_groups_users_rel', 'public', 'res_groups_users_rel', 'security', 1,
     current_timestamp, current_timestamp,
     'Relación usuario-grupo desde central hacia turistica'),
    ('trig_ir_model_access', 'public', 'ir_model_access', 'security', 1,
     current_timestamp, current_timestamp,
     'ACLs de modelos desde central hacia turistica'),
    ('trig_ir_rule', 'public', 'ir_rule', 'security', 1,
     current_timestamp, current_timestamp,
     'Reglas de registros desde central hacia turistica'),
    ('trig_rule_group_rel', 'public', 'rule_group_rel', 'security', 1,
     current_timestamp, current_timestamp,
     'Relación entre reglas y grupos desde central hacia turistica')
ON CONFLICT (trigger_id) DO NOTHING;

-- =========================
-- 6. TRIGGER-ROUTER LINKS
-- =========================
-- Vincular cada trigger con ambos routers (bidireccional), excepto
-- seguridad/usuarios que solo deben viajar de central hacia turistica.

-- Macro: crear links para todos los triggers existentes
DO $$
DECLARE
    trig RECORD;
    load_order INT := 100;
BEGIN
    FOR trig IN SELECT trigger_id FROM sym_trigger
                WHERE trigger_id LIKE 'trig_%'
    LOOP
        -- Central → Turística
        INSERT INTO sym_trigger_router
            (trigger_id, router_id, initial_load_order,
             create_time, last_update_time)
        VALUES
            (trig.trigger_id, 'central_to_turistica', load_order,
             current_timestamp, current_timestamp)
        ON CONFLICT DO NOTHING;

        -- Turística → Central
        IF trig.trigger_id NOT IN (
            'trig_res_users',
            'trig_res_groups',
            'trig_res_groups_users_rel',
            'trig_ir_model_access',
            'trig_ir_rule',
            'trig_rule_group_rel',
            'trig_res_partner_non_user',
            'trig_res_partner_user_profile'
        ) THEN
            INSERT INTO sym_trigger_router
                (trigger_id, router_id, initial_load_order,
                 create_time, last_update_time)
            VALUES
                (trig.trigger_id, 'turistica_to_central', load_order,
                 current_timestamp, current_timestamp)
            ON CONFLICT DO NOTHING;
        END IF;

        load_order := load_order + 10;
    END LOOP;
END $$;

INSERT INTO sym_trigger_router
    (trigger_id, router_id, initial_load_order, create_time, last_update_time)
VALUES
    ('trig_res_partner_non_user', 'central_to_turistica_non_user_partners', 95,
     current_timestamp, current_timestamp),
    ('trig_res_partner_non_user', 'turistica_to_central_non_user_partners', 95,
     current_timestamp, current_timestamp),
    ('trig_res_partner_user_profile', 'central_to_turistica', 96,
     current_timestamp, current_timestamp)
ON CONFLICT DO NOTHING;

-- =========================
-- 7. RESOLUCIÓN DE CONFLICTOS
-- =========================
-- El nodo CENTRAL siempre gana en caso de conflicto.
-- Si ambos nodos modifican el mismo registro, se mantiene
-- la versión del nodo central.

INSERT INTO sym_conflict
    (conflict_id, source_node_group_id, target_node_group_id,
     target_channel_id, detect_type, resolve_type, ping_back,
     create_time, last_update_time)
VALUES
    -- Cuando turística envía datos que conflictúan con central
    ('conflict_turistica_to_central',
     'turistica', 'central',
     'default',
     'USE_CHANGED_DATA',    -- Detectar con datos cambiados
     'MANUAL',              -- Requiere revisión manual
     'OFF',
     current_timestamp, current_timestamp),
    -- Cuando central envía datos, central siempre gana
    ('conflict_central_to_turistica',
     'central', 'turistica',
     'default',
     'USE_CHANGED_DATA',
     'NEWER_WINS',          -- El más reciente gana (central)
     'OFF',
     current_timestamp, current_timestamp)
ON CONFLICT (conflict_id) DO NOTHING;

-- ============================================================
-- FIN DE CONFIGURACIÓN
-- ============================================================
-- Después de ejecutar este SQL, reiniciar SymmetricDS:
--   podman restart symmetricds-central-001
--
-- Luego, arrancar el nodo turística para que se registre
-- automáticamente con el central.
-- ============================================================
