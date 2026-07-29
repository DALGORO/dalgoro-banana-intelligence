# 13 — Estado actual

## Versión

0.8.0-asset-persistence

## Terminado

- Estructura inicial del monorepositorio.
- Importación limpia de los tres sistemas.
- Exclusión inicial de secretos y archivos generados.
- Documentos maestros iniciales.
- CI básica.
- `DBI-SEC-001`: auditoría de secretos, dependencias y estructura importada.
- `DBI-CI-002`: integración continua modular y verificable.
- `DBI-REPO-001`: limpieza controlada de copias, respaldos y artefactos.
- `DBI-ARC-001`: arquitectura objetivo, límites y contratos de integración.
- `DBI-DATA-001`: base DBI aislada e historial Alembic independiente.
- `DBI-MAP-001`: interfaz cronológica de mapas y contrato v1.
- `DBI-DATA-002`: persistencia mínima de finca, lote y campaña.
- `DBI-JOB-001`: contratos v1 y máquina de estados geoespacial.
- `DBI-JOB-002`: persistencia offline de trabajos e intentos.
- `DBI-ASSET-001`: persistencia offline de activos y artefactos.

## Último ticket completado

`DBI-ASSET-001` — Persistencia offline de activos y artefactos.

- Issue: #20
- Pull request: #21
- Estado: completado
- SHA final validado: `e43ff9e743fbd0a472b66cd1cba9a6c08075a074`.
- GitHub Actions `30473493853`: seis de seis trabajos aprobados.
- Diff: 11 archivos; cuatro añadidos y siete modificados.
- Conexiones externas y migraciones online: cero.

## Ticket actual

Ninguno.

## Próximo paso

Seleccionar el siguiente incremento arquitectónico desde `main`. Crear una
sesión, repositorio, endpoint, cola, almacenamiento o ejecución del worker
continúa requiriendo otro ticket y aprobación explícitos.

## Riesgos heredados abiertos

- El backend importado continúa usando `DATABASE_URL`.
- DBI todavía no dispone de motor, sesión o repositorio de acceso.
- Alembic heredado conserva tres cabezas: `20260411_01`, `2cec060d9aa4` y
  `7ce73aae44ce`.
- El middleware de suscripción permite continuar ante varias excepciones.
- El bot depende actualmente de Green API y Google Sheets.
- El motor geoespacial depende de PyTorch, GDAL y almacenamiento local.
- El frontend mantiene 115 avisos ESLint como línea base.
- Las vulnerabilidades de dependencias inventariadas siguen pendientes de
  tickets específicos.

## No realizado todavía

- No se ha creado una base PostgreSQL/PostGIS DBI.
- No se han creado roles `dbi_migrator`, `dbi_app` o `dbi_readonly`.
- No se ha habilitado PostGIS.
- Los modelos y la migración del dominio agrícola no se han aplicado a una base.
- No se ha conectado el backend heredado al entorno DBI.
- Los esquemas de trabajos e intentos existen, pero no se han aplicado a una base.
- Los modelos de activos y artefactos existen, pero no se han aplicado a una
  base ni conectado a almacenamiento; no se persisten hallazgos.
- No existe cola, broker, productor, consumidor o almacenamiento privado.
- El adaptador del worker no ejecuta el pipeline ni resuelve activos.
- El mapa cronológico todavía no consulta persistencia y no dispone de
  geometrías, tiles o fechas reales.
- No se han cambiado Green API, Google Sheets o Render.
- No se ha cambiado la lógica conversacional del bot.
- No se han actualizado modelos de IA.
