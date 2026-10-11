# DBI-H12-DB-001 · Persistencia aditiva Campaign MULTI–INSPECT y doble firma

**Alcance:** revisión Alembic 27 y modelos de SQLAlchemy **solamente**.
Este hito crea soporte para la asociación explícita Campaign–INSPECT
y un registro de eventos por aprobación, pero **no crea endpoints para firmar,
no concede permisos, no expone observaciones a clientes y NO se despliega a
producción**.

## Motivación y decisión confirmada

- Cada nueva visita/INSPECT utilizada como verdad-terreno debe pertenecer
  inequívocamente a la **Campaign multiespectral que pretende explicar**.
- Una Campaign permite N observaciones de campo; cada **versión** de INSPECT
  puede tener a lo sumo un levantamiento asociado. Las versiones anteriores
  permanecen accesibles al personal autorizado para auditoría, sin sobrescribir.
- Dos principales diferentes deben firmar: primero validación técnica,
  después autorización administrativa. Solo entonces una versión VIGENTE
  podrá ser candidata a consulta de cliente, **previa comprobación de publicación
  efectiva del servidor**.
- Correcciones crean versión nueva y fuerzan un ciclo nuevo de aprobación.
- INSPECT observado y características MULTI derivadas forman pares solo cuando
  la correspondencia UP/soporte/timing y procedencia se hayan validado.

## Diseño de la revisión 27

### Tabla `dbi_inspect_campaign_links`

Incluye `tenant_ref`, `organization_ref`, `farm_id`, `plot_id`,
`campaign_id`, `campaign_analysis_type`, `observation_id`,
`observation_version_id`, `linked_by_ref` y `linked_at`.

**Garantías directas de PostgreSQL**:
- FK compuesta a Campaign incluye scope completo y `analysis_type`.
  CHECK `campaign_analysis_type = 'multispectral'` prohíbe campañas
  density o legacy sin alcance. Añade clave candidata compuesta a Campaign.
- FK compuesta a INSPECT incluye exactamente el mismo tenant, organización,
  finca y lote. Añade clave candidata compuesta a la identidad INSPECT.
- FK `(observation_id, observation_version_id)` obliga a que la versión
  pertenezca a la observación precisa.
- UNIQUE `observation_version_id` impide asociar una versión a más de una
  Campaign y evita concurrencia duplicada.
- FKs RESTRICT protegen contra eliminación de evidencia vinculada. Los
  registros históricos no reciben asignaciones automáticas ni se modifican.

**Límite:** esta tabla solo registra una asociación propuesta, **NO certifica**
que la fecha del vuelo, lugar/copa, identidad UP o cadena científica sean
aptos para aprendizaje. Esas verificaciones pertenecen al servicio futuro.

### Tabla `dbi_inspect_approval_events`

Con `link_id`, `event_kind` (`technical_validated` o
`administrative_authorized`), `actor_ref`, `decided_at` y
`recorded_at`, UUID de evento, FK RESTRICT al vínculo, CHECK de tipo,
y UNIQUE `(link_id, event_kind)` para evitar repetir la misma etapa.
Cada fila representa una firma auditable separada de la otra y
la versión queda fijada por el vínculo.

**Limitaciones intencionales:** la base todavía NO garantiza por sí sola el
orden de inserción, que las firmas sean de dos personas distintas,
la identidad de personal DALGORO, la integridad de la cadena científica,
la inmutabilidad frente a UPDATE/DELETE hechos por roles DB privilegiados
ni una revocación. Tampoco se publica por la mera existencia de 2 eventos.
Se debe implementar una API transaccional con control de concurrencia
(`SELECT ... FOR UPDATE`), permisos de servidor, versionado,
auditoría append-only e invalidación/revocación explícita. Si se requieren
protecciones contra UPDATE/DELETE por roles DB, añadir grants/trigger en
una fase independiente con pruebas e inspección de privilegios.

## Gate para implementar después de aprobar este PR

1. Servicio de creación de vínculo técnico: autoridad WRITE scoped y
   comprobación efectiva de Campaign `multispectral`, INSPECT observado,
   versión vigente, tiempo del vuelo, GPS, soporte COPA_UP y UP.
   Una nueva versión NO hereda firmas; si cambia la Campaign se requiere
   una reasociación controlada, no un UPDATE silencioso.
2. Endpoints de firmas distintas: técnico autorizado firma `technical_validated`
   con rol profesional DALGORO verificable; administrador distinto, con
   `APPROVE_AGRONOMIC+MANAGE` scoped, firma `administrative_authorized`.
   Validar order, version y idempotencia/transacción. Un solo principal,
   aunque tenga todos los permisos, no puede completar ambas firmas.
3. API externa publicada: **solo** versión vigente, dos firmas verificadas,
   vínculo con Campaign científicamente acreditado, estado publicado,
   acceso scoped READ y campos permitidos. No reabrir GET directo legacy
   a clientes. Técnico y administrador conservan lectura/correcciones
   en endpoints internos con membresía real auditada.
4. Pruebas de integración de seguridad: dos Campaign misma fecha,
   cross-tenant/plot/org, campaña density/legacy, versión ajena,
   acceso cliente sin firmas, misma persona con doble rol, corrección
   posterior, revocación, concurrencia de firmas, GET por UUID/historial,
   aislamiento del listado paginado y rastreo de versiones.
5. UAT móvil/escritorio con datos de campo autorizados; revisión
   agronómica y aprobación específica de despliegue tras migración
   staging controlada.

## Validación de este PR

- Alembic `dbi_0027_inspect_campaign_signatures` sigue a `dbi_0026`.
  Cambios exclusivamente aditivos en DBI.
- CI de migraciones crea el esquema en PostGIS **efímero de pruebas**.
- `ci_dbi_inspect_campaign_schema.py` verifica FKs scoped,
  UNIQUE, CHECK, código SQL PostgreSQL y ausencia de publicación.
- Sin modificaciones de tablas existentes salvo dos únicas nuevas
  claves candidatas compuestas; sin cambios API, React, modelos de
  Sigatoka ni servidores de producción.

**Advertencia principal:** pasar CI de esquema NO significa que ya funcione
el flujo de doble aprobación ni que INSPECT pueda mostrarse a clientes.
El bloqueo READ-only de #216 permanece vigente hasta la API publicable
con dos firmas reales.
