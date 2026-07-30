# 29 — Ciclo de vida DBI en FastAPI — DBI-API-001

<!-- markdownlint-disable MD013 -->

## Identificación

- Ticket: `DBI-API-001`.
- Issue: #37.
- Pull request: #38.
- Rama: `feat/DBI-API-001-ciclo-vida-fastapi`.
- Base: `main` en `e5787f1d22c6eff676c10982c4b5d932ea19a50d`.
- Estado: listo para revisión final.

## Objetivo cumplido

FastAPI administra ahora un runtime DBI explícito y separado de la sesión heredada. El runtime crea el motor y la fábrica de sesiones únicamente cuando `DBI_ENVIRONMENT` y `DBI_DATABASE_URL` están configuradas conjuntamente; la importación de la aplicación no abre conexiones.

La dependencia `get_dbi_session` obtiene la fábrica desde `application.state`, crea la sesión solo cuando una operación la solicita, ejecuta rollback si la operación falla y garantiza el cierre. La dependencia `get_dbi_access_context` transforma la identidad autenticada heredada en una referencia opaca y delega la autoridad de membresías, permisos y ámbitos al resolvedor aprobado en `DBI-AUTH-002`.

## Cambios funcionales

- `apps/platform-web/backend/app/dbi/runtime.py`
  - Runtime sin objetos globales de motor o sesión.
  - Inicio opcional y validado por configuración DBI exclusiva.
  - Disposición explícita del motor durante el cierre de FastAPI.
  - Denegación cerrada cuando la fábrica no está disponible.

- `apps/platform-web/backend/app/dbi/dependencies.py`
  - Dependencia diferida de sesión DBI.
  - Rollback ante excepción y cierre garantizado.
  - Resolución de `DBIAccessContext` con `DBIIdentityRepository`.
  - Cabecera explícita `X-DBI-Tenant`.
  - Respuestas uniformes `403` y `503` sin enumerar pertenencias.

- `apps/platform-web/backend/app/main.py`
  - `lifespan` de FastAPI para iniciar y detener `DBIRuntime`.
  - Conservación del router, middleware, healthcheck y sesión heredados.

- `.github/scripts/ci_dbi_fastapi_lifecycle.py`
  - Validación completamente offline del ciclo de vida.
  - Importación y healthcheck sin configuración DBI.
  - Inicio y disposición con dobles, sin conexión.
  - Cierre y rollback de sesiones.
  - Denegación cuando DBI no está habilitado.
  - Barreras estáticas contra sesión, modelos y conexión heredados.

- `.github/workflows/ci.yml`
  - Nueva barrera backend posterior a identidad y membresías.

## Auditoría de aislamiento

Se confirmó que:

1. `runtime.py` no importa `User`, `Company` ni `app.db.session`.
2. `dependencies.py` no importa modelos heredados ni la sesión heredada.
3. La autenticación heredada solo entrega un objeto autenticado mediante la dependencia existente; el dominio DBI recibe únicamente su identificador convertido a texto.
4. `DBI_DATABASE_URL` no reutiliza `DATABASE_URL`.
5. Construir el motor SQLAlchemy no abre una conexión; ninguna prueba invoca `connect()`.
6. No se aplicaron migraciones, no se sembraron datos y no se consultaron servicios externos.
7. No se crearon endpoints CRUD o funcionales DBI.
8. No se modificaron frontend, bot, motor geoespacial, Google Sheets, Green API o Render.

## Incidencias detectadas y correcciones

### Importación heredada en la prueba

La primera ejecución falló porque `app.core.config` exige `DATABASE_URL` y `JWT_SECRET` al importarse. La prueba ahora define valores locales exclusivos de CI antes de importar la aplicación. No se usan para DBI ni abren una conexión.

### Falso positivo de aislamiento

La segunda ejecución falló porque una búsqueda textual de `DATABASE_URL` coincidía dentro de `DBI_DATABASE_URL_ENV_VAR`. Se reemplazó por una expresión regular que detecta únicamente el identificador heredado independiente y permite el nombre DBI autorizado.

Ambos fallos pertenecían a la nueva barrera de CI y no a las demás áreas del monorepositorio.

## Evidencia

- Ejecución inicial del PR: Actions `30546959302`, fallo controlado en la nueva barrera.
- Ejecución posterior: Actions `30547685407`, falso positivo detectado en la barrera estática.
- Ejecución definitiva funcional: Actions `30548982857`, seis de seis trabajos aprobados.
- Backend definitivo: compilación, grafos Alembic, aislamiento, sesiones, repositorios, autorización, identidad, ciclo FastAPI, dominio agrícola, mapa, trabajos, activos y healthcheck aprobados.
- Frontend: lint dentro de la línea base y build aprobados.
- WhatsApp: instalación, compilación y smoke test aprobados.
- Motor geoespacial: instalación, compilación y smoke test aprobados.
- Seguridad: Gitleaks aprobado.
- Higiene del repositorio: aprobada.

## Criterios de aceptación

- [x] FastAPI administra explícitamente los recursos DBI sin sustituir los heredados.
- [x] La sesión DBI se abre solo al atender una dependencia que la requiere.
- [x] Toda sesión DBI termina cerrada y hace rollback cuando corresponde.
- [x] La importación y el healthcheck no abren conexiones DBI.
- [x] `DBIAccessContext` se obtiene mediante la autoridad de `DBI-AUTH-002`.
- [x] Los permisos y ámbitos permanecen cerrados por defecto.
- [x] No existen claves, imports o consultas cruzadas hacia modelos heredados dentro del dominio DBI.
- [x] No se crearon endpoints funcionales DBI.
- [x] CI valida aislamiento, ciclo de vida y regresión sin servicios externos.
- [x] Documentación y evidencia real quedaron registradas.

## Límites preservados

Este incremento no prueba una conexión PostgreSQL real, no aplica el historial Alembic DBI, no crea infraestructura y no habilita operaciones de dominio. Las lecturas autorizadas corresponden a `DBI-API-002`; las escrituras a `DBI-API-003`; la infraestructura y migración online tienen tickets independientes y requieren autorización explícita.
