# 35 — Implementación y auditoría administrativa DBI-ADMIN-001

## Identificación

- Ticket: `DBI-ADMIN-001`.
- Issue: #49.
- Pull request: #50.
- Rama: `feat/DBI-ADMIN-001-administracion-identidades-organizaciones-permisos`.
- Base inicial auditada: `main` en `8debfe41706360472f121b3f20b89f22b975bb75`.
- Código funcional auditado: `babd2b76ec48b8dc47ff4a245be5c3e0875490c8`.
- Estado: implementación funcional completa; documentación y revisión final del PR en curso.

## Objetivo cumplido

Se implementó una frontera administrativa DBI cerrada por defecto para:

- registrar y consultar principales DBI;
- crear y consultar membresías;
- sustituir permisos y ámbitos;
- desactivar, reactivar y revocar membresías;
- preservar el estado global de los principales;
- impedir autoelevación y acceso transversal;
- proteger al último administrador válido;
- mantener evidencia administrativa append-only;
- operar exclusivamente sobre sesión, modelos y autoridad DBI.

La implementación no convierte el rol heredado `ADMIN`, una cabecera ni la
ausencia de ámbitos en autoridad administrativa DBI.

## Límites arquitectónicos confirmados

### Autoridad

Toda operación administrativa exige simultáneamente:

- principal DBI activo;
- membresía DBI activa del actor;
- permiso explícito `manage`;
- cobertura organizacional explícita de todas las organizaciones afectadas;
- coincidencia exacta del tenant persistido.

El actor administrativo se reconstruye nuevamente desde la base DBI antes de
usar sus identificadores internos. Principal, membresía, permisos, ámbitos y
versiones no se aceptan desde payloads o cabeceras administrativas.

### Principal global

`DBIPrincipal` continúa siendo una identidad global por
`legacy_identity_ref`. La frontera organizacional puede:

- registrar un principal nuevo en estado `active`;
- consultar un principal activo o inactivo;
- aceptar un registro repetido exactamente igual como no-op idempotente.

No puede:

- activar o desactivar el principal;
- modificar `legacy_identity_ref`;
- alterar `principal.updated_at`;
- usar una mutación de membresía para cambiar `principal_active`.

Un principal existente e inactivo genera conflicto al intentar registrarlo y
no se reactiva por inferencia.

### Membresía

`DBIMembership` continúa siendo única por `principal_id + tenant_ref`.
Estados admitidos:

- `active`;
- `inactive`;
- `revoked`.

La revocación es irreversible desde esta frontera. No existe borrado físico de
principales, membresías o eventos de auditoría.

### Permisos y ámbitos

Los permisos pertenecen a toda la membresía. Por ello, modificar permisos o el
estado de una membresía multiorganización exige que el actor administre todas
las organizaciones cubiertas antes y después del cambio.

Los ámbitos admitidos son:

- organización;
- finca;
- lote.

Un ámbito de finca o lote no concede administración total de su organización.
La revisión `dbi_0008_scope_hierarchy` añade integridad referencial compuesta:

- finca + organización deben coincidir con `dbi_farms`;
- lote + finca deben coincidir con `dbi_plots`;
- las relaciones usan `ON DELETE RESTRICT`.

## Componentes implementados

### Política y estado

- `app/dbi/admin_policy.py`
- `app/dbi/admin_state.py`
- `app/dbi/admin_mutation_plan.py`
- `app/dbi/admin_creation_plan.py`

Responsabilidades:

- autoridad cerrada por defecto;
- anti-autoescalamiento;
- protección del último administrador;
- transiciones válidas de estado;
- planes puros e inmutables;
- control optimista por `membership.updated_at`;
- acciones de auditoría deterministas.

### Persistencia y servicio

- `app/dbi/admin_repository.py`
- `app/dbi/admin_persistence.py`
- `app/dbi/admin_creation_persistence.py`
- `app/dbi/admin_mutation.py`
- `app/dbi/admin_service.py`

Responsabilidades:

- advisory locks ordenados por tenant y organización;
- bloqueo de la membresía raíz con `FOR UPDATE`;
- lectura posterior de principal, permisos y ámbitos;
- sustitución transaccional de filas hijas autorizadas;
- altas idempotentes mediante restricciones canónicas;
- eventos append-only en la misma transacción;
- ausencia de `commit`, `rollback`, motores o sesiones internas.

### Resolución y lectura

- `app/dbi/admin_actor.py`
- `app/dbi/admin_dependencies.py`
- `app/dbi/admin_membership_reader.py`
- `app/dbi/admin_principal_reader.py`

Responsabilidades:

- reconstruir al actor autenticado desde DBI;
- verificar coincidencia exacta con `DBIAccessContext`;
- resolver membresías objetivo únicamente dentro del tenant del actor;
- ejecutar autorización antes de consultar un principal global;
- ocultar existencia fuera de cobertura mediante respuestas uniformes.

### Contratos HTTP

- `app/dbi/admin_schemas.py`
- `app/dbi/admin_membership_schemas.py`
- `app/dbi/admin_principal_schemas.py`

Controles:

- `extra="forbid"`;
- referencias vacías, comodines `*`, `all` y `any` rechazados;
- permisos y ámbitos duplicados rechazados;
- `expected_updated_at` exige zona horaria y se normaliza a UTC;
- el alta no permite controlar `principal_active`, estado global, actor, fechas
  persistidas ni resultado de auditoría;
- la creación de membresía produce siempre una membresía activa.

### API

- `app/api/v1/dbi_admin.py`
- `app/api/v1/dbi_admin_principals.py`

Rutas montadas bajo `/api/v1/dbi/admin`:

| Método | Ruta | Función |
|---|---|---|
| `POST` | `/principals` | Registro activo idempotente de principal |
| `GET` | `/principals/{legacy_identity_ref}` | Consulta autorizada de principal |
| `POST` | `/memberships` | Creación activa e idempotente de membresía |
| `GET` | `/memberships/{membership_id}` | Consulta protegida de membresía |
| `PATCH` | `/memberships/{membership_id}` | Sustitución completa de estado, permisos y ámbitos |
| `POST` | `/memberships/{membership_id}/deactivate` | Desactivación lógica |
| `POST` | `/memberships/{membership_id}/reactivate` | Reactivación de membresía inactiva |
| `POST` | `/memberships/{membership_id}/revoke` | Revocación irreversible |

La consulta de principal exige uno o más parámetros
`organization_ref`. La política se ejecuta antes del lector global para evitar
que el endpoint se use como mecanismo de enumeración.

## Semántica HTTP

- `200`: consulta, no-op idempotente o mutación aplicada;
- `201`: principal o membresía creados por primera vez;
- `403`: actor autenticado sin autoridad administrativa base;
- `404`: recurso ausente o fuera de cobertura, sin revelar cuál condición ocurrió;
- `409`: conflicto de unicidad, idempotencia, versión o estado;
- `422`: contrato o parámetros inválidos;
- `503`: runtime DBI no disponible mediante la dependencia existente.

No se exponen detalles SQL, URLs, credenciales, JWT, payloads completos ni
información de otro tenant.

## Concurrencia e idempotencia

### Concurrencia

Toda mutación recibe `expected_updated_at`. El servicio:

1. adquiere locks organizacionales estables;
2. bloquea la membresía raíz;
3. reconstruye el estado persistido;
4. compara la versión esperada;
5. vuelve a validar autoridad y último administrador;
6. persiste la mutación y auditoría en la misma transacción.

Una versión divergente devuelve conflicto y no sobrescribe cambios recientes.

### Principal

Un alta repetida es idempotente únicamente cuando coinciden exactamente:

- `principal_id`;
- `legacy_identity_ref`;
- estado activo persistido.

Cualquier divergencia produce conflicto.

### Membresía

Una creación repetida es idempotente únicamente cuando coinciden exactamente:

- `membership_id`;
- principal;
- tenant;
- estado activo;
- permisos;
- ámbitos.

No se fusionan autoridades ni se amplían permisos implícitamente.

## Protección del último administrador

Antes de degradar una membresía, la misma transacción verifica que cada
organización afectada conserve otra membresía distinta que cumpla:

- principal activo;
- membresía activa;
- permiso `manage`;
- ámbito explícito de organización.

La protección cubre:

- desactivación;
- revocación;
- retiro de `manage`;
- retiro de ámbito organizacional;
- cambios indirectos equivalentes.

## Auditoría administrativa

Modelo y tabla:

```text
app/dbi/models/admin_audit.py
dbi.dbi_admin_audit_events
```

La evidencia contiene únicamente:

- identificador;
- fecha UTC;
- actor principal y membresía;
- tenant;
- organización;
- acción;
- tipo y referencia opaca del recurso;
- resultado cerrado a `succeeded`;
- correlación no sensible.

No contiene JSON libre, descripción, JWT, contraseña, certificado, URL ni
payload completo. Principal, membresía y auditoría usan relaciones `RESTRICT`.
La unicidad por correlación, organización, acción y recurso evita duplicación de
evidencia en reintentos exactos.

## Migraciones

Historial lineal confirmado:

```text
dbi_0006_plot_boundaries
  -> dbi_0007_admin_audit
  -> dbi_0008_scope_hierarchy
```

La integración efímera valida:

- aplicación desde base vacía;
- única cabeza Alembic;
- metadata SQLAlchemy equivalente al esquema real;
- segunda ejecución idempotente;
- ausencia de tablas heredadas;
- restricciones compuestas de jerarquía;
- privilegios efectivos mínimos.

## ACL del rol API efímero

La integración real prueba `dbi_test_api` sin:

- `SUPERUSER`;
- `CREATEDB`;
- `CREATEROLE`;
- `REPLICATION`;
- `BYPASSRLS`;
- `CREATE` sobre el esquema;
- DDL funcional;
- borrado de principales, membresías o auditoría;
- actualización global de principales;
- actualización de `tenant_ref` de membresías.

Privilegios funcionales probados:

- principales: `SELECT`, y `INSERT` durante la prueba combinada de altas;
- membresías: `SELECT`, `INSERT`, `UPDATE(status, updated_at)`;
- permisos y ámbitos: `SELECT`, `INSERT`, `DELETE`;
- auditoría: `SELECT`, `INSERT`;
- fincas y lotes: `SELECT` para validar jerarquía.

Los privilegios combinados se aprovisionan únicamente dentro del fixture
efímero. Producción y staging permanecen fuera de alcance.

## Evidencia automatizada

Código funcional auditado:

```text
babd2b76ec48b8dc47ff4a245be5c3e0875490c8
```

Resultados:

- `CI modular #489`: 6/6 trabajos aprobados;
- `DBI migrations integration #174`: aprobada;
- backend completo hasta importación y healthcheck;
- frontend lint/build y auditoría de dependencias aprobados;
- WhatsApp smoke test aprobado;
- densidad geoespacial aprobada;
- higiene del repositorio aprobada;
- Gitleaks sobre historial completo aprobado;
- migraciones, ACL, mutación real y altas reales aprobadas.

La integración de altas verifica:

- principal nuevo;
- no-op exacto;
- colisión de ID o referencia;
- rechazo de principal inactivo;
- membresía nueva;
- no-op exacto;
- divergencia de permisos;
- principal inactivo;
- creación para el propio actor;
- autoridad y auditoría persistidas exactamente.

La integración de mutaciones verifica:

- sustitución real de permisos y ámbitos;
- seis eventos append-only en el escenario multiorganización;
- no-op sin nueva evidencia;
- conflicto de versión;
- protección del último administrador;
- rechazo real de SQL y privilegios prohibidos.

### Incidencia auditada durante la implementación

El SHA `75e30b9ef95400f32445052a9aed6846db65690f` produjo un fallo en la prueba
HTTP de reactivación de membresía revocada. La ruta productiva usaba el servicio
real, pero el doble de prueba omitía ejecutar la política. Se corrigió
únicamente el doble para llamar `DBIAdminPolicy.require_membership_change`.
El SHA posterior `f896967e37fd28493c3b6dea550f100725fcc9df`
terminó con `CI modular #482` e integración #167 en verde.

## Auditoría de fronteras

El diff completo fue revisado para confirmar:

- sin importación productiva de `User` o `Company`;
- sin `SessionLocal` o sesión heredada;
- sin uso productivo de `DATABASE_URL`;
- sin motores, fábricas o conexiones creados dentro de servicio/repositorios;
- sin secretos o URLs completas en auditoría;
- sin borrado físico de principales, membresías o auditoría;
- sin cambios en WhatsApp, Green API, Google Sheets, Render o modelos de IA;
- sin panel administrativo frontend;
- sin bootstrap automático;
- sin entidad canónica nueva de organización.

Las referencias a `DATABASE_URL`, sesión heredada y modelos heredados dentro de
scripts CI corresponden a aserciones de prohibición o configuración SQLite de
smoke tests, no a la frontera productiva DBI.

## Recuperación ante fallo

- La frontera HTTP confirma la transacción únicamente después del resultado del
  servicio.
- Denegaciones, conflictos e integridad fallida ejecutan rollback.
- Errores inesperados son revertidos por `get_dbi_session`.
- No existe reparación automática.
- No se reactiva principal o membresía por inferencia.
- Un conflicto de versión exige releer el estado.
- No se edita manualmente la tabla Alembic.
- Todo cambio futuro de esquema requiere una revisión nueva.

## Exclusiones confirmadas

- producción o staging remoto;
- bootstrap automático del primer administrador;
- autoridad transversal para mutar el principal global;
- entidad canónica de organización;
- panel frontend;
- cambios en JWT, middleware o autenticación heredada;
- migración masiva de usuarios heredados;
- borrado físico de recursos canónicos;
- rotación de credenciales;
- WhatsApp, Green API, Google Sheets, Render o modelos de IA.

## Condición de cierre

El PR solo puede marcarse listo cuando:

- la documentación final esté integrada;
- CI modular y PostgreSQL/PostGIS estén verdes sobre el SHA final;
- el diff completo no presente hallazgos críticos;
- no existan hilos o revisiones pendientes;
- Issue #49 y la descripción del PR reflejen evidencia actual.

La fusión y cierre requieren una comprobación posterior en `main` antes de
actualizar el Hito 9.
