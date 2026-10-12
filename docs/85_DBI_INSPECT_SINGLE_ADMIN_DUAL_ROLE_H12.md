# DBI-H12-AUTH-002 — Administrador único y técnicos múltiples en INSPECT

## Regla de negocio confirmada por DALGORO

- **Exactamente un administrador institucional DALGORO**, global para DBI;
  no un administrador por tenant, cliente, organización ni finca.
- **Uno o más técnicos**: no hay máximo técnico preestablecido.
- La **misma persona** puede ser a la vez administrador y técnico, con
  ambas acreditaciones activas vinculadas al mismo UUID canónico.
- Cuando el administrador también actuó como técnico, **una sola acción
  administrativa** es suficiente. No se exigen dos aprobaciones manuales
  ni se fabrican dos identidades. La acción genera en la misma transacción
  los eventos `technical_validated` y `administrative_authorized`,
  ambos con el mismo UUID; si ya existía su propia validación técnica,
  sólo se agrega la autorización.
- Cuando una **persona técnica diferente** valida la evidencia, se conserva
  el orden técnico→administrador, con dos principales distintos.

## Cambios acotados

1. `inspection/staff_workflow.py` pide al directorio institucional
   `list_active_administrators()` de **alcance global DALGORO** y niega
   cualquier operación si no devuelve exactamente un UUID. Permite una
   asignación activa por cada cargo al mismo principal (sin duplicados).
   Exige que una asignación `administrator` corresponda al único UUID
   institucional, además de principal y membresía DBI activos y scope.
2. `inspection/campaign_approval_service.py` conserva por defecto la
   denegación de autoaprobación del servicio legacy. Sólo el
   `DBIInspectionStaffWorkflow` tras verificar ambos cargos inyecta
   `_staff_dual_role_verified=True` al método interno. Este parámetro
   **jamás se recibe de HTTP, payload, cabecera ni frontend**. Aún no
   existen endpoints de firma.
3. `inspection/dual_approval.py` diferencia los estados
   `dual_approved` (dos actores) y `self_approved` (uno con dos cargos).
   En ambos exige autorización ADMIN + `APPROVE_AGRONOMIC`; el modo propio
   añade `WRITE`, validez de Campaign y versión actual.
4. `inspection/published_read_service.py` acepta las dos modalidades
   cuando el vínculo y la Campaign publicada siguen vigentes, el hash de
   INSPECT coincide y la cadena científica real MULTI está demostrada.

## Controles inalterados

- Finca/lote/tenant exactos, principal y membresía DBI activos.
- El cliente con sólo `READ` **no puede firmar ni consultar INSPECT
  no publicado**; no se abren rutas ni UI.
- La evidencia `observed` debe ser la última versión, con `sha256`
  coincidente y cadena auténtica
  ráster científico→artefacto→job→Campaign MULTI.
- Una corrección vuelve ineligibles eventos sobre la versión anterior;
  requiere nuevo vínculo y nueva aprobación.
- Ambos eventos siguen siendo append-only; no se modifican las tablas
  ni la migración 27. Se respetan locks `FOR UPDATE`.
- Las pruebas de la modalidad tradicional con técnicos distintos siguen
  vigentes. La ruta unipersonal se ensaya además en PostGIS efímero.

## Límites institucionales pendientes (no confundir con producción)

Todavía **NO hay directorio DALGORO real** ni base persistente de roles
laborales. Las pruebas incluyen un directorio sintético, pero no acreditan
a personas de producción. El método `list_active_administrators()`
es contrato para el próximo PR: debe usar consulta institucional global y
garantía de exclusión en PostgreSQL para no permitir dos administradores
en carreras de alta/revocación; su lectura debe quedar ligada a los locks
de acreditaciones durante la firma. Revocaciones y auditoría requieren
su propio PR. No se activa una opción de "autofirma" sin comprobar primero
el cargo doble desde esa autoridad.

No se realizan despliegues, migraciones, cambios de modelos de IA ni
publicación del cliente.
