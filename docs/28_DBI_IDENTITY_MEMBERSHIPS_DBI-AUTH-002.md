# 28 — Identidad y membresías DBI-AUTH-002

## Identificación

- Ticket: `DBI-AUTH-002`.
- Issue: #34.
- Fecha: 2026-07-29.
- Rama: `feat/DBI-AUTH-002-identidad-membresias-offline`.
- Base: `main` en `50fda6bc6c0308f79d21454e92a8a4734ca55898`.
- Pull request: #36.
- Estado: en revisión.

## Objetivo

Persistir la relación canónica entre una identidad autenticada y sus ámbitos
DBI, y construir `DBIAccessContext` desde una autoridad explícita, activa y
consistente. El corte permanece completamente offline y no integra FastAPI,
JWT, una base real o los modelos heredados.

## Evidencia de partida

La revisión de `main` confirmó:

- `DBIAccessContext` y `DBIAuthorizationPolicy` puros y cerrados por defecto;
- siete repositorios DBI sobre una sesión recibida;
- siete tablas DBI y cuatro revisiones posteriores a la línea base;
- una sola cabeza DBI en `dbi_0004_assets_artifacts`;
- tres cabezas heredadas independientes;
- ausencia de principal, membresía, permisos y ámbitos persistidos;
- ausencia de vínculo canónico con `User`, `Company` o roles heredados;
- ausencia de ciclo de vida FastAPI, endpoint y base DBI operativa.

No se consultaron PostgreSQL, Render, almacenamiento, colas, Green API, Google
Sheets, modelos remotos ni datos productivos.

## Decisión

La autoridad se normaliza en cuatro responsabilidades:

1. `DBIPrincipal` asigna un UUID canónico a una `legacy_identity_ref` opaca;
2. `DBIMembership` representa la relación única principal–tenant y su estado;
3. `DBIMembershipPermission` conserva permisos globales de la membresía;
4. `DBIMembershipScope` conserva ámbitos de organización, finca o lote;
5. `DBIIdentityRepository` consulta exclusivamente una sesión recibida;
6. `DBIAccessContextResolver` valida la autoridad y produce el contexto.

Los permisos se separan de los ámbitos porque `DBIAccessContext` usa un conjunto
global de permisos para todos sus ámbitos. Guardar permisos independientes por
organización, finca o lote permitiría combinar accidentalmente un permiso de un
ámbito con la pertenencia de otro.

Una membresía sin filas de ámbito representa acceso solo al tenant. Un ámbito de
finca incorpora su organización y un ámbito de lote incorpora organización y
finca. El resolvedor confirma esas relaciones contra `dbi_farms` y `dbi_plots`
antes de construir el contexto.

## Implementación por archivo

### `apps/platform-web/backend/app/dbi/models/identity.py`

El módulo añade:

- `DBIPrincipal` y estados `active` e `inactive`;
- `DBIMembership` y estados `active`, `inactive` y `revoked`;
- `DBIMembershipPermission`, alineado con los cinco `DBIPermission`;
- `DBIMembershipScope`, con niveles `organization`, `farm` y `plot`;
- referencias recortadas, no vacías y sin comodines;
- restricciones únicas y jerárquicas;
- claves foráneas únicamente entre tablas DBI.

`legacy_identity_ref`, `tenant_ref` y `organization_ref` son referencias opacas.
No existe clave foránea a `users`, `companies` u otra tabla heredada.

### `apps/platform-web/backend/app/dbi/identity.py`

`DBIIdentityRepository` recibe una `Session` y ofrece seis consultas:

- candidatos de principal por referencia heredada;
- membresías por principal y tenant;
- permisos y ámbitos por membresía;
- coincidencia finca–organización;
- coincidencia lote–finca–organización.

`DBIAccessContextResolver` recibe un repositorio. Exige exactamente un principal
y una membresía activos, al menos un permiso reconocido, referencias canónicas
y ámbitos no duplicados. El UUID del principal se convierte en `principal_ref`
del contexto; la referencia heredada no se propaga.

Toda ausencia, duplicidad, inactividad, revocación, permiso desconocido o
jerarquía inconsistente produce el mismo `DBIAccessDenied`.

### `apps/platform-web/backend/app/dbi/models/__init__.py`

Exporta los cuatro modelos y sus enumeraciones sin modificar los siete modelos
anteriores.

### `dbi_alembic/versions/20260729_05_identity_memberships.py`

La revisión `dbi_0005_identity_memberships` desciende directamente de
`dbi_0004_assets_artifacts`. Crea cuatro tablas, índices parciales únicos para
cada nivel de ámbito y restricciones de integridad equivalentes a los modelos.

El `downgrade()` elimina únicamente las cuatro tablas nuevas en orden inverso.
La revisión no ejecuta SQL arbitrario, no siembra identidades y no requiere una
extensión PostgreSQL.

### `.github/scripts/ci_dbi_identity.py`

La barrera valida:

- metadatos y claves foráneas exclusivas de `DBIBase`;
- igualdad exacta de permisos persistibles y `DBIPermission`;
- índices únicos por nivel de ámbito;
- cabeza y linaje Alembic;
- SQL completo generado offline;
- compilación PostgreSQL de las seis consultas;
- contexto completo y membresía solo de tenant;
- denegaciones por referencias, ausencia, duplicidad, estados e inconsistencia;
- ausencia de FastAPI, seguridad heredada, motores, conexiones y efectos
  externos.

### `.github/scripts/ci_asset_persistence.py`

La barrera heredada de activos conservaba dos supuestos cerrados al corte de
`DBI-ASSET-001`: exactamente siete tablas y la revisión 0004 como cabeza. Se
ajusta sin reducir cobertura para exigir:

- que sus siete tablas sigan presentes como subconjunto;
- que exista una sola cabeza DBI;
- que `dbi_0004_assets_artifacts` permanezca en el linaje;
- que su predecesora continúe siendo `dbi_0003_analysis_jobs`.

No se modifica un modelo, restricción o migración de activos.

### `.github/workflows/ci.yml`

El backend ejecuta la nueva barrera después de autorización. El paso no recibe
credenciales y no necesita PostgreSQL.

## Riesgos y controles

| Riesgo | Control |
| --- | --- |
| Permiso de un ámbito combinado con otro | Permisos globales separados de ámbitos |
| Duplicados pese a restricciones únicas | Rechazo defensivo por cardinalidad |
| Principal o membresía inactivos | Solo `active` produce contexto |
| Membresía revocada reutilizada | `revoked` siempre denegado |
| Finca fuera de organización | Consulta de coincidencia exacta |
| Lote fuera de finca | Consulta acumulativa exacta |
| Referencia heredada expuesta | El contexto usa el UUID canónico |
| Enumeración de pertenencias | Tipo y mensaje de denegación únicos |
| Conexión accidental | Sesión y repositorio inyectados |
| Grafo DBI divergente | Una cabeza y predecesora exacta |

## Pruebas y criterios de aceptación

| Criterio | Evidencia |
| --- | --- |
| Autoridad solo en DBI | Cuatro tablas sobre `DBIBase` |
| Referencias opacas | Cero FKs hacia tablas heredadas |
| Solo estados activos | Casos válido, inactivo y revocado |
| Permisos exactos | Comparación con `DBIPermission` |
| Ámbitos exactos | Organización, finca y lote resueltos |
| Denegación cerrada | Ausencia, duplicidad e inconsistencia |
| Dependencias explícitas | Sesión en repositorio; repositorio en resolvedor |
| Una cabeza DBI | Grafo y SQL offline |
| Compatibilidad heredada | Tres cabezas heredadas y barreras previas |
| Sin integraciones | Barrera estática y cero servicios |

## Validación

### Local

| Verificación | Resultado |
| --- | --- |
| Compilación Python de cuatro módulos nuevos | Aprobado |
| Límite de 88 caracteres en cuatro módulos nuevos | Aprobado |
| Ejecución SQLAlchemy/Alembic local | No ejecutada: instalación bloqueada |

La imposibilidad local no se presenta como aprobación. La evidencia funcional
se obtiene en GitHub Actions con las versiones fijadas por el repositorio.

### Remota

GitHub Actions `30506792978` confirmó que la nueva barrera completa aprobaba,
pero detectó que la barrera heredada de activos asumía siete tablas y la revisión
0004 como cabeza. El ajuste fue limitado a hacer esas aserciones extensibles,
conservando todas sus comprobaciones propias.

GitHub Actions `30506879227` sobre
`fb8a8192f9364f13904aef7b0022699d9fbd1284` aprobó seis de seis
trabajos:

- backend con Python 3.11, compilación, ambos grafos Alembic, SQL offline,
  sesiones, repositorios, autorización, identidad, dominio, contratos,
  persistencia y healthcheck;
- frontend con instalación, lint y build de producción;
- bot con instalación, compilación y smoke test;
- densidad con dependencias, compilación, importaciones y CLI;
- higiene de artefactos y detección de secretos.

Esta es la evidencia inicial de implementación. La documentación deberá aprobar
otra ejecución completa sobre su propio SHA antes de considerar el ticket listo
para revisión final.

## Exclusiones confirmadas

- No se modifica `app/core/security.py`, `User` o `Company`.
- No se modifica `app/main.py`, `app/api/deps.py` o un router.
- No se decodifica JWT ni se interpreta el rol heredado `ADMIN`.
- No se cambia la fábrica o la sesión heredada.
- No se construye motor, fábrica de sesión o conexión DBI.
- No se ejecuta Alembic online ni se consulta PostgreSQL.
- No se siembran principales, membresías, permisos o ámbitos.
- No se conecta almacenamiento, cola, PostGIS o worker.
- No se procesa una ortofoto.
- No se cambia frontend, mapa, bot, Green API, Sheets o Render.
- No se descarga, actualiza o promueve un modelo de IA.
