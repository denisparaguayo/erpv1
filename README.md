# Mbarete ERP · VPS / Coolify Ready

Esta versión está preparada para subir desde tu repo de GitHub a **Coolify** y publicar en:

- `erp.mbarete.digital`

## Qué cambia en esta refactorización

- arranque en **producción** con `gunicorn`
- app escuchando en `0.0.0.0:8000`
- **healthcheck** en `/health`
- datos persistentes fuera del código usando volumen Docker en `/data`
- **creación automática** de la base SQLite al primer arranque
- sin apertura automática de navegador en servidor
- preparada para desplegar desde **GitHub + Coolify**

## Base de datos

La base actual sigue siendo **SQLite**, pero ahora vive en un volumen persistente de Docker:

- `/data/instance/mbarete_erp.sqlite3`

Se crea sola cuando la app arranca por primera vez.

## Estructura persistente en el VPS

Dentro del volumen `/data` la app crea automáticamente:

- `instance/`
- `Proyectos/`
- `uploads/`
- `backups/`
- `settings/`

## Despliegue en Coolify

### Opción recomendada
Usá **Docker Compose** con el archivo:

- `docker-compose.coolify.yml`

### Variables necesarias
Creá en Coolify esta variable:

- `MBARETE_SECRET_KEY`

Ejemplo: una clave larga y aleatoria.

### Dominio
En Coolify configurá el dominio:

- `erp.mbarete.digital`

Y hacé que apunte al servicio `erp` puerto `8000`.

## Flujo recomendado en Coolify

1. crear nuevo recurso desde GitHub
2. elegir **Docker Compose**
3. seleccionar `docker-compose.coolify.yml`
4. cargar la variable `MBARETE_SECRET_KEY`
5. configurar el dominio `erp.mbarete.digital`
6. desplegar

## Desarrollo local

```bash
pip install -r requirements.txt
python app.py
```

## Producción local con Docker

```bash
docker compose -f docker-compose.coolify.yml up --build
```

## Endpoint de salud

- `GET /health`

Respuesta esperada:

```json
{"status":"ok","app_version":"3.5.1","schema_version":"3.5.1"}
```

## Nota importante

Esta refactorización deja el ERP **listo para VPS**.

El siguiente paso natural, cuando quieras escalar más, es migrar de SQLite a PostgreSQL. Pero para publicar ya y trabajar en `erp.mbarete.digital`, esta base queda estable y simple de operar.
