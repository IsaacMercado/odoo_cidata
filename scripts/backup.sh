#!/bin/bash
# ============================================================
# Backup Automático — pg_dump + rotación
# ============================================================
# Ejecutado por el contenedor de backup cada N horas.
# Crea un dump comprimido y elimina backups viejos.
# ============================================================

set -euo pipefail

BACKUP_DIR="/backups"
DATE=$(date +%Y%m%d_%H%M%S)
FILENAME="odoo_backup_${DATE}.sql.gz"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

echo "[$(date)] Iniciando backup..."

# Crear backup comprimido
pg_dump -h "$PGHOST" -U "$PGUSER" -d "$PGDATABASE" \
    --no-owner --no-privileges \
    | gzip > "${BACKUP_DIR}/${FILENAME}"

# Verificar que el archivo no está vacío
if [[ ! -s "${BACKUP_DIR}/${FILENAME}" ]]; then
    echo "[$(date)] ERROR: Backup vacío, eliminando archivo"
    rm -f "${BACKUP_DIR}/${FILENAME}"
    exit 1
fi

SIZE=$(du -h "${BACKUP_DIR}/${FILENAME}" | cut -f1)
echo "[$(date)] Backup creado: ${FILENAME} (${SIZE})"

# Eliminar backups viejos
DELETED=$(find "$BACKUP_DIR" -name "odoo_backup_*.sql.gz" \
    -mtime "+${RETENTION_DAYS}" -delete -print | wc -l)

if [[ "$DELETED" -gt 0 ]]; then
    echo "[$(date)] Eliminados ${DELETED} backups con más de ${RETENTION_DAYS} días"
fi

# Listar backups existentes
echo "[$(date)] Backups disponibles:"
ls -lh "${BACKUP_DIR}"/odoo_backup_*.sql.gz 2>/dev/null || echo "  (ninguno)"
echo "[$(date)] Backup completado."
