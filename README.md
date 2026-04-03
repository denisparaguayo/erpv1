# Mbarete ERP - VPS / Coolify Ready

Esta version soporta SQLite y PostgreSQL, con login de usuarios y rol admin.

## Cambios clave

- Login obligatorio para usar el ERP.
- Roles `admin` y `user`.
- Compatibilidad de conexion por `DATABASE_URL`.
- Si `DATABASE_URL` no existe, sigue usando SQLite.
- Script de migracion SQLite -> PostgreSQL.

## Variables de entorno

- `MBARETE_SECRET_KEY` (obligatoria)
- `DATABASE_URL` (opcional, para PostgreSQL)
- `MBARETE_ADMIN_EMAIL` (opcional, default `admin@mbarete.local`)
- `MBARETE_ADMIN_PASSWORD` (opcional, default `admin123`)

## Modos de base de datos

### SQLite (actual)

Se guarda en `/data/instance/mbarete_erp.sqlite3`.

### PostgreSQL

Defini `DATABASE_URL`, por ejemplo:

```bash
DATABASE_URL=postgresql://erp_user:erp_pass@127.0.0.1:5432/erp_db
```

Al arrancar, la app aplica `schema_postgres.sql` automaticamente.

## Migracion a PostgreSQL

1. Crear DB y usuario en PostgreSQL.
2. Correr la app una vez con `DATABASE_URL` para crear esquema.
3. Ejecutar migracion:

```bash
pip install -r requirements.txt
set DATABASE_URL=postgresql://erp_user:erp_pass@127.0.0.1:5432/erp_db
set SQLITE_PATH=C:\ruta\mbarete_erp.sqlite3
python scripts/migrate_sqlite_to_postgres.py
```

4. Validar datos y luego hacer deploy con `DATABASE_URL` en Coolify.

## Despliegue en Coolify

1. Crear recurso desde GitHub.
2. Elegir Docker Compose con `docker-compose.coolify.yml`.
3. Cargar variables (`MBARETE_SECRET_KEY` y opcionalmente `DATABASE_URL`).
4. Desplegar.

## Desarrollo local

```bash
pip install -r requirements.txt
python app.py
```

## Healthcheck

- `GET /health`

Respuesta esperada:

```json
{"status":"ok","app_version":"3.5.1","schema_version":"3.6.0"}
```
