# DBI-H12-SVC-001 · Servicio interno de vínculo Campaign–INSPECT y doble firma

## Cambio
Añade `DBIInspectionCampaignApprovalService` como API Python interna, **sin rutas
HTTP**, sin publicación al productor y sin despliegues ni migraciones nuevas.

La migración 27 (#217) ya aporta las tablas necesarias, pero **todavía no está
aplicada a producción**. La introducción del servicio al código no cambia
automáticamente la disponibilidad del esquema en servidores.

### Métodos
- `register_link`: requiere `WRITE` scoped, bloquea la identidad estable
  INSPECT en PostgreSQL, exige la **versión vigente observada** y Campaign
  `multispectral` del mismo tenant/organización/finca/lote. Una versión se
  vincula expresamente a una Campaign; repetición idéntica es inmutable.
  Si otra versión de la misma observación intenta cambiar de Campaign sin
  procedimiento de auditoría separado, se rechaza.
- `validate_technical`: requiere `WRITE` scoped, serializa contra las
  correcciones INSPECT mediante `SELECT ... FOR UPDATE` de su identidad
  estable, bloquea el vínculo y añade un evento
  `technical_validated`. No edita ni reescribe versiones.
- `authorize_administrative`: requiere `APPROVE_AGRONOMIC` **Y** `MANAGE`
  scoped, obligatoriamente otro principal. Exige primero validación técnica,
  misma versión vigente y **al menos una extracción MULTI** para esa versión
  cuya procedencia Campaign se resuelva por la cadena verificada
  `raster → artifact → job → Campaign` desde la base de datos.
  La fecha del vuelo o cercanía GPS no sustituyen la cadena. Solo entonces
  registra el evento `administrative_authorized`.
- `_state`: reconstruye el estado desde eventos inmutables; el contrato puro
  rechaza firmas inconsistentes o cruzadas. Una corrección posterior hace
  que el vínculo de versión anterior no sea vigente: nuevas firmas son
  necesarias para la versión sucesora.

### Garantías y límites
- `Session` compartida; **sin commit/rollback propios**. Los endpoints futuros
  deben proporcionar una transacción real, rollback en conflicto, membership
  DALGORO confiable, permisos DB limitados y auditoría de concurrencia.
- Regla **fail-closed**: cuando falta extracción científica verificada,
  no se permite la segunda firma. Un catálogo de campo puede estar
  técnicamente validado aunque la extracción MULTI todavía no exista.
- Las restricciones relacionales y UNIQUE/FOREIGN KEY son responsabilidad de
  la migración 27. No se debe confiar solo en validación Python.
- Las pruebas `ci_dbi_inspection_approval_service.py` usan **sesión simulada**
  para controlar orden de consultas, locks, permisos, idempotencia, firmas y
  procedencia. **No son pruebas transaccionales sobre PostGIS real.**
- Todavía NO se verifica identidad laboral DALGORO en estas operaciones:
  `WRITE` y `MANAGE` scoped son capacidades, no prueba de rol. **Antes
  de crear endpoints se deben consultar memberships autoritativas del backend**,
  y garantizar que cuentas cliente nunca puedan adoptar esos permisos.
- Faltan protección DB append-only frente a UPDATE/DELETE arbitrarios de
  roles privilegiados, revocación, registro de procedencia/auditoría completa,
  QA de UP y COPA_UP y prueba de concurrencia real en PostgreSQL.
- **No hay publicación cliente, GET paginado por Campaign, clasificación
  Sigatoka ni inferencia ML.** Los GET INSPECT READ-only permanecen
  bloqueados por #216. La existencia de eventos duales **no activa** salida
  de campo a usuarios externos.
- `_verified_scientific_chain` evalúa a lo sumo 20 extracciones por versión:
  en conjuntos mayores debe implementarse un verificador EXISTS scoped y
  paginado; la condición falla cerrada si no encuentra cadena verificable
  entre las muestras inspeccionadas.

### Condiciones para el siguiente microhito

1. Prueba real PostgreSQL/PostGIS en rol DBI con permisos mínimos,
   `SELECT ... FOR UPDATE` y dos transacciones concurrentes.
2. Endpoints **internos** con autenticación de técnico/admin y pertenencia
   institucional verificada; request nunca puede elegir `actor_ref` ni
   `campaign_link_verified`.
3. Tests HTTP con técnicos, administradores y clientes y corrección tardía;
   no exponer consultas de borradores al cliente ni por UUID.
4. Diseño de revocación/publicación separado y listado cliente **solo** de
   versiones vigentes con firmas válidas y proveniencia GIS/MULTI acreditada.
5. UAT móvil/escritorio y decisión de despliegue consciente. No ejecutar
   migraciones en producción como efecto del merge.

**Microhito deliberadamente interno:** prepara el motor de firma de evidencias
y conserva intactos los contratos de lectura y algoritmos actuales.
