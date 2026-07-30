# 13 — Estado actual

## Versión

0.12.0-master-backlog

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
- `DBI-DATA-003`: fábrica aislada de sesiones DBI.
- `DBI-DATA-004`: repositorios DBI y unidad de trabajo offline.
- `DBI-AUTH-001`: política de autorización DBI offline.

## Último ticket completado

`DBI-AUTH-001` — Política de autorización DBI offline.

- Issue: #26.
- Pull request: #27.
- Estado: completado.
- Commit integrado en `main`:
  `21346aeb7bf568fba97ca0c4fa7364b12b4670df`.
- GitHub Actions de cierre `30500300967`: seis de seis trabajos aprobados.
- Conexiones externas y migraciones online: cero.

## Ticket actual

`DBI-PLAN-001` — Backlog maestro verificable.

- Issue: #28.
- Rama: `feat/DBI-PLAN-001-backlog-maestro`.
- Base: `main` en `21346aeb7bf568fba97ca0c4fa7364b12b4670df`.
- Estado: en revisión.
- Archivos previstos: cuatro documentos; uno nuevo y tres modificados.
- Código funcional, dependencias y workflow modificados: cero.
- Conexiones externas, migraciones y despliegues: cero.
- SHA de planificación validado:
  `90cd0bc6da7d4aa24e41d1694a543e2033df024e`.
- Validación estructural offline: 35 tickets únicos, 79 dependencias válidas,
  cero ciclos y cobertura transitiva de los otros 34 tickets desde UAT.
- Markdownlint: cuatro documentos, cero errores.
- GitHub Actions `30502586256`: seis de seis trabajos aprobados.

## Backlog operativo

- Hito 9, plano de control y persistencia: Issue #29.
- Hito 10, almacenamiento, cola y worker: Issue #30.
- Hito 11, producto agrícola, dashboard y PWA: Issue #31.
- Hito 12, migración controlada del bot: Issue #32.
- Hito 13, operación y producción: Issue #33.
- Próximo ticket ejecutable, `DBI-AUTH-002`: Issue #34.

Los Issues de hito son rastreadores y no representan funciones implementadas.
`DBI-AUTH-002` permanece pendiente hasta cerrar `DBI-PLAN-001`.

## Próximo paso

Validar y revisar `DBI-PLAN-001`. Después de su fusión, iniciar
`DBI-AUTH-002` en una rama independiente para resolver identidad y membresías
DBI completamente offline.

## Riesgos heredados abiertos

- El backend importado continúa usando `DATABASE_URL`.
- La política DBI no está integrada a FastAPI y no existe una autoridad
  persistida de membresías.
- Alembic heredado conserva tres cabezas: `20260411_01`, `2cec060d9aa4` y
  `7ce73aae44ce`.
- El middleware de suscripción permite continuar ante varias excepciones.
- El bot depende actualmente de Green API y Google Sheets.
- El motor geoespacial depende de PyTorch, GDAL y almacenamiento local.
- El frontend mantiene 115 avisos ESLint como línea base.
- Las vulnerabilidades de dependencias inventariadas siguen pendientes de
  `DBI-SEC-002`.
- Rendimiento, volumen de ortofotos y costos no tienen todavía línea base.
- Los 35 tickets futuros son planificación y requieren aceptación individual.

## No realizado todavía

- No se ha creado una base PostgreSQL/PostGIS DBI.
- No se han creado roles `dbi_migrator`, `dbi_app` o `dbi_readonly`.
- No se ha habilitado PostGIS.
- Los modelos y migraciones DBI no se han aplicado a una base.
- No se ha conectado el backend heredado al entorno DBI.
- La fábrica, repositorios y autorización DBI no están integrados con FastAPI.
- No existe autoridad persistida para principales, membresías o permisos DBI.
- No existe API operativa de fincas, lotes, campañas, trabajos o activos.
- No existe almacenamiento privado, cola, broker, productor o consumidor.
- El adaptador del worker no ejecuta el pipeline ni resuelve activos.
- El mapa cronológico no consulta persistencia ni contiene capas reales.
- Agrometeorología, inspecciones, producción, empacadora, biblioteca técnica y
  aprobación agronómica no están implementadas.
- El módulo SST y el bot no usan DBI como fuente canónica.
- No existen registro operativo de modelos, promoción Champion/Challenger,
  observabilidad, pruebas de capacidad, DR o UAT integral.
- No se han cambiado Green API, Google Sheets, Render o la lógica conversacional
  del bot.
- No se han actualizado o promovido modelos de IA.
