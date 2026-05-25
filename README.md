# Odoo CIDA — Despliegue Multi-Sede

Sistema ERP (Odoo 19 Community) desplegado en dos sedes con sincronización
bidireccional de datos vía SymmetricDS y conectividad VPN vía Tailscale.

## Arquitectura

```
┌─────────────────────────┐         ┌─────────────────────────┐
│     SEDE CENTRAL        │         │    SEDE TURÍSTICA       │
│                         │         │                         │
│  ┌─────────────────┐    │  VPN    │    ┌─────────────────┐  │
│  │   Tailscale     │◄───┼─────────┼───►│   Tailscale     │  │
│  ├─────────────────┤    │Tailscale│    ├─────────────────┤  │
│  │   Nginx         │    │         │    │   Nginx         │  │
│  ├─────────────────┤    │         │    ├─────────────────┤  │
│  │   Odoo 19       │    │         │    │   Odoo 19       │  │
│  │   IDs: 1-100M   │    │         │    │   IDs: 100M+    │  │
│  ├─────────────────┤    │         │    ├─────────────────┤  │
│  │ PostgreSQL 17 + │    │         │    │ PostgreSQL 17 + │  │
│  │    pgvector     │    │         │    │    pgvector     │  │
│  ├─────────────────┤    │         │    ├─────────────────┤  │
│  │   SymmetricDS   │◄───┼── Sync ─┼───►│   SymmetricDS   │  │
│  ├─────────────────┤    │         │    ├─────────────────┤  │
│  │   Backup Auto   │    │         │    │   Backup Auto   │  │
│  └─────────────────┘    │         │    └─────────────────┘  │
└─────────────────────────┘         └─────────────────────────┘
```

## Requisitos

- Linux con motor de contenedores (**Docker** o **Podman**) y su herramienta compose (`docker compose` o `podman-compose`)
- Cuenta de [Tailscale](https://tailscale.com) (gratuita hasta 100 dispositivos)
- Dispositivo `/dev/net/tun` disponible (`sudo modprobe tun`)
- Si usas ejecución rootless, el proyecto expone por defecto `8080/8443` en el host para evitar puertos privilegiados

## Instalación Rápida

### 1. Clonar el repositorio en ambas máquinas

```bash
git clone <url-del-repo> odoo_cida
cd odoo_cida
```

### 2. Configurar Tailscale

1. Crear cuenta en [tailscale.com](https://tailscale.com)
2. Ir a **Settings → Keys → Generate auth key**
3. Generar un key **reusable** y **NO ephemeral** para servidores fijos
4. Si es posible, marcarlo como **pre-approved** para evitar alta manual

> No uses **ephemeral auth keys** en la sede central o turística.
> Los nodos efímeros cambian IP al recrearse y se eliminan tras inactividad,
> lo que rompe `registration.url`, `sync.url` y la resolución por nombre en Tailscale.

### 3. Ejecutar setup

**En la Sede Central:**
```bash
chmod +x scripts/setup.sh scripts/backup.sh
./scripts/setup.sh central
```

**En la Sede Turística:**
```bash
chmod +x scripts/setup.sh scripts/backup.sh
./scripts/setup.sh turistica
```

> **IMPORTANTE:** Ejecuta primero el setup en la sede CENTRAL.
> La sede turística se registra automáticamente con la central.

### 4. Acceder a Odoo

Abrir en el navegador: **http://localhost:8080**

## Estructura de Archivos

```
odoo_cida/
├── compose.yml                     # Stack completo parametrizado
├── .env.example                    # Template de configuración
├── .env                            # Config local (NO commitear)
├── config/
│   ├── odoo/odoo.conf              # Configuración de Odoo
│   ├── nginx/nginx.conf            # Reverse proxy
│   ├── symmetricds/
│   │   ├── central.properties      # Config nodo central
│   │   ├── turistica.properties    # Config nodo turístico
│   │   └── init-central.sql        # Topología de sync
│   └── postgres/
│       ├── init-sequences.sh       # Rangos de IDs por sede
│       └── pg_hba.conf             # Control de acceso BD
├── scripts/
│   ├── setup.sh                    # Instalación automática
│   └── backup.sh                   # Backup con rotación
├── backups/                        # Dumps automáticos
└── secrets/                        # Credenciales (gitignored)
```

## Comandos Útiles

| Comando (Docker / Podman) | Descripción |
|---------------------------|-------------|
| `docker compose ps` | Ver estado de contenedores |
| `docker compose logs -f` | Ver logs en tiempo real |
| `docker compose logs -f odoo` | Logs solo de Odoo |
| `docker compose down` | Detener todo |
| `docker compose up -d` | Arrancar todo |
| `docker compose restart odoo` | Reiniciar Odoo |

*(Nota: si usas Podman, reemplaza `docker compose` por `podman-compose`)*

### Verificar sincronización

```bash
# Ver estado de Tailscale
docker exec tailscale-central-001 tailscale status

# Ver estado de SymmetricDS
docker exec symmetricds-central-001 curl -s http://127.0.0.1:31415/api/engine/status
```
*(Nota: usa `podman exec` si utilizas Podman)*

### Restaurar un backup

```bash
# Detener Odoo
docker compose stop odoo

# Restaurar
gunzip -c backups/odoo_backup_FECHA.sql.gz | \
  docker exec -i postgres-central-001 psql -U odoo -d odoo

# Reiniciar
docker compose start odoo
```

## Reglas de Negocio

1. **IDs Separados**: Central usa IDs 1-100M, Turística usa 100M+1 a 200M
2. **Módulos**: Solo se instalan desde la sede CENTRAL
3. **Conflictos**: En caso de conflicto, la sede central tiene prioridad
4. **Datos sincronizados**: Contactos, productos, inventario, POS, ventas, compras
5. **Datos NO sincronizados**: Configuración interna de Odoo, crons, vistas, módulos

## Seguridad

### Gestión de Contraseñas (Docker/Podman Secrets)

**No hay contraseñas en texto plano en ningún archivo del proyecto.**

Las credenciales se almacenan cifradas via motor de secretos del contenedor:

```bash
# Ver secretos creados
docker secret ls

# Recrear un secreto (ej: cambiar contraseña de PostgreSQL)
docker secret rm pg_password
echo -n "NuevaClaveSegura" | docker secret create pg_password -
docker compose down && docker compose up -d
```
*(Nota: usa `podman secret` y `podman-compose` si utilizas Podman)*

| Secreto | Usado por | Propósito |
|---------|-----------|-----------|
| `pg_password` | PostgreSQL, Odoo, SymmetricDS, Backup | Contraseña de la BD |
| `ts_authkey` | Tailscale | Auth key para conectar a la VPN |

Los secretos se inyectan como archivos en `/run/secrets/` dentro de cada
contenedor. Solo el contenedor que los necesita tiene acceso.

### Seguridad de Red

- **Tailscale** corre en contenedor aislado (no instalado en el host)
- **PostgreSQL** solo acepta conexiones locales (`pg_hba.conf`)
- **Nginx** agrega headers de seguridad (X-Frame-Options, XSS, etc.)
- **Backups** automáticos cada 6 horas con rotación de 7 días

### Seguridad Física — Sede Turística

La computadora de la sede turística está expuesta a personal no técnico.
Aplica estas medidas para protegerla:

#### 1. Usuario restringido (sin terminal ni admin)
```bash
# Crear usuario que SOLO puede usar el navegador
sudo useradd -m -s /usr/sbin/nologin cida-pos
# O si necesita sesión gráfica:
sudo useradd -m -s /bin/bash -G nopasswdlogin cida-pos
# Quitar acceso a terminal
sudo chmod 750 /usr/bin/bash
# Configurar auto-login al usuario restringido
```

#### 2. Bloqueo automático de pantalla
```bash
# GNOME: bloqueo a los 5 minutos de inactividad
gsettings set org.gnome.desktop.session idle-delay 300
gsettings set org.gnome.desktop.screensaver lock-enabled true
gsettings set org.gnome.desktop.screensaver lock-delay 0
```

#### 3. Cifrado de disco (LUKS)
Si alguien roba la computadora, el disco cifrado protege los datos:
```bash
# Al instalar Linux, elegir "Cifrar disco completo"
# Si ya está instalado, cifrar la partición de datos
```

#### 4. Modo kiosco (solo navegador)
```bash
# Hacer que el usuario solo vea el navegador con Odoo
# Crear archivo ~/.config/autostart/odoo-kiosk.desktop:
# [Desktop Entry]
# Type=Application
# Name=Odoo POS
# Exec=firefox --kiosk http://localhost:8080
```

#### 5. BIOS/UEFI protegido
- Poner contraseña al BIOS para evitar boot desde USB
- Deshabilitar boot desde dispositivos externos

## Solución de Problemas

### Odoo no arranca
```bash
docker compose logs odoo
# Verificar que PostgreSQL está listo:
docker exec postgres-central-001 pg_isready -U odoo
```

### SymmetricDS no sincroniza
```bash
# Ver logs de sync
docker compose logs symmetricds
# Verificar conectividad Tailscale
docker exec tailscale-central-001 tailscale ping odoo-turistica-001
```

### Tailscale no conecta
```bash
# Ver estado
docker exec tailscale-central-001 tailscale status
# Re-autenticar si es necesario
docker exec tailscale-central-001 tailscale up --authkey=tskey-auth-XXX
```

## Advertencias

> ⚠️ **La sincronización bidireccional de bases de datos Odoo es una operación
> avanzada.** Odoo no fue diseñado para multi-master. Este setup mitiga los
> riesgos principales (IDs separados, tablas filtradas, conflictos resueltos),
> pero se recomienda:
>
> 1. **Probar extensivamente** antes de usar en producción
> 2. **Hacer backups frecuentes** (el sistema los hace automáticamente)
> 3. **Instalar módulos SOLO desde la sede central**
> 4. **No modificar el mismo registro en ambas sedes simultáneamente**
