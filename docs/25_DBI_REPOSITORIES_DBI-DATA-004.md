# 25 — Repositorios y unidad de trabajo DBI-DATA-004

## Identificación

- Ticket: `DBI-DATA-004`
- Issue: #24
- Fecha: 2026-07-29
- Rama: `feat/DBI-DATA-004-repositorios-dbi-offline`
- Base: `main` en `1e57631c19c0546d4d7e5343c4ff84eae28b7748`
- Pull request: #25
- Estado: en revisión

## Objetivo

Introducir acceso DBI explícito, reutilizable y acotado por ámbito sin integrar
FastAPI, abrir conexiones o añadir infraestructura operativa. El cambio usa la
frontera transaccional de `DBI-DATA-003` y mantiene separados repositorios,
autorización y transporte HTTP.

## Evidencia de partida

La revisión de `main` confirmó:

- siete modelos DBI sobre metadatos independientes;
- cuatro revisiones DBI posteriores a la línea base;
- una fábrica explícita de motor y sesiones;
- `dbi_session_scope()` como autoridad de commit, rollback y cierre;
- ausencia de repositorios, unidad de trabajo y dependencia FastAPI DBI;
- ausencia de base DBI real, almacenamiento, cola y ejecución del worker.

No se consultaron PostgreSQL, Render, almacenamiento de objetos, colas o
servicios externos.

## Decisión

La capa de acceso queda dividida en dos responsabilidades:

1. los repositorios construyen consultas SQLAlchemy y añaden entidades a la
   sesión recibida;
2. la unidad de trabajo liga todos los repositorios a una misma sesión;
3. `dbi_session_scope()` conserva el control exclusivo de commit, rollback y
   cierre;
4. ninguna lectura de repositorio puede ejecutarse sin un ámbito explícito;
5. autorización de identidad y pertenencia continúa reservada para otro
   ticket.

`organization_ref` delimita finca, lote y campaña. `tenant_ref` delimita
trabajos, intentos, activos de entrada y artefactos. Este alcance reduce el
riesgo de consultas globales, pero no sustituye una decisión de autorización.

## Implementación por archivo

### `apps/platform-web/backend/app/dbi/repositories.py`

El módulo añade siete repositorios:

- `FarmRepository`;
- `PlotRepository`;
- `CampaignRepository`;
- `AnalysisJobRepository`;
- `AnalysisJobAttemptRepository`;
- `AnalysisInputAssetRepository`;
- `AnalysisArtifactRepository`.

Todos reciben una `Session` explícita. `add()` incorpora una entidad a la
transacción actual y devuelve la misma instancia, sin confirmar, revertir,
cerrar o eliminar.

Las lecturas aplican las siguientes barreras:

| Repositorio | Ámbito obligatorio | Relación usada |
| --- | --- | --- |
| Finca | `organization_ref` | Columna propia |
| Lote | `organization_ref` | Unión con finca |
| Campaña | `organization_ref` | Unión con finca |
| Trabajo | `tenant_ref` | Columna propia |
| Intento | `tenant_ref` | Unión con trabajo |
| Activo de entrada | `tenant_ref` | Columna propia |
| Artefacto | `tenant_ref` | Unión con trabajo |

La consulta idempotente de trabajo exige conjuntamente `tenant_ref` y
`request_id`, en concordancia con
`uq_dbi_analysis_jobs_tenant_request`.

### `apps/platform-web/backend/app/dbi/unit_of_work.py`

`DBIUnitOfWork.bind()` construye los siete repositorios sobre la misma sesión.
`flush()` sincroniza cambios sin confirmar la transacción.

`dbi_unit_of_work_scope()` delega la transacción completa a
`dbi_session_scope()`. Por tanto:

- una salida exitosa ejecuta commit y cierre;
- una excepción ejecuta rollback, cierre y propagación;
- no existe una segunda implementación transaccional;
- importar el módulo no crea motor, fábrica, sesión o conexión.

### `.github/scripts/ci_dbi_repositories.py`

La barrera usa sesiones y resultados falsos para comprobar:

- tablas y valores de ámbito en cada sentencia;
- uniones de lote y campaña con finca;
- uniones de intento y artefacto con trabajo;
- idempotencia por `tenant_ref + request_id`;
- siete operaciones `add()` sin efectos transaccionales;
- una sesión compartida por todos los repositorios;
- secuencia `flush → commit → close`;
- secuencia `rollback → close` ante error;
- ausencia de conexión, sesión heredada e infraestructura.

Las sentencias se compilan con el dialecto PostgreSQL de SQLAlchemy. Compilar
una sentencia no crea un motor ni abre una conexión.

### `.github/workflows/ci.yml`

El trabajo backend ejecuta la nueva barrera después de validar la fábrica de
sesiones DBI. No recibe credenciales y no necesita PostgreSQL.

## Límites

Este ticket no implementa:

- integración con `app/main.py` o ciclo de vida FastAPI;
- dependencia de sesión para rutas;
- autorización por identidad, tenant, organización, finca o lote;
- endpoints o esquemas HTTP nuevos;
- cambios de estado de trabajos o intentos;
- eliminaciones o consultas de listado;
- tablas, migraciones, roles o una base DBI real;
- almacenamiento de objetos o URLs temporales;
- cola, productor, consumidor o worker;
- PostGIS, geometrías, tiles o mapa conectado;
- cambios de Green API, Google Sheets, Render o el bot.

## Riesgos y controles

| Riesgo | Control |
| --- | --- |
| Lectura transversal | Ámbito obligatorio en cada método |
| Lote fuera de organización | Unión explícita con finca |
| Intento fuera de tenant | Unión explícita con trabajo |
| Doble control transaccional | Solo `dbi_session_scope()` confirma o revierte |
| Commit dentro del repositorio | Barrera estática y doble de sesión |
| Confundir ámbito con autorización | Autorización permanece excluida |
| Eludir estados del trabajo | No existen métodos de transición |
| Conectar durante CI | No se construye motor ni se llama `connect()` |

## Pruebas y criterios de aceptación

| Criterio | Evidencia prevista |
| --- | --- |
| Siete repositorios explícitos | Construcción sobre sesión falsa |
| Lecturas agrícolas acotadas | SQL compilado con organización |
| Lecturas de análisis acotadas | SQL compilado con tenant |
| Idempotencia | Tenant y solicitud en una sentencia |
| Sin transacciones internas | Cero eventos después de `add()` |
| Sesión única | Siete repositorios con el mismo doble |
| Commit correcto | Secuencia exitosa verificada |
| Rollback correcto | Error propagado y secuencia verificada |
| Sin servicios | Barrera estática y ninguna conexión |
| Compatibilidad | Barreras DBI y smoke test del backend |

## Validaciones locales

| Verificación | Resultado |
| --- | --- |
| `compileall` de módulos y barrera nueva | Aprobado |
| Consultas acotadas compiladas offline | Aprobado |
| Idempotencia de solicitudes | Aprobado |
| Operaciones `add()` sin commit | Aprobado |
| Unidad de trabajo exitosa | Aprobado |
| Unidad de trabajo fallida | Aprobado |
| Límites de código fuente | Aprobado |

La evidencia definitiva será la ejecución completa de GitHub Actions sobre el
SHA final. Las pruebas locales no sustituyen esa ejecución.

## Validación remota

GitHub Actions `30493838198` aprobó seis de seis trabajos sobre el SHA inicial
validado `99da89eb084e56c1b094f29a734e037929d19a12`:

- backend con instalación completa, ambos grafos Alembic, aislamiento, fábrica,
  repositorios, dominio, contratos, persistencia y healthcheck;
- frontend con instalación, lint y build de producción;
- bot con instalación, compilación y smoke test;
- motor de densidad con dependencias, compilación, importaciones y CLI;
- higiene de artefactos y detección de secretos.

El diff contiene ocho archivos —cuatro añadidos y cuatro modificados—, un commit
y cero retraso frente a `main`. No se abrió una conexión, no se ejecutó una
migración online y no se invocó almacenamiento, cola o pipeline.

La ejecución definitiva corresponderá al commit documental que registre esta
evidencia.

## Exclusiones confirmadas

- No se modifica `app/db/session.py`.
- No se modifica `app/main.py`.
- No se modifican modelos, tablas o migraciones.
- No se ejecuta Alembic online.
- No se consulta o modifica PostgreSQL.
- No se crean endpoints o autorización.
- No se conecta almacenamiento, cola, PostGIS o worker.
- No se procesa una ortofoto.
- No se descarga o actualiza un modelo de IA.
- No se cambia el frontend, el mapa o el bot.
