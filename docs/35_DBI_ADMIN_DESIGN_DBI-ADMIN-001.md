# 35 — Diseño administrativo DBI-ADMIN-001

## Identificación

- Ticket: `DBI-ADMIN-001`.
- Issue: #49.
- Pull request: #50.
- Rama: `feat/DBI-ADMIN-001-administracion-identidades-organizaciones-permisos`.
- Base inicial auditada: `main` en `8debfe41706360472f121b3f20b89f22b975bb75`.
- Estado: política pura en implementación; persistencia y API pendientes.

## Objetivo

Definir una frontera administrativa DBI cerrada por defecto para registrar
principales y gestionar membresías, permisos y ámbitos organizacionales sin
convertir la autoridad heredada en acceso universal, sin borrar físicamente
recursos y sin permitir autoelevación o acceso entre organizaciones.

Ninguna ruta, modelo, migración o servicio se considera aprobado hasta que sus
pruebas y la CI completa terminen en verde sobre el SHA correspondiente.

## Componentes auditados

La revisión cubrió:

- `app/dbi/models/identity.py`;
- `app/dbi/identity.py`;
- `app/dbi/authorization.py`;
- `app/dbi/repositories.py`;
- `app/dbi/unit_of_work.py`;
- `app/dbi/dependencies.py`;
- `app/api/v1/dbi_writes.py`;
- `dbi_alembic/versions/20260729_05_identity_memberships.py`;
- contratos y barreras CI de identidad, autorización, repositorios y escritura.

## Estado actual confirmado

### Principales

`DBIPrincipal` representa una identidad DBI canónica y global vinculada mediante
`legacy_identity_ref`. La referencia es opaca, única, no admite comodines y no
tiene clave foránea hacia `User`.

Estados persistidos:

- `active`;
- `inactive`.

El estado pertenece al principal global, no a un tenant. Por esa razón, una
administración limitada a una organización no puede activar o desactivar el
principal sin afectar potencialmente otras membresías fuera de su cobertura.

### Membresías

`DBIMembership` es única por `principal_id + tenant_ref`.

Estados:

- `active`;
- `inactive`;
- `revoked`.

La membresía es la frontera correcta para conceder, suspender o revocar acceso
dentro de un tenant.

### Permisos

Los permisos pertenecen a toda la membresía:

- `read`;
- `write`;
- `submit_analysis`;
- `approve_agronomic`;
- `manage`.

No son permisos por organización. Cambiar uno puede afectar todos los ámbitos
de una membresía multiorganización.

### Ámbitos

`DBIMembershipScope` representa ámbitos acumulativos de:

- organización;
- finca;
- lote.

Toda finca exige organización y todo lote exige organización y finca.

### Organizaciones

No existe una tabla canónica `DBIOrganization`. `organization_ref` es una
referencia opaca usada por fincas, ámbitos y autorización.

Los repositorios agrícolas filtran por `organization_ref`, pero las tablas de
finca no contienen `tenant_ref`. Introducir una entidad canónica de organización
requeriría redefinir claves, migrar datos y revisar el aislamiento de fincas.
Ese cambio no se hará implícitamente dentro de este ticket.

### Resolución de acceso

`DBIAccessContextResolver` acepta únicamente principal y membresía activos,
permisos válidos y jerarquías consistentes. La resolución niega por defecto.

La dependencia FastAPI transforma el identificador heredado autenticado en una
referencia opaca y resuelve autoridad exclusivamente desde DBI.

### Frontera administrativa ausente al iniciar

No existían:

- política administrativa;
- repositorios administrativos de principal o membresía;
- servicio administrativo;
- contratos de comando administrativos;
- rutas `/dbi/admin/...`;
- auditoría persistente de operaciones;
- protección del último administrador;
- control optimista explícito para cambios de permisos y ámbitos.

## Decisiones de seguridad

### Sin autoridad global implícita

No otorgan administración DBI:

- el rol heredado `ADMIN`;
- la ausencia de ámbitos;
- una cabecera especial;
- un permiso inferido;
- una pertenencia a la base heredada.

Toda operación exige una identidad DBI activa, una membresía activa,
`DBIPermission.MANAGE` y cobertura explícita del ámbito afectado.

### Administración organizacional

En `DBI-ADMIN-001`, administrar una organización significa administrar la
autoridad asociada a un `organization_ref` ya reconocido por DBI.

Quedan fuera:

- crear una tabla canónica de organizaciones;
- renombrar organizaciones;
- mover fincas entre tenants;
- inferir tenant a partir de una finca;
- crear automáticamente la primera autoridad administrativa.

### Principal global

La API administrativa organizacional podrá:

- registrar un principal nuevo y activo;
- consultar un principal por referencia opaca;
- tratar un registro repetido idéntico como idempotente.

No podrá:

- activar un principal inactivo;
- desactivar un principal activo;
- cambiar su referencia global;
- usar una mutación de membresía para alterar `principal_active`.

Un principal existente e inactivo producirá conflicto. La gestión global de su
estado requiere una futura autoridad transversal explícita o un procedimiento
de seguridad separado, no inferido desde una organización.

### Membresías multiorganización

Una membresía puede contener ámbitos de varias organizaciones, pero sus
permisos son globales dentro del tenant.

Regla obligatoria:

> Para cambiar permisos o estado de una membresía, el actor debe administrar
> todas las organizaciones cubiertas antes y después del cambio.

Un administrador parcial no puede modificar una membresía multiorganización.

### Anti-autoescalamiento

El actor no puede:

- conceder un permiso que no posee;
- asignar una organización que no administra;
- usar un ámbito de finca o lote como administración total de la organización;
- registrar su propio principal mediante la operación administrativa;
- crear una membresía para sí mismo;
- ampliar su propia autoridad mediante una mutación;
- reactivar su propia membresía inactiva.

La autoridad solicitada debe ser subconjunto de la autoridad efectiva del actor
antes de iniciar la operación.

### Último administrador

Una organización debe conservar al menos otra membresía distinta, activa y
resoluble que cumpla simultáneamente:

- principal activo;
- membresía activa;
- permiso `manage`;
- ámbito explícito de organización.

Se bloquean:

- desactivación o revocación de membresía;
- retiro de `manage`;
- retiro del último ámbito organizacional administrativo;
- cambios indirectos que produzcan el mismo resultado.

La comprobación debe ejecutarse en la misma transacción que aplica el cambio y
excluir la membresía objetivo del conteo restante.

### Concurrencia optimista

Toda mutación de membresía recibirá `expected_updated_at` y lo comparará con
`membership.updated_at` bajo bloqueo de fila.

Cambiar permisos o ámbitos debe actualizar también `membership.updated_at`.
Una divergencia devuelve conflicto y no sobrescribe el estado actual.

El registro de principal se protege mediante su restricción única. No existe una
mutación organizacional de `principal.updated_at` o `principal.status`.

### Estados y revocación

No habrá borrado físico administrativo.

- la creación de membresía produce una membresía activa;
- una membresía activa puede pasar a inactiva o revocada;
- una membresía inactiva puede reactivarse con autoridad explícita;
- una membresía revocada no se reactiva automáticamente;
- el estado global del principal permanece inmutable desde esta frontera.

### Idempotencia

Registrar un principal ya existente es idempotente únicamente cuando permanece
activo y representa la misma referencia solicitada. Un principal existente e
inactivo genera conflicto; no se reactiva.

Crear una membresía existente solo es idempotente cuando coinciden:

- principal;
- tenant;
- estado activo;
- permisos;
- ámbitos solicitados.

Toda divergencia se traduce en conflicto; no se fusionan autoridades.

## Auditoría administrativa

Se añadirá un registro append-only separado de modelos heredados.

Evidencia mínima:

- identificador del evento;
- fecha UTC;
- actor DBI;
- tenant;
- organización afectada cuando corresponda;
- acción;
- tipo de recurso;
- referencia opaca del recurso;
- resultado controlado;
- referencia de correlación no sensible.

No se almacenarán JWT, contraseñas, URLs de base, certificados, payload completo
ni datos heredados innecesarios.

Los eventos exitosos deben persistirse en la misma transacción que la mutación.
Los rechazos previos se registrarán mediante una frontera no sensible sin
convertir la denegación en acceso a información.

## Contrato administrativo previsto

### Lecturas

- consultar principal por referencia opaca;
- consultar membresía por tenant y principal;
- listar permisos y ámbitos dentro de la cobertura del actor;
- consultar eventos acotados por tenant y organización.

### Escrituras

- registrar principal activo de forma idempotente;
- crear membresía activa;
- activar, desactivar o revocar membresía;
- reemplazar permisos;
- reemplazar ámbitos;
- reactivar una membresía inactiva con autoridad explícita.

No se implementará `DELETE` ni mutación del estado global del principal.

## Frontera API prevista

Prefijo reservado:

```text
/dbi/admin
```

Las rutas exactas se incorporarán después de aprobar política, repositorio y
servicio administrativos offline.

Reglas HTTP:

- denegación o recurso fuera de ámbito: respuesta uniforme no enumerable;
- conflicto de unicidad, versión o idempotencia: `409`;
- contrato inválido: `422`;
- DBI no disponible: `503`;
- nunca se exponen detalles de SQL, URL o credenciales.

## Capas

### Política pura

```text
app/dbi/admin_policy.py
```

Responsabilidades:

- cobertura completa de organizaciones;
- subconjunto de permisos y ámbitos;
- bloqueo de autoelevación;
- detección de pérdida de administración;
- rechazo de cambios globales del principal;
- sin FastAPI, SQLAlchemy ni modelos heredados.

### Repositorio administrativo

```text
app/dbi/admin_repository.py
```

Responsabilidades:

- consultas acotadas por tenant y organización;
- bloqueo de filas cuando corresponda;
- conteo del administrador restante;
- persistencia de permisos, ámbitos y auditoría;
- sin commit, rollback o cierre propios.

### Servicio administrativo

```text
app/dbi/admin_service.py
```

Responsabilidades:

- coordinar autorización, concurrencia e idempotencia;
- mantener una única transacción recibida;
- actualizar `membership.updated_at` al cambiar hijos;
- añadir eventos de auditoría;
- no crear motores ni sesiones.

### Contratos

```text
app/dbi/admin_schemas.py
```

Serán estrictos, sin campos adicionales y sin valores vacíos o comodines.

### API

```text
app/api/v1/dbi_admin.py
```

Usará la sesión y el contexto DBI existentes. No importará `User`, `Company`,
`SessionLocal` ni configuración heredada.

## Secuencia de implementación

1. Política administrativa pura y pruebas offline.
2. Repositorio y servicio con dobles de sesión.
3. Modelo de auditoría y revisión Alembic lineal.
4. Contratos y rutas administrativas.
5. Integración PostgreSQL/PostGIS efímera desde base vacía.
6. Documentación, auditoría de diff y cierre.

Cada fase debe mantener la CI completa en verde antes de iniciar la siguiente.

## Pruebas obligatorias

### Política

- actor sin `manage` rechazado;
- tenant u organización ajenos rechazados;
- ámbito de finca sin ámbito organizacional no administra;
- permisos fuera del subconjunto rechazados;
- administrador parcial frente a membresía multiorganización rechazado;
- registro del propio principal rechazado;
- creación de membresía propia rechazada;
- membresía nueva inactiva o con principal inactivo rechazada;
- cambio indirecto de `principal_active` produce conflicto;
- reducción propia permitida sin ampliación.

### Último administrador

- dos administradores: degradación de uno permitida;
- un administrador: degradación rechazada;
- principal inactivo no cuenta;
- membresía inactiva o revocada no cuenta;
- `manage` sin ámbito de organización no cuenta;
- ámbito sin `manage` no cuenta.

### Concurrencia e idempotencia

- versión coincidente permite mutación;
- versión divergente devuelve conflicto;
- registro repetido idéntico es idempotente;
- principal inactivo no se reactiva;
- membresía repetida divergente devuelve conflicto;
- permisos o ámbitos actualizan `membership.updated_at`.

### Fronteras

- no se importa sesión heredada;
- no se usa `DATABASE_URL`;
- no existen motores o conexiones internas;
- no existe borrado físico;
- no se registran secretos;
- todas las consultas conservan tenant y organización;
- toda la CI modular termina sin pasos omitidos.

## Recuperación ante fallo

- la transacción se revierte completa;
- no se intenta reparación automática;
- no se reactiva principal o membresía por inferencia;
- no se reduce la protección del último administrador;
- un conflicto de versión exige releer el estado;
- todo cambio de esquema requiere una revisión Alembic nueva;
- no se edita manualmente la tabla de versión.

## Exclusiones

- producción o staging remoto;
- bootstrap automático del primer administrador;
- autoridad transversal para mutar el principal global;
- entidad canónica nueva de organización;
- panel frontend;
- cambios en JWT, middleware o autenticación heredada;
- migración masiva de usuarios heredados;
- borrado físico;
- administración de infraestructura o credenciales;
- WhatsApp, Green API, Google Sheets, Render o modelos de IA.
