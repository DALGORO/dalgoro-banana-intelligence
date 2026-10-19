# H14 / 2H-2D/3F — Revisión independiente de observación privada, no autorizante

## Propósito y dependencias

Se añade un **segundo operador con permiso MANAGE**, diferente del autor original de la observación archivada en H14/2H-2D/3E (#274). Se registra en S3 privado una **constancia inmutable de que revisó esa observación**. Esta constancia no representa firma institucional, aprobación de limpieza ni mandato de ejecución. Solo es evidencia documental de la revisión del *snapshot* JSON previo; no certifica que el inventario remoto S3 siga igual.

**Cadena apilada:** #259 → #262 → #263 → #264 → #265 → #266 → #267 → #268 → #269 → #270 → #272 → #274 → este PR. El #271 es una variante de auditoría postaprobación parcialmente solapada con #270 y debe tratarse como alternativa, no fusionarse a ciegas. Mantener `main` intacto.

## Ruta y guardas

`PUT /api/v1/dbi/organizations/{org}/farms/{farm}/plots/{plot}/campaigns/{campaign}/scientific-intake/private-raster-cleanup-peer-review/{role}/{index}`

Para habilitarla deben cumplirse **todas** las variables:

- `DBI_SCIENTIFIC_CLEANUP_PEER_REVIEW_ENABLED=1`
- `DBI_SCIENTIFIC_CLEANUP_EVIDENCE_ENABLED=1`
- `DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED=1`
- `DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED=1`
- `DBI_ENVIRONMENT=test|development|local` (en `production`/`staging` devuelve 404 incluso con todas las flags).

El operador revisor requiere **MANAGE** sobre tenant/organización/finca/lote. Antes de acceder a S3 se bloquea con `SELECT FOR UPDATE` la Campaign exacta MULTISPECTRAL, estrictamente `APPROVED` o `PUBLISHED` con timestamps coherentes. El rol/índice debe ser una de las siete posiciones científicas existentes. Se impide expresamente revisar la propia observación.

El payload es estricto, con `schema_version`, `original_actor_ref`, `evidence_sha256`, `original_object_sha256` y reconocimiento literal `reviewed_snapshot_not_cleanup_authorization`. El cliente **no puede suministrar permisos, decisiones de limpieza ni URL o claves S3**.

## Comprobaciones de integridad

1. Calcula en servidor la dirección opaca UUIDv5 de la observación original usando actor/ámbito/rol/índice y huella de evidencia declarados; no acepta rutas S3.
2. Relee el JSON original desde `DBIS3ObjectStore` privado y verifica identidad exacta del objeto, tipo `application/json`, tamaño máximo **8 KiB**, SHA-256 de bytes y serialización JSON canónica.
3. Verifica ámbito completo, autor original, rol/índice, huella declarada y `original_object_sha256`. **El estado de Campaign de la observación debe coincidir con el estado bloqueado actual**. Si pasó de APPROVED a PUBLISHED, obliga a generar una nueva observación, no reutiliza la antigua como vigente.
4. Constata que el original sigue siendo una observación de solo diagnóstico: nunca firmado, autorizado, ejecutado, recibido, validado ni publicado.
5. Almacena constancia inmutable de un revisor **distinto del autor**, con UUIDv5 que liga tenant/ámbito/Campaign/rol/índice, actor revisor, objeto original y su SHA. Reintento exacto devuelve **200**, primera creación **201**, conflicto **409**; se releen y verifican los bytes nuevos y su SHA. Libera el bloqueo de Campaign mediante `session.rollback()`, sin escribir en SQL.
6. La constancia no contiene `UploadId`, bucket, claves S3, URLs, presigned grants o acción ejecutable.

## Respuesta y límites institucionales

La respuesta distingue `review_recorded=true`, `independent_actor=true` y `snapshot_only=true`, pero impone de forma literal `evidence_signed=false`, `cleanup_authorized=false`, `cleanup_executed=false`, `grants_issued=false`, `file_received=false`, `content_verified=false` y `published=false`.

**No hay firmas criptográficas, nombramiento/delegación institucional de revisores, segregación formal de funciones, control de retención, autorización de aborto remoto, limpieza, cambio en Render ni publicación.** El segundo MANAGE no es por sí solo un aprobador institucional. Antes de cualquier aborto real siguen pendientes un esquema oficial de autorizaciones y retención, firma/verificación, revalidación S3+SQL inmediatamente antes de la acción y pruebas de concurrencia/compensación ante fallos de red.

## Validación

Script `.github/scripts/ci_dbi_scientific_raster_cleanup_peer_review.py`: doble de S3 privado en memoria **solo para tests**, control de Campaign mediante repositorio sintético, distinción de actores, idempotencia, tercero revisor, tenant/READ ajenos, cambio APPROVED→PUBLISHED, corrupción de bytes originales, hashes divergentes, flags de entorno y ausencia de abort/grants. La CI global mantiene el ensayo MinIO loopback de #269, pero el endpoint nuevo **no está probado de extremo a extremo contra PostgreSQL+MinIO simultáneamente**.

Sin migraciones nuevas y **sin cambios en `main`/Render**.
