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
- `DBI-PLAN-001`: backlog maestro verificable.

## Último ticket completado

`DBI-PLAN-001` — Backlog maestro verificable.

- Issue: #28.
- Pull request: #35.
- Estado: completado.
- SHA de planificación y evidencia previa al cierre:
  `ce8bf771a2fa49ab56228bb1fe8f21c292a1280f`.
- GitHub Actions inicial `30502586256`: seis de seis trabajos aprobados.
- GitHub Actions final `30502931704`: seis de seis trabajos aprobados.
- Validación estructural: 35 tickets únicos, 79 dependencias válidas, cero
  ciclos y cobertura transitiva de los otros 34 tickets desde UAT.
- Código funcional, conexiones externas, migraciones online y despliegues:
  cero.

## Ticket actual

Ninguno.

`DBI-AUTH-002` permanece pendiente en el Issue #34 y será el próximo
incremento ejecutable, siempre en una rama independiente.

## Backlog operativo

- Hito 9, plano de control y persistencia: Issue #29.
- Hito 10, almacenamiento, cola y worker: Issue #30.
- Hito 11, producto agrícola, dashboard y PWA: Issue #31.
- Hito 12, migración controlada del bot: Issue #32.
- Hito 13, operación y producción: Issue #33.
- Próximo ticket ejecutable, `DBI-AUTH-002`: Issue #34.

Los Issues de hito son rastreadores y no representan funciones implementadas.
`DBI-AUTH-002` permanece pendiente hasta iniciar su propio ticket y rama.

## Próximo paso

Iniciar `DBI-AUTH-002` en una rama independiente creada desde el `main` que
integre el PR #35, para resolver identidad y membresías DBI completamente
offline. Este paso no autoriza FastAPI, una base real ni migraciones online.

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
