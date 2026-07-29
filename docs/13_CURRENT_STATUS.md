# 13 — Estado actual

## Versión

0.3.0-data-isolation

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

## Último ticket completado

`DBI-ARC-001` — Arquitectura objetivo, límites y contratos de integración.

## Ticket actual

`DBI-DATA-001` — Base DBI aislada e historial Alembic independiente.

- Issue: #10
- Rama: `feat/DBI-DATA-001-aislamiento-base-dbi`
- Pull request: #11
- Estado: en revisión
- Base: `main` en `59652b8afe97ca59991547c1d39ab4fd56bcb38e`

### Alcance

- Añadir configuración exclusiva mediante `DBI_ENVIRONMENT` y
  `DBI_DATABASE_URL`.
- Validar PostgreSQL y nombres de base autorizados por ambiente.
- Crear metadatos SQLAlchemy DBI independientes.
- Crear un entorno Alembic DBI con tabla de versión propia.
- Iniciar el historial en una revisión vacía y no destructiva.
- Añadir pruebas CI offline para impedir mezcla con la base heredada.

### Archivos involucrados

- `apps/platform-web/backend/app/db/dbi_config.py`
- `apps/platform-web/backend/app/db/dbi_base.py`
- `apps/platform-web/backend/dbi_alembic.ini`
- `apps/platform-web/backend/dbi_alembic/`
- `apps/platform-web/backend/.env.example`
- `.github/scripts/ci_dbi_database_isolation.py`
- `.github/workflows/ci.yml`
- `docs/01_SYSTEM_ARCHITECTURE.md`
- `docs/06_TECHNICAL_DECISIONS.md`
- `docs/13_CURRENT_STATUS.md`
- `docs/18_DATABASE_ISOLATION_DBI-DATA-001.md`

### Exclusiones

- No se crea ni consulta una base PostgreSQL/PostGIS.
- No se crean extensiones, esquemas, tablas de dominio o roles.
- No se ejecutan migraciones online.
- No se modifica `DATABASE_URL`, `app/core/config.py` o `app/db/session.py`.
- No se modifica el historial heredado `alembic/`.
- No se modifican Render, Green API o Google Sheets.
- No se cambia frontend, bot, motor geoespacial o modelos de IA.

### Validación ejecutada

- Compilación Python de `app`, `alembic`, `dbi_alembic` y el control CI:
  aprobada.
- Dependencias focalizadas: `pip check` aprobado.
- Historial heredado: tres cabezas confirmadas e intactas.
- Historial DBI: raíz y cabeza únicas `dbi_0001_baseline`.
- Matriz de configuración: cuatro ambientes válidos y cinco escenarios de
  rechazo aprobados.
- SQL DBI generado en modo offline con `alembic_version_dbi`.
- SQL offline sin tablas `users`, `companies` o `documents`.
- Ninguna conexión externa ni migración online ejecutada.
- GitHub Actions `30448937826`: seis de seis trabajos aprobados.
- El trabajo backend aprobó instalación completa, dependencias, compilación,
  ambos grafos Alembic, aislamiento DBI, SQL offline y healthcheck.

## Próximo paso

Revisar el Draft PR #11 y fusionarlo únicamente con autorización explícita. La
creación de infraestructura o una migración online queda fuera de este ticket.

## Riesgos heredados abiertos

- El backend importado continúa usando `DATABASE_URL`.
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
- No se han creado modelos o tablas del dominio agrícola.
- No se ha conectado el backend heredado al entorno DBI.
- No existe todavía el dashboard agrícola o el mapa cronológico.
- No se han cambiado Green API, Google Sheets o Render.
- No se ha cambiado la lógica conversacional del bot.
- No se han actualizado modelos de IA.
