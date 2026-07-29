# 13 — Estado actual

## Versión

0.7.0-analysis-job-persistence

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

## Último ticket completado

`DBI-JOB-001` — Contratos v1 y máquina de estados geoespacial.

- Issue: #16
- Pull request: #17
- Estado: completado
- SHA final validado: `c5820ff6ddc4a774c7d14a8c0716f19c85819fd3`.
- GitHub Actions `30462722323`: seis de seis trabajos aprobados.
- Diff: 10 archivos; seis añadidos y cuatro modificados.
- Conexiones externas y ejecución del pipeline: cero.

## Ticket actual

`DBI-JOB-002` — Persistencia offline de trabajos e intentos.

- Issue: #18
- Rama: `feat/DBI-JOB-002-persistencia-trabajos-intentos`
- Estado: en implementación

## Próximo paso

Publicar y validar la migración y los metadatos exclusivamente en modo offline.
Crear una sesión, repositorio, endpoint, cola, almacenamiento o ejecución del
worker continúa requiriendo un ticket y aprobación explícitos.

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
