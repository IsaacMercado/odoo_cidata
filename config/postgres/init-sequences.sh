#!/bin/bash
# ============================================================
# Inicialización de Secuencias PostgreSQL
# ============================================================
# Ejecutado automáticamente por postgres en el primer arranque.
# Configura los rangos de secuencias según la sede:
#
#   Central:    SEQUENCE_START=1          SEQUENCE_END=100000000
#   Turística:  SEQUENCE_START=100000001  SEQUENCE_END=200000000
#
# Esto evita colisiones de IDs entre ambas sedes.
# ============================================================

set -e

SEQUENCE_START="${SEQUENCE_START:-1}"
SEQUENCE_END="${SEQUENCE_END:-100000000}"

echo "============================================"
echo " Configurando rangos de secuencias"
echo " Inicio: ${SEQUENCE_START}"
echo " Fin:    ${SEQUENCE_END}"
echo "============================================"

# Crear función que será llamada después de que Odoo
# inicialice la base de datos para reconfigurar las secuencias
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Función para reconfigurar todas las secuencias de una BD
    CREATE OR REPLACE FUNCTION reset_all_sequences(seq_start BIGINT)
    RETURNS void AS \$\$
    DECLARE
        seq_record RECORD;
        current_val BIGINT;
    BEGIN
        FOR seq_record IN
            SELECT schemaname, sequencename
            FROM pg_sequences
            WHERE schemaname = 'public'
              AND sequencename NOT LIKE 'sym_%'
        LOOP
            -- Solo modificar si el valor actual es menor al rango
            EXECUTE format(
                'SELECT last_value FROM %I.%I',
                seq_record.schemaname, seq_record.sequencename
            ) INTO current_val;

            IF current_val < seq_start THEN
                EXECUTE format(
                    'ALTER SEQUENCE %I.%I RESTART WITH %s',
                    seq_record.schemaname, seq_record.sequencename,
                    seq_start
                );
                RAISE NOTICE 'Secuencia % reiniciada a %',
                    seq_record.sequencename, seq_start;
            END IF;
        END LOOP;
    END;
    \$\$ LANGUAGE plpgsql;

    -- Guardar la configuración del nodo para uso posterior
    CREATE TABLE IF NOT EXISTS cida_node_config (
        key   VARCHAR(100) PRIMARY KEY,
        value VARCHAR(255) NOT NULL
    );

    INSERT INTO cida_node_config (key, value) VALUES
        ('sequence_start', '${SEQUENCE_START}'),
        ('sequence_end', '${SEQUENCE_END}')
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

    -- Nota: Las secuencias de Odoo se crean cuando Odoo
    -- inicializa la BD. El script setup.sh ejecuta
    -- reset_all_sequences() DESPUÉS de la primera
    -- inicialización de Odoo.

EOSQL

echo "Configuración de secuencias completada."
