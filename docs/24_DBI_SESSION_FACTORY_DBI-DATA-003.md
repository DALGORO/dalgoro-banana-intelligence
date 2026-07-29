# 24 — Fábrica de sesiones DBI-DATA-003

## Identificación

- Ticket: `DBI-DATA-003`
- Issue: #22
- Fecha: 2026-07-29
- Rama: `feat/DBI-DATA-003-sesiones-dbi-aisladas`
- Base: `main` en `41880374cfa1a7dfdb4f9b34ec79c70ad10a259d`
- Pull request: #23
- Estado: completado

## Objetivo

Introducir una frontera transaccional explícita para DALGORO Banana
Intelligence sin reutilizar la sesión heredada, abrir conexiones durante la
importación ni incorporar reglas de negocio o infraestructura operativa.

## Evidencia de partida

La revisión de `main` confirmó:

- `app/db/dbi_config.py` valida ambiente, controlador y nombre de base;
- `app/db/session.py` crea el motor heredado desde `DATABASE_URL` al importar;
- los siete modelos DBI existen sobre `DBIBase`;
- el historial DBI llega a `dbi_0004_assets_artifacts`;
- no existe motor, fábrica de sesiones, repositorio o endpoint DBI;
- SQLAlchemy 2.0.44 y psycopg 3.2.12 ya están fijados;
- CI valida configuración, metadatos y SQL Alembic solo en modo offline.

No se consultaron PostgreSQL, Render, almacenamiento, colas o servicios
externos.

## Decisión

La sesión DBI se construye exclusivamente mediante funciones explícitas:

1. `create_dbi_engine()` recibe o carga una configuración ya validada;
2. `create_dbi_session_factory()` liga una fábrica al motor recibido;
3. `dbi_session_scope()` abre una sesión por operación;
4. el bloque exitoso confirma la transacción;
5. cualquier excepción provoca rollback y se propaga;
6. la sesión se cierra siempre.

No se declara un motor, una fábrica o una sesión global. Importar el módulo no
lee variables, crea recursos ni abre conexiones.

## Implementación por archivo

### `apps/platform-web/backend/app/db/dbi_session.py`

#### `create_dbi_engine()`

- reutiliza `load_dbi_database_config()`;
- pasa el objeto `URL` validado directamente a SQLAlchemy;
- activa `pool_pre_ping=True`;
- no llama `connect()` ni conserva el motor globalmente.

Crear un `Engine` configura un punto de acceso diferido. La primera conexión
solo podrá ocurrir cuando un ticket posterior integre el ciclo de vida de la
aplicación y use una sesión.

#### `create_dbi_session_factory()`

- exige un motor explícito;
- configura `autoflush=False`;
- conserva objetos después del commit con `expire_on_commit=False`;
- no importa `SessionLocal` ni configuración heredada.

#### `dbi_session_scope()`

- crea una sesión por invocación;
- entrega la sesión al bloque autorizado;
- ejecuta commit solo si el bloque y el commit terminan correctamente;
- ejecuta rollback si falla el bloque o el commit;
- vuelve a lanzar la excepción original;
- ejecuta cierre en todos los caminos.

### `.github/scripts/ci_dbi_session_factory.py`

La barrera usa dobles y parches para comprobar:

- importación sin construir motor o fábrica;
- rechazo de configuración heredada antes de crear un motor;
- paso del objeto `URL` validado y `pool_pre_ping`;
- enlace exacto entre motor y fábrica;
- orden `commit → close` en éxito;
- orden `rollback → close` ante error del bloque;
- orden `commit → rollback → close` si falla el commit;
- propagación de excepciones;
- ausencia de conexión, sesión heredada, cola, almacenamiento o worker.

### `.github/workflows/ci.yml`

El trabajo backend ejecuta la barrera después del control de aislamiento DBI.
La prueba no recibe credenciales y no necesita PostgreSQL.

## Límites

Este ticket no integra la fábrica con `app/main.py`. El llamador futuro será
responsable de crear y disponer el motor dentro de un ciclo de vida aprobado.

Tampoco define:

- repositorios o unidad de trabajo de dominio;
- dependencia FastAPI;
- autorización por tenant, organización o finca;
- endpoints de finca, activos o trabajos;
- cola, broker, productor o consumidor;
- almacenamiento de objetos o URLs firmadas;
- PostGIS, geometrías o tiles;
- ejecución del worker o del pipeline.

## Riesgos y controles

| Riesgo | Control |
|---|---|
| Reutilizar la base heredada | Solo se importa `dbi_config` |
| Crear recursos al importar | No existen objetos globales |
| Confirmar después de un error | Commit está después del bloque |
| Dejar transacción fallida | Rollback ante bloque o commit fallido |
| Filtrar credenciales | Se pasa `URL`; no se registra ni renderiza |
| Conectar CI a PostgreSQL | Constructores sustituidos por dobles |
| Ocultar una excepción | Rollback seguido de propagación |
| Dejar sesiones abiertas | Cierre dentro de `finally` |

## Pruebas y criterios de aceptación

| Criterio | Evidencia prevista |
|---|---|
| Configuración DBI exclusiva | Cargador existente y prueba negativa |
| Importación diferida | Constructores no invocados |
| Motor explícito | URL validada y `pool_pre_ping=True` |
| Fábrica aislada | Enlace solo al motor recibido |
| Commit correcto | Secuencia exitosa verificada |
| Rollback correcto | Error de bloque y de commit verificados |
| Cierre garantizado | Ambos caminos verificados |
| Sin servicios | Ninguna llamada de conexión |
| Compatibilidad | Barreras DBI y smoke test del backend |
| Documentación | Arquitectura, decisión y estado actualizados |

## Validaciones ejecutadas

| Verificación local | Resultado |
|---|---|
| `pip check` del entorno mínimo fijado | Aprobado |
| `compileall` de aplicación y barrera nueva | Aprobado |
| Dominio agrícola DBI offline | Aprobado |
| Contrato API–worker offline | Aprobado |
| Persistencia de trabajos offline | Aprobado |
| Persistencia de activos y artefactos offline | Aprobado |
| Fábrica y ciclo transaccional con dobles | Aprobado |
| Markdownlint de cuatro documentos | Cero incidencias |

La evidencia definitiva es la ejecución final de GitHub Actions sobre el SHA
validado. Las pruebas locales no sustituyen esa ejecución.

## Validación remota

GitHub Actions `30477179411` aprobó seis de seis trabajos sobre el SHA final
validado `80c0986598ca8f4d416f9e498fdbc8059d8f0b0c`:

- backend con instalación completa, ambos grafos Alembic, aislamiento,
  fábrica de sesiones, dominio, mapa, contratos, persistencia y healthcheck;
- frontend con instalación, lint y build de producción;
- bot con instalación, compilación y smoke test;
- motor de densidad con dependencias, compilación, importaciones y CLI;
- higiene de artefactos y detección de secretos.

El diff contiene siete archivos —tres añadidos y cuatro modificados—, dos
commits y cero retraso frente a `main`. No se abrió una conexión, no se ejecutó
una migración online y no se invocó almacenamiento, cola o pipeline.

## Exclusiones confirmadas

- No se modifica `app/db/session.py`.
- No se modifica `app/main.py`.
- No se crean o alteran tablas y migraciones.
- No se ejecuta Alembic online.
- No se consulta o modifica PostgreSQL.
- No se crean repositorios o endpoints.
- No se conecta almacenamiento, cola, PostGIS o worker.
- No se procesa una ortofoto.
- No se descarga o actualiza un modelo de IA.
- No se cambia Green API, Google Sheets, Render o el bot.
