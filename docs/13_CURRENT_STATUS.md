# 13 — Estado actual

## Versión

0.11.0-dbi-authorization

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

- Issue: #26
- Pull request: #27
- Estado: completado
- SHA de implementación validado: `86db0a393fe13bce26b9faf6e87265ce6fc26b0e`.
- SHA final validado: `2f6a4aacff37c5fbda89a463a2013bb2ccf4a66f`.
- GitHub Actions `30497480322` y `30497741123`: seis de seis trabajos aprobados en cada ejecución.
- Diff: siete archivos; tres añadidos y cuatro modificados.
- Conexiones externas y migraciones online: cero.

## Ticket actual

Ninguno.

## Próximo paso

Definir el próximo incremento de DALGORO Banana Intelligence mediante un ticket
separado. Resolver identidad y pertenencias DBI, integrar el ciclo de vida
FastAPI, crear endpoints o conectar una base real continúa requiriendo
aprobación explícita y tickets independientes.

## Riesgos heredados abiertos

- El backend importado continúa usando `DATABASE_URL`.
- La política DBI todavía no está integrada a un ciclo de vida FastAPI y la
  resolución canónica de identidad y pertenencia continúa pendiente.
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
- La fábrica de sesiones DBI no está integrada con `app/main.py`; los
  repositorios y la unidad de trabajo tampoco se usan para abrir conexiones.
- La política de autorización no resuelve contextos desde JWT, usuarios,
  empresas o membresías persistidas.
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
