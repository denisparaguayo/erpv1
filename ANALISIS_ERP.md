# Análisis técnico del ERP (Mbarete ERP)

## 1) Resumen ejecutivo

El proyecto es un ERP vertical para agencia digital, construido con **Flask + SQLite**, con un alcance funcional sólido para operación diaria (clientes, proyectos, presupuestos, pagos, renovaciones y archivos). La aplicación está lista para despliegue en VPS/Coolify y tiene utilidades de persistencia y backup.

Sin embargo, a nivel de arquitectura y seguridad, el riesgo operativo crece si se usa en producción con múltiples usuarios o datos sensibles. Los principales puntos a corregir son: **ausencia de autenticación/autorización**, **descarga de archivos sin validación de ruta**, **datos sensibles almacenados en texto plano**, y **tareas de inicialización de DB ejecutadas por request**.

## 2) Qué está bien

- Cobertura funcional integral del flujo comercial (cliente → presupuesto → proyecto → cobro/renovación).
- Esquema SQL amplio y relativamente consistente en claves foráneas.
- Inicialización automática de entorno de datos y base al primer arranque.
- Healthcheck disponible para operación en contenedores.
- Generación de PDF y organización de carpetas por proyecto.

## 3) Riesgos y hallazgos críticos

### 3.1 Seguridad de acceso (crítico)

- No se observa capa de login/roles/permisos en rutas de negocio.
- Esto implica que cualquier acceso HTTP al servicio podría leer/modificar datos si no hay controles externos estrictos (VPN/reverse proxy con auth).

### 3.2 Descarga de archivos por ruta arbitraria (crítico)

- El endpoint `/download` recibe `path` por query string y lo pasa a `send_file()` sin validar si pertenece a un directorio permitido.
- Esto abre posibilidad de exfiltración de archivos del servidor (path traversal lógico por input confiado).

### 3.3 Secretos y credenciales en texto plano (alto)

- Se guardan credenciales de dominio/hosting directamente en columnas del proyecto y en archivos TXT de proyecto.
- Riesgo de fuga por backup, acceso filesystem o error operativo.

### 3.4 Inicialización de DB en cada request (medio)

- `init_db()` y `ensure_defaults()` se ejecutan en `before_request` (una vez por request por contexto `g`), no una sola vez al arranque del proceso.
- Aunque funcionalmente tolerable en baja carga, agrega latencia y trabajo repetido de schema check.

### 3.5 Escalabilidad limitada por SQLite (medio)

- SQLite es válido para baja concurrencia, pero tendrá límites al crecer usuarios/escrituras simultáneas.
- Falta estrategia de migración/modeo de conexión para escenario multiusuario real.

## 4) Deuda técnica / mantenibilidad

- `app.py` concentra casi toda la lógica (rutas + reglas + utilidades), dificultando pruebas unitarias y evolución.
- No se evidencian suites de test automatizadas.
- Falta separación por capas (routes/services/repositories/schemas/forms).

## 5) Recomendaciones priorizadas

## Prioridad P0 (inmediata)

1. Implementar autenticación y control de sesión (mínimo: login con hash seguro + protección de rutas).
2. Proteger formularios con CSRF.
3. Corregir `/download` para permitir solo archivos dentro de roots autorizados (`PROJECTS_ROOT`, `BACKUPS_ROOT`, etc.) y normalizar rutas.
4. Remover secretos hardcodeados/default débiles en producción (obligar `MBARETE_SECRET_KEY` fuerte).

## Prioridad P1 (corto plazo)

5. Cifrar o externalizar credenciales de dominio/hosting (ideal: secret manager; mínimo: cifrado en reposo).
6. Mover `init_db/ensure_defaults` a una fase de startup o comando CLI de migración/seed.
7. Agregar logging estructurado y auditoría mínima de acciones sensibles.
8. Añadir índices SQL para búsquedas frecuentes y dashboards.

## Prioridad P2 (evolución)

9. Modularizar `app.py` en blueprint por dominio (`clients`, `projects`, `billing`, `settings`).
10. Incorporar tests (al menos smoke + rutas críticas + reglas de negocio).
11. Plan de migración a PostgreSQL para operación multiusuario.

## 6) Diagnóstico de arquitectura actual

- **Stack**: Flask monolítico, SQLite, templates server-side.
- **Persistencia**: buena para single-instance; frágil para alta concurrencia.
- **Operación**: docker/coolify friendly.
- **Seguridad**: principal área de riesgo.
- **Escalabilidad**: aceptable para etapa inicial, insuficiente para crecimiento sostenido.

## 7) Conclusión

El ERP está bien encaminado en términos de producto y flujo operativo. Para uso serio en producción, el foco debe pasar de “funcionalidad” a “endurecimiento” (security hardening) y mantenibilidad. Si se ejecuta un plan en 2–4 semanas con foco en P0/P1, puede quedar en un nivel robusto para operación profesional de pequeña/mediana escala.
