# 13 — Estado actual

## Versión

0.6.0-analysis-job-contract

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

## Último ticket completado

`DBI-DATA-002` — Persistencia mínima de finca, lote y campaña.

- Issue: #14
- Pull request: #15
- Estado: completado
- Commit fusionado: `b70889179baa031f48124b369fe393a702cbfd81`.
- Conexiones externas y migraciones online: cero.

## Ticket actual

`DBI-JOB-001` — Contratos v1 y máquina de estados geoespacial.

- Issue: #16
- Rama: `feat/DBI-JOB-001-contratos-trabajos-v1`
- Base: `main` en `b70889179baa031f48124b369fe393a702cbfd81`
- Pull request: #17
- Estado: en revisión
- SHA técnico validado: `3425d8254300689fcbeeca330b9ae72d94719a1b`
- GitHub Actions `30462381405`: seis de seis trabajos aprobados

### Alcance

- Contratos estrictos de comando, resultado, manifiesto y hallazgo.
- Máquina de estados pura con idempotencia y reintento autorizado.
- Adaptador del worker basado en biblioteca estándar.
- Paridad de las 17 etapas del pipeline.
- Validación CI completamente offline.

### Exclusiones

- Sin tablas, migraciones, motores o sesiones DBI.
- Sin endpoint, cola, broker, consumidor o almacenamiento de objetos.
- Sin PostGIS, ortofotos, inferencia o ejecución del pipeline.
- Sin cambios en Render, Green API, Google Sheets o modelos de IA.

## Próximo paso

Completar la ejecución final de GitHub Actions sobre el SHA documental y
revisar el Draft PR #17. La cola, persistencia operativa, almacenamiento y
ejecución del worker requieren tickets posteriores y aprobación explícita.

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
- No se persisten trabajos, intentos, activos, artefactos o hallazgos.
- No existe cola, broker, productor, consumidor o almacenamiento privado.
- El adaptador del worker no ejecuta el pipeline ni resuelve activos.
- El mapa cronológico todavía no consulta persistencia y no dispone de
  geometrías, tiles o fechas reales.
- No se han cambiado Green API, Google Sheets o Render.
- No se ha cambiado la lógica conversacional del bot.
- No se han actualizado modelos de IA.
