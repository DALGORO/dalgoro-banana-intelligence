# 26 — Política de autorización DBI-AUTH-001

## Identificación

- Ticket: `DBI-AUTH-001`
- Issue: #26
- Fecha: 2026-07-29
- Rama: `feat/DBI-AUTH-001-autorizacion-dbi-offline`
- Base: `main` en `706537d900e66a0963f555541b9d883f167ce823`
- Pull request: pendiente
- Estado: en implementación

## Objetivo

Definir una política DBI pura, explícita y cerrada por defecto para validar
identidad, permiso y pertenencia antes de que futuros adaptadores FastAPI
invoquen repositorios. El cambio mantiene separadas tres responsabilidades:
autenticación heredada, resolución futura del contexto DBI y autorización de
recursos.

## Evidencia de partida

La revisión de `main` confirmó:

- siete repositorios DBI acotados por `organization_ref` o `tenant_ref`;
- una unidad de trabajo sobre la frontera transaccional autorizada;
- autenticación heredada con JWT, `User.role` y sesiones `DATABASE_URL`;
- empresas heredadas ligadas mediante `Company.owner_id`;
- ausencia de identidad, pertenencia o permisos DBI persistidos;
- ausencia de vínculo canónico entre `Company` y `organization_ref`;
- ausencia de ciclo de vida FastAPI, endpoints y base DBI real.

El rol heredado `ADMIN` no demuestra pertenencia DBI. La política nueva no lo
importa ni lo interpreta como acceso global.

## Decisión

La autorización DBI queda dividida en dos fronteras futuras y una frontera
implementada:

1. una futura capa confiable autenticará al usuario y resolverá sus ámbitos;
2. `DBIAccessContext` conservará una copia inmutable de identidad, tenant,
   organizaciones, fincas, lotes y permisos ya resueltos;
3. `DBIAuthorizationPolicy` validará coincidencia exacta antes del acceso;
4. un futuro adaptador FastAPI pasará únicamente ámbitos autorizados a los
   repositorios;
5. cualquier ausencia, diferencia o valor desconocido producirá denegación.

La política no consulta tablas y no determina pertenencia por sí misma. Esa
resolución requiere un ticket posterior con una fuente canónica explícita.

## Implementación por archivo

### `apps/platform-web/backend/app/dbi/authorization.py`

El módulo incorpora:

- `DBIPermission`, con cinco permisos explícitos;
- `DBIFarmScope`, pertenencia inmutable de finca y organización;
- `DBIPlotScope`, pertenencia inmutable de lote, finca y organización;
- `DBIAccessContext`, contexto defensivo y sin comodines;
- `DBIAccessDenied`, denegación externa uniforme;
- `DBIAuthorizationPolicy`, validación de tenant, organización, finca y lote.

Los permisos reconocidos son:

| Permiso | Uso futuro previsto |
| --- | --- |
| `read` | Lecturas autorizadas |
| `write` | Cambios de dominio autorizados |
| `submit_analysis` | Envío de trabajos geoespaciales |
| `approve_agronomic` | Aprobación profesional de hallazgos |
| `manage` | Administración DBI expresamente concedida |

Ningún permiso se deduce de otro. `manage` tampoco crea un comodín: todo acceso
continúa exigiendo tenant y cadena de pertenencia coincidentes.

La cadena aplicada por recurso es:

| Recurso | Coincidencias obligatorias |
| --- | --- |
| Tenant | permiso + tenant |
| Organización | permiso + tenant + organización |
| Finca | permiso + tenant + organización + finca |
| Lote | permiso + tenant + organización + finca + lote |

Todos los identificadores de texto se normalizan en los bordes, pero no cambian
mayúsculas ni minúsculas. Una pertenencia exige igualdad exacta después de
retirar espacios exteriores.

### `.github/scripts/ci_dbi_authorization.py`

La barrera comprueba:

- los cuatro niveles permitidos;
- permiso ausente;
- tenant, organización, finca y lote ajenos;
- valores vacíos, comodines y permiso desconocido;
- UUID inválido;
- finca sin organización;
- lote sin finca;
- copia defensiva de colecciones;
- inmutabilidad del contexto;
- denegación uniforme;
- ausencia de integraciones o efectos laterales.

La prueba usa únicamente la biblioteca estándar y no crea motor, sesión,
conexión, petición HTTP o consulta.

### `.github/workflows/ci.yml`

El trabajo backend ejecuta la nueva barrera después de validar repositorios y
unidad de trabajo DBI. El paso no recibe credenciales ni necesita PostgreSQL.

## Límites

Este ticket no implementa:

- autenticación o decodificación de JWT;
- conversión de `User`, roles o `Company` a un contexto DBI;
- persistencia de tenants, membresías o permisos;
- relación entre tablas heredadas y referencias DBI;
- integración con `app/main.py`, `app/api/deps.py` o routers;
- dependencia FastAPI o endpoints;
- cambios en repositorios o unidad de trabajo;
- tablas, migraciones, roles o una base DBI real;
- almacenamiento, cola, worker, PostGIS, mapa o bot.

## Riesgos y controles

| Riesgo | Control |
| --- | --- |
| Acceso transversal | Coincidencia exacta y denegación por defecto |
| Ámbito universal | Valores vacíos y comodines rechazados |
| Rol heredado tratado como pertenencia | Cero importaciones heredadas |
| Organización sin tenant | Tenant validado en todos los niveles |
| Finca sin organización | Invariante al construir el contexto |
| Lote sin finca | Invariante al construir el contexto |
| Enumeración de recursos | Un único tipo y mensaje de denegación |
| Colecciones modificadas después | Copia defensiva a `frozenset` |
| Acoplamiento prematuro | Biblioteca estándar sin FastAPI ni SQLAlchemy |

## Pruebas y criterios de aceptación

| Criterio | Evidencia prevista |
| --- | --- |
| Identidad y tenant explícitos | Entradas vacías rechazadas |
| Contexto inmutable | Mutación y alias de colecciones bloqueados |
| Denegación por defecto | Permiso ausente rechazado |
| Tenant exacto | Tenant ajeno rechazado |
| Organización completa | Organización ajena rechazada |
| Finca completa | Finca ajena o huérfana rechazada |
| Lote completo | Lote ajeno o huérfano rechazado |
| Error uniforme | Tipo y mensaje únicos |
| Sin servicios | Barrera estática y cero conexiones |
| Compatibilidad | CI completa de los cuatro módulos |

## Validaciones locales

| Verificación | Resultado |
| --- | --- |
| Compilación del módulo y barrera | Aprobado |
| Cadena permitida en cuatro niveles | Aprobado |
| Denegaciones por permiso y ámbito | Aprobado |
| Identificadores y permisos inválidos | Aprobado |
| Invariantes de finca y lote | Aprobado |
| Copia defensiva e inmutabilidad | Aprobado |
| Límites de código fuente | Aprobado |

La evidencia definitiva será la ejecución completa de GitHub Actions sobre el
SHA final. Las pruebas locales no sustituyen esa ejecución.

## Validación remota

Pendiente de publicación del Draft PR y de GitHub Actions.

## Exclusiones confirmadas

- No se modifica `app/core/security.py`.
- No se modifica `app/models/user.py`.
- No se modifica `app/models/company.py`.
- No se modifica `app/main.py` o `app/api/deps.py`.
- No se modifican repositorios, modelos o migraciones DBI.
- No se ejecuta Alembic online.
- No se consulta o modifica PostgreSQL.
- No se crea un endpoint o dependencia FastAPI.
- No se conecta almacenamiento, cola, PostGIS o worker.
- No se procesa una ortofoto.
- No se descarga o actualiza un modelo de IA.
- No se cambia el frontend, el mapa o el bot.
