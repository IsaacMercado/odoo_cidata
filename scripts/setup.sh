#!/bin/bash
# ============================================================
# Setup Inicial — Odoo CIDA Multi-Sede
# ============================================================
# Ejecutar UNA SOLA VEZ en cada máquina para:
#   1. Validar prerrequisitos (detecta docker o podman automáticamente)
#   2. Generar secretos CIFRADOS (docker/podman secret)
#   3. Crear archivo .env (SIN contraseñas)
#   4. Levantar el stack
#   5. Esperar a que Odoo inicialice la BD
#   6. Reconfigurar secuencias al rango correcto
#   7. (Solo central) Cargar config de SymmetricDS
#
# ⚠️  Las contraseñas NUNCA se escriben en disco.
#     Se generan → se inyectan a docker/podman secret → se borran
#     de la memoria del script.
#
# USO:
#   chmod +x scripts/setup.sh
#   ./scripts/setup.sh central     # En la sede central
#   ./scripts/setup.sh turistica   # En la sede turística
# ============================================================

set -euo pipefail

# --- Colores ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; exit 1; }
info()  { echo -e "${BLUE}[i]${NC} $1"; }

# --- Validar argumento ---
ROLE="${1:-}"
if [[ "$ROLE" != "central" && "$ROLE" != "turistica" ]]; then
    echo "============================================"
    echo " Odoo CIDA — Setup Inicial"
    echo "============================================"
    echo ""
    echo "Uso: $0 <central|turistica>"
    echo ""
    echo "  central    — Para la sede central/administrativa"
    echo "  turistica  — Para la sede turística/operativa"
    echo ""
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo ""
echo "============================================"
echo " Odoo CIDA — Setup: Sede ${ROLE^^}"
echo "============================================"
echo ""

# --- 1. Verificar prerrequisitos ---
info "Verificando prerrequisitos..."

CONTAINER_CMD=""
COMPOSE_CMD=""

if command -v podman &> /dev/null && command -v podman-compose &> /dev/null; then
    CONTAINER_CMD="podman"
    COMPOSE_CMD="podman-compose"
    log "Usando Podman como motor de contenedores"
elif command -v docker &> /dev/null; then
    CONTAINER_CMD="docker"
    if docker compose version &> /dev/null; then
        COMPOSE_CMD="docker compose"
    elif command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
    else
        error "Docker encontrado, pero no docker-compose. Instálalo primero."
    fi
    log "Usando Docker como motor de contenedores ($COMPOSE_CMD)"
else
    error "Ni Podman ni Docker encontrados. Instala uno primero."
fi

if ! command -v openssl &> /dev/null; then
    error "openssl no está instalado. Instálalo primero."
fi
log "openssl encontrado"

if [[ ! -c /dev/net/tun ]]; then
    warn "/dev/net/tun no encontrado. Tailscale podría no funcionar."
    warn "Intenta: sudo modprobe tun"
fi

# --- 2. Crear .env (SIN contraseñas) ---
if [[ ! -f .env ]]; then
    info "Creando .env desde template..."
    cp .env.example .env

    if [[ "$ROLE" == "central" ]]; then
        sed -i 's/NODE_ROLE=central/NODE_ROLE=central/' .env
        sed -i 's/NODE_ID=central-001/NODE_ID=central-001/' .env
        sed -i 's/REMOTE_NODE_ID=turistica-001/REMOTE_NODE_ID=turistica-001/' .env
        sed -i 's/SEQUENCE_START=1/SEQUENCE_START=1/' .env
        sed -i 's/SEQUENCE_END=100000000/SEQUENCE_END=100000000/' .env
    else
        sed -i 's/NODE_ROLE=central/NODE_ROLE=turistica/' .env
        sed -i 's/NODE_ID=central-001/NODE_ID=turistica-001/' .env
        sed -i 's/REMOTE_NODE_ID=turistica-001/REMOTE_NODE_ID=central-001/' .env
        sed -i 's/SEQUENCE_START=1/SEQUENCE_START=100000001/' .env
        sed -i 's/SEQUENCE_END=100000000/SEQUENCE_END=200000000/' .env
    fi

    log ".env creado (sin contraseñas — están en $CONTAINER_CMD secret)"
else
    log ".env ya existe, usando configuración existente"
fi

# Cargar variables
source .env

# Compatibilidad con .env existentes creados antes de introducir
# puertos host configurables para entornos rootless.
HOST_HTTP_PORT="${HOST_HTTP_PORT:-8080}"
HOST_HTTPS_PORT="${HOST_HTTPS_PORT:-8443}"
HOST_ODOO_PORT="${HOST_ODOO_PORT:-8069}"

# ==============================================================
# 3. CREAR SECRETOS CIFRADOS
# ==============================================================
# Las contraseñas se generan, se inyectan directamente al
# almacén cifrado del engine, y NUNCA tocan el disco.
# ==============================================================

create_secret() {
    local SECRET_NAME="$1"
    local SECRET_VALUE="$2"

    if $CONTAINER_CMD secret inspect "$SECRET_NAME" &>/dev/null; then
        info "Secreto '${SECRET_NAME}' ya existe, omitiendo"
        return 0
    fi

    # Inyectar directamente via stdin (nunca toca disco)
    echo -n "$SECRET_VALUE" | $CONTAINER_CMD secret create "$SECRET_NAME" -
    log "Secreto '${SECRET_NAME}' creado (cifrado por $CONTAINER_CMD)"
}

# --- Contraseña de PostgreSQL ---
if ! $CONTAINER_CMD secret inspect pg_password &>/dev/null; then
    PG_PASS=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)
    create_secret "pg_password" "$PG_PASS"
    echo ""
    warn "╔══════════════════════════════════════════════════╗"
    warn "║  CONTRASEÑA DE PostgreSQL GENERADA               ║"
    warn "║  Anótala en un lugar SEGURO fuera de esta PC.    ║"
    warn "║                                                  ║"
    info "║  ${PG_PASS}  ║"
    warn "║                                                  ║"
    warn "║  Esta contraseña NO se guardó en ningún archivo. ║"
    warn "║  Si la pierdes, tendrás que recrear los secretos.║"
    warn "╚══════════════════════════════════════════════════╝"
    echo ""
    # Borrar de la memoria del script
    unset PG_PASS
else
    log "Secreto 'pg_password' ya existe"
fi

# --- Auth Key de Tailscale ---
if ! $CONTAINER_CMD secret inspect ts_authkey &>/dev/null; then
    echo ""
    info "Tailscale requiere un Auth Key para conectar a la VPN."
    info "Genera uno en: https://login.tailscale.com/admin/settings/keys"
    echo ""
    read -s -p "Pega tu Tailscale Auth Key (no se mostrará): " TS_KEY
    echo ""

    if [[ -z "$TS_KEY" || "$TS_KEY" == "tskey-auth-XXXXXXXXXXXXXXXX" ]]; then
        warn "Auth Key vacío o de ejemplo."
        read -p "¿Deseas continuar sin Tailscale? (s/N): " -r
        if [[ ! "$REPLY" =~ ^[Ss]$ ]]; then
            error "Configura un Tailscale Auth Key válido"
        fi
        # Crear un placeholder para que compose no falle
        create_secret "ts_authkey" "not-configured"
    else
        create_secret "ts_authkey" "$TS_KEY"
    fi
    unset TS_KEY
else
    log "Secreto 'ts_authkey' ya existe"
fi

echo ""
info "Verificando secretos creados..."
echo "  Secretos en $CONTAINER_CMD:"
$CONTAINER_CMD secret ls
echo ""

# --- 4. Crear directorios necesarios ---
mkdir -p backups
log "Directorio de backups creado"

# --- 5. Levantar el stack ---
info "Levantando contenedores..."
$COMPOSE_CMD up -d
log "Contenedores iniciados"

# --- 6. Esperar a que Odoo inicialice ---
info "Esperando a que Odoo inicialice la base de datos (puede tardar 2-5 min)..."
RETRIES=0
MAX_RETRIES=30
until $CONTAINER_CMD exec "odoo-${NODE_ID}" curl -sf http://127.0.0.1:8069/web/health > /dev/null 2>&1; do
    RETRIES=$((RETRIES + 1))
    if [[ $RETRIES -ge $MAX_RETRIES ]]; then
        error "Odoo no respondió después de ${MAX_RETRIES} intentos"
    fi
    echo -n "."
    sleep 10
done
echo ""
log "Odoo está listo"

# --- 7. Reconfigurar secuencias ---
info "Reconfigurando secuencias al rango de esta sede..."
$CONTAINER_CMD exec "postgres-${NODE_ID}" psql \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT reset_all_sequences(${SEQUENCE_START});" \
    2>/dev/null || warn "Las secuencias se configurarán en el próximo reinicio"
log "Secuencias configuradas: ${SEQUENCE_START} → ${SEQUENCE_END}"

# --- 8. Cargar config de SymmetricDS (solo central) ---
if [[ "$ROLE" == "central" ]]; then
    info "Cargando configuración de sincronización en SymmetricDS..."
    sleep 30  # Esperar a que SymmetricDS cree sus tablas

    $CONTAINER_CMD exec -i "postgres-${NODE_ID}" psql \
        -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -f /dev/stdin < config/symmetricds/init-central.sql \
        2>/dev/null && log "Configuración de SymmetricDS cargada" \
        || warn "No se pudo cargar la config de SymmetricDS. Ejecútala manualmente después."

    info "Reiniciando SymmetricDS para aplicar configuración..."
    $CONTAINER_CMD restart "symmetricds-${NODE_ID}"
fi

# --- Resumen ---
echo ""
echo "============================================"
echo " ¡Setup completado!"
echo "============================================"
echo ""
echo " Sede:      ${ROLE^^}"
echo " Nodo:      ${NODE_ID}"
echo " Odoo:      http://localhost:${HOST_HTTP_PORT}"
echo ""
echo " 🔒 SEGURIDAD:"
echo "   - Contraseñas cifradas en $CONTAINER_CMD secret"
echo "   - NO hay contraseñas en .env ni en disco"
echo "   - Ver secretos: $CONTAINER_CMD secret ls"
echo ""
if [[ "$ROLE" == "turistica" ]]; then
    echo " SIGUIENTE PASO:"
    echo " Asegúrate de que el nodo CENTRAL esté corriendo."
    echo " El nodo turística se registrará automáticamente."
fi
echo ""
echo " Comandos útiles:"
echo "   $COMPOSE_CMD ps          — Ver estado"
echo "   $COMPOSE_CMD logs -f     — Ver logs"
echo "   $COMPOSE_CMD down        — Detener todo"
echo "   $COMPOSE_CMD up -d       — Arrancar todo"
echo "   $CONTAINER_CMD secret ls           — Ver secretos"
echo ""
echo " ⚠️  RECOMENDACIONES PARA SEDE TURÍSTICA:"
echo "   1. Bloquear pantalla: configurar auto-lock (5 min)"
echo "   2. Usuario sin permisos de terminal/admin"
echo "   3. Cifrar disco con LUKS si es posible"
echo "   4. Ver README.md sección 'Seguridad Física'"
echo ""
