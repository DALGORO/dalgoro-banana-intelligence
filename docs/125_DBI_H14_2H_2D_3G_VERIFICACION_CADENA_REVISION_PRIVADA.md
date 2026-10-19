# H14 / 2H-2D/3G — Verificación privada de cadena de evidencia con dos actores

## Objetivo
Esta etapa permite al **segundo revisor original** (MANAGE) comprobar en lectura la consistencia de una observación S3 privada e inmutable (#274) con su constancia de revisión por actor independiente (#275). También vuelve a comprobar que la Campaign MULTISPECTRAL continúa en el mismo estado institucional (APPROVED o PUBLISHED) que consta en ambos registros.

**No significa que el inventario remoto actual siga idéntico**. Deliberadamente la respuesta fija `live_s3_inventory_rechecked=false`, `cleanup_authorized=false`, `cleanup_executed=false` y `evidence_signed=false`.

## Dependencias
**PR #259 → #262 → #263 → #264 → #265 → #266 → #267 → #268 → #269 → #270 → #272 → #274 → #275 → 3G.** La alternativa #271 es parcialmente solapada con #270 y requiere resolución de revisión; no debe fusionarse ciegamente.

## API y autorización
`POST /api/v1/dbi/organizations/{org}/farms/{farm}/plots/{plot}/campaigns/{campaign}/scientific-intake/private-raster-cleanup-review-chain/{role}/{index}`

Payload estricto `dbi-h14-observation-review-chain-request.v1`: `original_actor_ref`, `reviewer_actor_ref`, `evidence_sha256`, `original_object_sha256`, `review_object_sha256`. No admite una clave de idempotencia prestada ni una dirección S3 arbitraria; el servidor deriva ambas direcciones opacas del ámbito y de los hashes.

Se registra únicamente al activar juntas las flags `DBI_SCIENTIFIC_CLEANUP_CHAIN_VERIFY_ENABLED`, `DBI_SCIENTIFIC_CLEANUP_PEER_REVIEW_ENABLED`, `DBI_SCIENTIFIC_CLEANUP_EVIDENCE_ENABLED`, `DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED`, `DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED`, todas en `1`, y `DBI_ENVIRONMENT=test|development|local`. No disponible en staging/producción incluso si alguien enciende todas las flags. **No activar en Render.**

1. Requiere MANAGE exacto y bloquea Campaign con `SELECT FOR UPDATE`; confirma APPROVED/PUBLISHED y timestamps coherentes.
2. El principal autenticado debe coincidir con el **revisor**, y ser distinto del actor que produjo la observación. **No** se suplanta al autor para inspeccionar S3 ni para reabrir una sesión multipart.
3. Solo a través del almacén S3 privado se leen los **dos JSON originales** (máximo 8 KiB cada uno): metadatos MIME/longitud/dirección, SHA-256 efectivo de bytes y serialización canónica. Se comprueban hashes facilitados, tenant/org/finca/lote/Campaign, rol/índice, identidades de ambos autores, encadenamiento del objeto original y de la revisión, y estado institucional de ambos frente a Campaign actual.
4. Se devuelve únicamente un recibo de verificación documental. `session.rollback()` libera el bloqueo sin escribir SQL. No escribe S3 ni modifica las evidencias; no devuelve UploadId, bucket, clave o URL.

## Restricciones
- No se vuelve a listar S3 multipart ni se afirma que el objeto haya desaparecido, sido abortado o permanezca presente. Cualquier futura decisión **deberá** hacer inventario en vivo, tratar cambios concurrentes y exigir mandato institucional verificable; una constancia de revisión no sustituye esas pruebas.
- No hay firmas criptográficas de actores, delegación institucional autorizada, evidencia de retención, permiso de aborto, subida de partes TIFF, checksum completo de raster, datos validados o publicación.
- El estado `PUBLISHED` de Campaign no implica publicación ni validación científica de este TIFF particular.

## Pruebas
`.github/scripts/ci_dbi_scientific_raster_cleanup_review_chain.py` usa dobles sintéticos de objetos privados y Campaign para comprobar un par de documentos verificable, idempotencia de consulta, SHA originales/revisor contradictorios, corrupción de bytes, actor/tenant ajenos, READ, cambio de APPROVED a PUBLISHED, exclusión en production/staging, ausencia de `put`, `commit`, grants/abortos y salida siempre no autorizante.

El test de protocolo MinIO en CI continúa independiente; esta nueva comprobación documental no se declara E2E PostgreSQL + S3 real.
