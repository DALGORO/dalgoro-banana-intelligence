# 35 — Diseño administrativo DBI-ADMIN-001

## Identificación

- Ticket: `DBI-ADMIN-001`.
- Issue: #49.
- Rama: `feat/DBI-ADMIN-001-administracion-identidades-organizaciones-permisos`.
- Base auditada: `main` en `8debfe41706360472f121b3f20b89f22b975bb75`.
- Estado: diseño previo a implementación.

## Objetivo

Definir una frontera administrativa DBI cerrada por defecto para gestionar
principales, membresías, permisos y ámbitos organizacionales sin convertir la
autoridad heredada en acceso universal, sin borrar físicamente recursos y sin
permitir autoelevación o acceso entre organizaciones.

Este documento precede cualquier cambio funcional. Ninguna ruta, modelo,
migración o servicio se considera aprobado hasta que sus pruebas y la CI
completa terminen en verde sobre el SHA correspondiente.

## Componentes auditados

La revisión inicial cubrió:

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

`DBIPrincipal` representa una identidad DBI canónica vinculada mediante
`legacy_identity_ref`. La referencia es opaca, única, no admite comodines y no
tiene clave foránea hacia `User`.

Estados actuales:

- `active`;
- `inactive`.

### Membresías

`DBIMembership` es única por `principal_id + tenant_ref`.

Estados actuales:

- `active`;
- `inactive`;
- `revoked`.

### Permisos

Los permisos pertenecen a toda la membresía:

- `read`;
- `write`;
- `submit_analysis`;
- `approve_agronomic`;
- `manage`.

No son permisos por organización. Por ello, cambiar un permiso puede afectar
todos los ámbitos de una membresía multiorganización.

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
finca no contienen `tenant_ref`. Introducir ahora una entidad canónica de
organización requeriría redefinir claves, migración de datos y aislamiento de
fincas. Ese cambio no se hará de forma implícita dentro de este ticket.

### Resolución de acceso

`DBIAccessContextResolver` acepta únicamente principal y membresía activos,
permisos válidos y jerarquías consistentes. La resolución niega por defecto.

La dependencia FastAPI convierte el identificador heredado autenticado en una
referencia opaca y resuelve la autoridad exclusivamente desde DBI.

### Frontera administrativa ausente

Actualmente no existen:

- repositorios administrativos de principal o membresía;
- servicio administrativo;
- contratos de comando administrativos;
- rutas `/dbi/admin/...`;
- auditoría persistente de operaciones administrativas;
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

Toda operación requiere una identidad DBI activa, una membresía activa,
`DBIPermission.MANAGE` y cobertura explícita del ámbito afectado.

### Administración de organizaciones

En `DBI-ADMIN-001`, administrar una organización significa administrar la
autoridad asociada a un `organization_ref` ya reconocido por DBI.

Quedan fuera de este ticket:

- crear una tabla canónica de organizaciones;
- renombrar organizaciones;
- mover fincas entre tenants;
- inferir tenant a partir de una finca;
- crear la primera autoridad administrativa.

### Membresías multiorganización

Una membresía puede contener ámbitos de varias organizaciones, pero sus
permisos son globales dentro del tenant.

Regla obligatoria:

> Para cambiar permisos o estado de una membresía, el actor debe administrar
> todas las organizaciones cubiertas por esa membresía.

Un administrador parcial puede administrar únicamente asignaciones que no
alteren autoridad fuera de su cobertura.

### Anti-autoescalamiento

El actor no puede:

- conceder un permiso que no posee;
- asignar una organización que no administra;
- añadir una finca o lote fuera de sus ámbitos;
- usar una operación sobre sí mismo para ampliar su autoridad;
- transformar una membresía inactiva en una autoridad mayor que la propia.

La autoridad solicitada debe ser subconjunto de la autoridad efectiva del
actor antes de iniciar la operación.

### Último administrador

Una organización debe conservar al menos una membresía distinta, activa y
resoluble que cumpla simultáneamente:

- principal activo;
- membresía activa;
- permiso `manage`;
- ámbito de organización correspondiente.

Se bloquean:

- desactivación del principal;
- desactivación o revocación de membresía;
- retiro de `manage`;
- retiro del último ámbito organizacional administrativo;
- cambios indirectos que produzcan el mismo resultado.

La comprobación debe ejecutarse dentro de la misma transacción que aplica el
cambio.

### Concurrencia optimista

Toda mutación de principal o membresía recibirá una marca temporal esperada.

- principal: `expected_updated_at` contra `principal.updated_at`;
- membresía: `expected_updated_at` contra `membership.updated_at`.

Cambiar permisos o ámbitos debe actualizar también `membership.updated_at`.
Una divergencia devuelve conflicto y no sobrescribe el estado actual.

### Estados y revocación

No habrá borrado físico administrativo.

- principal activo puede pasar a inactivo;
- principal inactivo puede reactivarse si la operación es autorizada;
- membresía activa puede pasar a inactiva o revocada;
- membresía inactiva puede reactivarse;
- membresía revocada no se reactiva automáticamente.

Una revocación exige una operación explícita y auditada.

### Idempotencia

Crear un principal con una referencia ya existente solo es idempotente cuando
la entidad existente representa exactamente la misma identidad solicitada.

Crear una membresía existente solo es idempotente cuando coinciden:

- principal;
- tenant;
- estado;
- permisos;
- ámbitos solicitados.

Toda divergencia se traduce en conflicto; no se fusionan autoridades por
conveniencia.

## Auditoría administrativa

Se añadirá un registro append-only separado de los modelos heredados.

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

No se almacenarán:

- JWT;
- contraseñas;
- URLs de base;
- certificados;
- payload completo;
- nombres o datos heredados innecesarios.

Los eventos exitosos deben persistirse en la misma transacción que la mutación.
Los rechazos previos a una mutación se registrarán mediante una frontera de
auditoría no sensible, sin convertir una denegación en acceso a información.

## Contrato administrativo previsto

### Operaciones de lectura

- consultar principal por referencia opaca;
- consultar membresía por tenant y principal;
- listar permisos y ámbitos de una membresía dentro de la cobertura del actor;
- consultar eventos administrativos acotados por tenant y organización.

### Operaciones de escritura

- crear principal;
- activar o desactivar principal;
- crear membresía;
- activar, desactivar o revocar membresía;
- reemplazar permisos de membresía;
- reemplazar ámbitos de membresía;
- reactivar una membresía inactiva con autoridad explícita.

No se implementará `DELETE`.

## Frontera API prevista

Prefijo reservado:

```text
/dbi/admin
```

Las rutas exactas se incorporarán únicamente después de aprobar la política y
el servicio administrativo offline.

Reglas HTTP:

- denegación o recurso fuera de ámbito: respuesta uniforme no enumerable;
- conflicto de unicidad, versión o idempotencia: `409`;
- contrato inválido: `422`;
- DBI no disponible: `503`;
- nunca se exponen detalles de SQL, URL o credenciales.

## Capas previstas

### Política pura

Archivo previsto:

```text
app/dbi/admin_policy.py
```

Responsabilidades:

- validar cobertura completa de organizaciones;
- validar subconjunto de permisos y ámbitos;
- bloquear autoelevación;
- decidir cuándo se requiere protección del último administrador;
- no importar FastAPI, SQLAlchemy ni modelos heredados.

### Repositorio administrativo

Archivo previsto:

```text
app/dbi/admin_repository.py
```

Responsabilidades:

- consultas acotadas por tenant y organización;
- bloqueo de filas cuando la operación lo requiera;
- conteo del administrador restante;
- persistencia de permisos, ámbitos y auditoría;
- ninguna confirmación, rollback o cierre de sesión propios.

### Servicio administrativo

Archivo previsto:

```text
app/dbi/admin_service.py
```

Responsabilidades:

- coordinar autorización, concurrencia e idempotencia;
- mantener una única transacción;
- actualizar `membership.updated_at` al cambiar hijos;
- añadir eventos de auditoría;
- no crear motores ni sesiones.

### Contratos

Archivo previsto:

```text
app/dbi/admin_schemas.py
```

Los contratos serán estrictos, sin campos adicionales y sin valores vacíos o
comodines.

### API

Archivo previsto:

```text
app/api/v1/dbi_admin.py
```

La API dependerá de la sesión y del contexto DBI ya existentes. No importará
`User`, `Company`, `SessionLocal` ni configuración heredada.

## Secuencia de implementación

1. Política administrativa pura y pruebas offline.
2. Repositorio y servicio con dobles de sesión.
3. Modelo de auditoría y revisión Alembic lineal.
4. Contratos y rutas administrativas.
5. Integración PostGIS efímera desde base vacía hasta la nueva cabeza.
6. Documentación, auditoría de diff y cierre.

Cada fase debe mantener la CI completa en verde antes de iniciar la siguiente.

## Pruebas obligatorias

### Política

- actor sin `manage` rechazado;
- tenant ajeno rechazado;
- organización ajena rechazada;
- permisos solicitados fuera del subconjunto rechazados;
- ámbitos solicitados fuera del subconjunto rechazados;
- actor parcial frente a membresía multiorganización rechazado;
- operación sobre sí mismo sin elevación permitida;
- autoelevación directa o indirecta rechazada.

### Último administrador

- dos administradores: degradación de uno permitida;
- un administrador: degradación rechazada;
- principal inactivo no cuenta;
- membresía inactiva o revocada no cuenta;
- `manage` sin ámbito de organización no cuenta;
- ámbito sin `manage` no cuenta.

### Concurrencia e idempotencia

- versión temporal coincidente permite mutación;
- versión divergente devuelve conflicto;
- creación repetida idéntica es idempotente;
- creación repetida divergente devuelve conflicto;
- cambio de permisos actualiza `membership.updated_at`;
- cambio de ámbitos actualiza `membership.updated_at`.

### Fronteras

- no se importa sesión heredada;
- no se usa `DATABASE_URL`;
- no existen motores o conexiones internas;
- no existe borrado físico;
- no se registran secretos;
- todas las consultas administrativas conservan tenant y organización;
- toda la CI modular termina sin pasos omitidos.

## Recuperación ante fallo

- la transacción se revierte completa;
- no se intenta reparación automática;
- no se reactiva una membresía revocada por inferencia;
- no se reduce la protección del último administrador;
- un conflicto de versión exige releer el estado;
- cualquier cambio de esquema requiere una nueva revisión Alembic revisada;
- no se edita manualmente la tabla de versión.

## Exclusiones

- producción o staging remoto;
- bootstrap automático del primer administrador;
- entidad canónica nueva de organización;
- panel frontend;
- cambios en JWT, middleware o autenticación heredada;
- migración masiva de usuarios heredados;
- borrado físico;
- administración de infraestructura o credenciales;
- WhatsApp, Green API, Google Sheets, Render o modelos de IA.

## Puerta para comenzar código

La implementación funcional puede comenzar únicamente cuando:

- el Issue #49 contenga estas decisiones;
- este documento exista en la rama;
- la rama parta de `main` sin diferencias no relacionadas;
- el Draft PR esté abierto;
- la CI documental inicial termine completamente en verde.
