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
    ('config',   70, 5000,  1, 'Configuración compartida (monedas, impuestos)')
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
    ('turistica_to_central', 'turistica', 'central', 'default',
     current_timestamp, current_timestamp)
ON CONFLICT (router_id) DO NOTHING;

-- =========================
-- 5. TRIGGERS — Tablas a sincronizar
-- =========================
-- NOTA: sync_on_incoming_batch = 1 permite re-sincronizar
-- datos que llegaron de otro nodo (necesario para bidireccional)

-- --- Contactos ---
INSERT INTO sym_trigger
    (trigger_id, source_table_name, channel_id,
     sync_on_incoming_batch, last_update_time, create_time)
VALUES
    ('trig_res_partner', 'res_partner', 'partner',
     1, current_timestamp, current_timestamp),
    ('trig_res_partner_category', 'res_partner_category', 'partner',
     1, current_timestamp, current_timestamp)
ON CONFLICT (trigger_id) DO NOTHING;

-- --- Productos ---
INSERT INTO sym_trigger
    (trigger_id, source_table_name, channel_id,
     sync_on_incoming_batch, last_update_time, create_time)
VALUES
    ('trig_product_category', 'product_category', 'product',
     1, current_timestamp, current_timestamp),
    ('trig_product_template', 'product_template', 'product',
     1, current_timestamp, current_timestamp),
    ('trig_product_product', 'product_product', 'product',
     1, current_timestamp, current_timestamp),
    ('trig_product_pricelist', 'product_pricelist', 'product',
     1, current_timestamp, current_timestamp),
    ('trig_product_pricelist_item', 'product_pricelist_item', 'product',
     1, current_timestamp, current_timestamp),
    ('trig_uom_uom', 'uom_uom', 'product',
     1, current_timestamp, current_timestamp),
    ('trig_uom_category', 'uom_category', 'product',
     1, current_timestamp, current_timestamp)
ON CONFLICT (trigger_id) DO NOTHING;

-- --- Inventario ---
INSERT INTO sym_trigger
    (trigger_id, source_table_name, channel_id,
     sync_on_incoming_batch, last_update_time, create_time)
VALUES
    ('trig_stock_warehouse', 'stock_warehouse', 'stock',
     1, current_timestamp, current_timestamp),
    ('trig_stock_location', 'stock_location', 'stock',
     1, current_timestamp, current_timestamp),
    ('trig_stock_picking_type', 'stock_picking_type', 'stock',
     1, current_timestamp, current_timestamp),
    ('trig_stock_quant', 'stock_quant', 'stock',
     1, current_timestamp, current_timestamp),
    ('trig_stock_move', 'stock_move', 'stock',
     1, current_timestamp, current_timestamp),
    ('trig_stock_picking', 'stock_picking', 'stock',
     1, current_timestamp, current_timestamp),
    ('trig_stock_lot', 'stock_lot', 'stock',
     1, current_timestamp, current_timestamp)
ON CONFLICT (trigger_id) DO NOTHING;

-- --- Punto de Venta ---
INSERT INTO sym_trigger
    (trigger_id, source_table_name, channel_id,
     sync_on_incoming_batch, last_update_time, create_time)
VALUES
    ('trig_pos_config', 'pos_config', 'pos',
     1, current_timestamp, current_timestamp),
    ('trig_pos_session', 'pos_session', 'pos',
     1, current_timestamp, current_timestamp),
    ('trig_pos_order', 'pos_order', 'pos',
     1, current_timestamp, current_timestamp),
    ('trig_pos_order_line', 'pos_order_line', 'pos',
     1, current_timestamp, current_timestamp),
    ('trig_pos_payment', 'pos_payment', 'pos',
     1, current_timestamp, current_timestamp),
    ('trig_pos_payment_method', 'pos_payment_method', 'pos',
     1, current_timestamp, current_timestamp)
ON CONFLICT (trigger_id) DO NOTHING;

-- --- Ventas ---
INSERT INTO sym_trigger
    (trigger_id, source_table_name, channel_id,
     sync_on_incoming_batch, last_update_time, create_time)
VALUES
    ('trig_sale_order', 'sale_order', 'sale',
     1, current_timestamp, current_timestamp),
    ('trig_sale_order_line', 'sale_order_line', 'sale',
     1, current_timestamp, current_timestamp)
ON CONFLICT (trigger_id) DO NOTHING;

-- --- Compras ---
INSERT INTO sym_trigger
    (trigger_id, source_table_name, channel_id,
     sync_on_incoming_batch, last_update_time, create_time)
VALUES
    ('trig_purchase_order', 'purchase_order', 'purchase',
     1, current_timestamp, current_timestamp),
    ('trig_purchase_order_line', 'purchase_order_line', 'purchase',
     1, current_timestamp, current_timestamp)
ON CONFLICT (trigger_id) DO NOTHING;

-- --- Configuración compartida ---
INSERT INTO sym_trigger
    (trigger_id, source_table_name, channel_id,
     sync_on_incoming_batch, last_update_time, create_time)
VALUES
    ('trig_res_currency', 'res_currency', 'config',
     1, current_timestamp, current_timestamp),
    ('trig_res_currency_rate', 'res_currency_rate', 'config',
     1, current_timestamp, current_timestamp),
    ('trig_account_tax', 'account_tax', 'config',
     1, current_timestamp, current_timestamp),
    ('trig_res_company', 'res_company', 'config',
     1, current_timestamp, current_timestamp)
ON CONFLICT (trigger_id) DO NOTHING;

-- =========================
-- 6. TRIGGER-ROUTER LINKS
-- =========================
-- Vincular cada trigger con ambos routers (bidireccional)

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
        INSERT INTO sym_trigger_router
            (trigger_id, router_id, initial_load_order,
             create_time, last_update_time)
        VALUES
            (trig.trigger_id, 'turistica_to_central', load_order,
             current_timestamp, current_timestamp)
        ON CONFLICT DO NOTHING;

        load_order := load_order + 10;
    END LOOP;
END $$;

-- =========================
-- 7. RESOLUCIÓN DE CONFLICTOS
-- =========================
-- El nodo CENTRAL siempre gana en caso de conflicto.
-- Si ambos nodos modifican el mismo registro, se mantiene
-- la versión del nodo central.

INSERT INTO sym_conflict
    (conflict_id, source_node_group_id, target_node_group_id,
     target_channel_id, detect_type, resolve_type,
     create_time, last_update_time)
VALUES
    -- Cuando turística envía datos que conflictúan con central
    ('conflict_turistica_to_central',
     'turistica', 'central',
     'default',
     'USE_CHANGED_DATA',    -- Detectar con datos cambiados
     'MANUAL',              -- Requiere revisión manual
     current_timestamp, current_timestamp),
    -- Cuando central envía datos, central siempre gana
    ('conflict_central_to_turistica',
     'central', 'turistica',
     'default',
     'USE_CHANGED_DATA',
     'NEWER_WINS',          -- El más reciente gana (central)
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
