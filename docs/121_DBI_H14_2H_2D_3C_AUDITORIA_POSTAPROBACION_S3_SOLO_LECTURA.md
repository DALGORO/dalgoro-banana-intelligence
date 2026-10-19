# DBI H14 / 2H-2D/3C — Auditoría institucional postaprobación (solo lectura)

## Propósito
Incremento sobre **#269 → #268 → #267 → #266 → #265 → #264 → #263 → #262 → #259**. El proceso de carga experimental existente deja de admitir `start`, `inspect` y `abort` al aprobarse la Campaign. Eso protege la integridad pero impedía al personal institucional **inspeccionar las cargas incompletas que quedaron abiertas después de aprobar**. Esta fase habilita únicamente un **diagnóstico protegido**, no la limpieza ni la transferencia.

## Control de acceso independiente
Endpoint `POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/scientific-intake/private-raster-postapproval-audit/{role}/{index}`.

Requiere **ambos** permisos `MANAGE` **y** `APPROVE_AGRONOMIC` sobre el tenant, organización, finca y lote exactos; no basta uno solo. Bajo un `SELECT ... FOR UPDATE` de Campaign confirma `analysis_type='multispectral'` y aprobación/publicación por estado o timestamp. Se rechazan entidades ajenas, Campaign previa a aprobación, READ y usuarios con un solo permiso. Se admite que el aprobador sea **distinto del operador que reservó**, sin conocer, revelar o copiar su clave de idempotencia. El payload incluye únicamente las huellas SHA-256 del manifiesto y la reserva, más `schema_version=dbi-h14-postapproval-audit-request.v1`; no incluye UploadId, secretos ni destinos.

Solo se registra con **`DBI_SCIENTIFIC_POSTAPPROVAL_AUDIT_ENABLED=1` Y `DBI_ENVIRONMENT=test|development|local`**. En `staging`/`production` no existe la ruta incluso con el flag. No activar en Render.

## Comprobación técnica
Tras bloquear Campaign:
1. Relee manifiesto y reserva originales del objeto S3 privado y comprueba integridad, huellas, ubicación, rol y dueño original. El aprobador no reemplaza al operador.
2. Bloquea y valida las **cuatro filas SQL**: Binding, Asset científico, ticket preparatorio y, si existe, inicio S3. Compara scope, Campaign, hash de originales, identidad, tamaño declarado y estado inmutable. La ausencia de Binding/Asset/ticket o cualquier divergencia devuelve conflicto, no diagnostica como sano.
3. Reconstruye el contrato de transporte desde evidencia SQL/S3 confiable (sin usar ni exigir la clave idempotente original), y consulta en S3 loopback las cargas incompletas de la clave exacta del TIFF.
4. Clasifica usando los ocho estados ya definidos en #268; señala `manual_review_required=true` para **cualquier sesión S3 todavía activa después de aprobar**, incluso cuando coincide perfectamente con SQL. Comprueba además la existencia de un objeto TIFF inesperado en destino y lo señala para revisión; no lo lee ni lo da por validado.
5. Ejecuta `session.rollback()` para liberar bloqueos **sin persistir cambios**. La respuesta muestra conteos, estado y riesgos, pero jamás referencias de carga, rutas, bucket, credenciales, URLs ni información de acceso a partes.

Una Campaign con estado aparentemente previo pero con timestamp de aprobación/publicación contradictorio puede ser auditada para detectar inconsistencias, que deben quedar marcadas para revisión. El endpoint **no aprueba ni publica**.

## Frontera de seguridad
**No se inicia ni aborta S3**, no se emiten grants ni URLs, no se suben partes, no se cambian activos, no se ejecutan migraciones y no se valida ningún SHA-256 del TIFF. La respuesta impone `automatic_cleanup_performed=false`, `ready_for_upload=false`, `grants_issued=false`, `file_received=false`, `content_verified=false` y `published_by_this_audit=false`. Si falla S3, la BD o los hashes, devuelve error; **no simula un informe fiable**.

La auditoría es una instantánea, no demuestra atomicidad S3↔SQL. No sustituye auditoría institucional registrada en un expediente duradero ni un registro de trazabilidad firmado. No demuestra que la aprobación en otros módulos siempre use el mismo bloqueo de Campaign; **auditar esas transiciones es requisito para un futuro aborto administrativo**.

## CI
`.github/scripts/ci_dbi_scientific_raster_postapproval_audit.py` utiliza escenario completo sintético: S3 privado, Binding + Asset + ticket SQL, aprobador independiente con doble permiso, S3 huérfano y coincidente, inicio extra/ausente, rollback sin commits, rechazo de permisos/scope, Campaign preaprobación, TIFF inesperado, caída de S3 y feature flags cerrados en production/staging. La conciliación real con MinIO local ya tiene cobertura en #269, pero **este endpoint usa dobles** y todavía requiere pruebas de concurrencia real y un plan formal de cleanup institucional.

## Próximo incremento
H14/2H-2D/3D: auditoría transaccional de los flujos de aprobación y *protocolo conservador de recuperación* para cargas S3 huérfanas o commit SQL incierto, con pruebas de carreras y operación administrativa específica. No conceder permisos de partes antes de cerrar esas garantías.
