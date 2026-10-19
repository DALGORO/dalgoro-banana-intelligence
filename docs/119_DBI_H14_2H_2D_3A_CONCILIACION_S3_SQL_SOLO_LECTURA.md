# H14 / 2H-2D/3A — Conciliación S3 ↔ SQL de solo lectura (sin limpieza automática)

## Objetivo y dependencias
Este PR se apila sobre **#267**, precedido por **#259 → #262 → #263 → #264 → #265 → #266**. Su objetivo es detectar **cargas multipart incompletas** en S3 local que no coinciden con los registros SQL, antes de conceder permisos de subida. Es un incremento **deliberadamente de solo lectura**: NO inicia, aborta, completa, borra ni recibe partes, y NO emite grants o presigned URLs. No contiene migraciones SQL.

## Proveedor seguro
Se añade a `DBIS3MultipartAdapter` (cuyo constructor solo admite endpoints **loopback**) un método `inspect_incomplete_uploads`. Valida el contrato del objeto y devuelve únicamente `incomplete_count`, `expected_present` y `unexpected_count`.

La enumeración emplea el listado S3 de cargas multipart por **clave exacta** derivada del objeto DBI; el adaptador ya filtra claves distintas aunque el proveedor devuelva prefijos vecinos. Sigue su límite de 10 páginas de 100, rechaza referencias duplicadas y ante paginación inconclusa devuelve error, **nunca un informe incompleto declarado consistente**. La referencia S3 SQL se emplea solo para comparación privada en servidor: la respuesta no incluye UploadId, clave S3, bucket ni credenciales.

## Ruta experimental
`POST /api/v1/dbi/organizations/{org}/farms/{farm}/plots/{plot}/campaigns/{campaign}/scientific-intake/private-raster-local-reconciliation/{role}/{index}`

Payload estricto heredado de preparación H14/2H-2D/1: `schema_version`, huellas exactas de manifiesto/reserva JSON y `idempotency_key`.

Solo accesible al definir **`DBI_SCIENTIFIC_RASTER_RECONCILIATION_ENABLED=1` y `DBI_ENVIRONMENT=test|development|local`**. `production`, `staging` y entornos vacíos permanecen bloqueados, incluso con flag. **No activar en Render.**

El endpoint ejecuta, en este orden:

1. Comprobación **MANAGE** y bloqueo `SELECT FOR UPDATE` de Campaign MULTISPECTRAL **no aprobada/no publicada**. Esto asegura una evaluación coherente con otros escritores que utilicen el mismo bloqueo.
2. Verificación de integridad de manifiesto y reserva S3 privados, rol/índice, actor, SHA-256 de JSON e identidad del TIFF todavía no ocupado.
3. Relectura y bloqueo de Binding + Asset + ticket SQL bajo scope completo, seguida del registro de inicio S3 SQL si existe.
4. `inspect_incomplete_uploads` sobre el **único destino futuro** y clasificación de discrepancias. Desbloquea con `session.rollback()` sin escribir filas.

## Estados de conciliación

| Estado | Interpretación |
| --- | --- |
| `no_remote_no_sql` | Ticket existente sin inicio SQL ni remoto |
| `remote_orphan_without_sql` | S3 registra al menos una carga incompleta, pero SQL no conserva una referencia |
| `active_exact_single_upload` | Único UploadId incompleto que coincide exactamente con SQL |
| `sql_active_remote_missing` | SQL dice iniciado, pero S3 no registra la carga |
| `sql_active_remote_replaced` | SQL dice iniciado; S3 tiene otras referencias, ninguna igual |
| `sql_active_remote_extra` | UploadId esperado presente y además cargas adicionales |
| `sql_aborted_no_remote` | SQL abortado y no quedan cargas incompletas |
| `sql_aborted_remote_remains` | SQL abortado, pero S3 todavía conserva cargas incompletas |

Toda discrepancia marca `manual_review_required=true`. Incluso el estado aparentemente consistente mantiene **`ready_for_upload=false`**, `grants_issued=false`, `file_received=false`, `content_verified=false`, `institutional_approved=false` y `published=false`. Una lista S3 de cargas incompletas **no demuestra** que las partes se hayan subido, que el objeto exista o que su contenido haya sido verificado.

## Límites deliberados
- **NO hay aborto automático ni limpieza administrativa postaprobación** en esta entrega. La ruta exige estado preaprobación; si la Campaign está aprobada/publicada, devuelve 404 sin inspeccionar S3. La gestión institucional postaprobación exige otro contrato de autorización, auditoría y retención.
- Un proveedor que devuelve un error, referencias duplicadas o listado truncado por encima del límite provoca fallo **503**, no conciliación positiva.
- La lista y SQL son una **instantánea transaccional parcialmente distribuida**, no una garantía de atomicidad S3↔SQL. Las partes o cargas remotas podrían cambiar entre lectura y respuesta. No habilitar grants hasta resolver el caso de commit incierto, hacer tests de carreras S3/SQL y comprobar revocación al aprobar.
- Aún no hay una **prueba de integración real con MinIO** para esta ruta: las pruebas de CI ejercitan el algoritmo real de listado exacto con proveedor simulado y escenarios sintéticos. El futuro test end-to-end debe levantar MinIO local y ensayar red cortada, duplicados, expiración y cleanup idempotente.

## Pruebas
`.github/scripts/ci_dbi_scientific_raster_reconciliation.py` cubre los ocho estados, aislamiento de una clave S3, rechazo de identificadores duplicados, permisos READ/tenant/actor, estado Campaign aprobado/publicado, falla del proveedor, gates de entorno y ausencia de acciones/grants/commits. La CI global sigue ejecutando los 26 checks existentes. No hay migraciones ni cambios en Render.
