# H14 / 2H-2D/3B — Inventario forense postaprobación de multipart S3 (solo lectura)

## Finalidad y dependencia
Ampliación **separada** de H14/2H-2D/3A (#268): permite identificar un inicio S3 multipart incompleto aunque la Campaign ya esté `APPROVED` o `PUBLISHED`. Es un **diagnóstico privado** para responsables con permiso `MANAGE` y alcance exacto, nunca una excepción a las restricciones operativas de recepción.

Cadena GitHub: **#259 → #262 → #263 → #264 → #265 → #266 → #267 → #268 → esta etapa**. El PR debe quedar apilado sobre la rama de #268. No hay nueva migración ni cambios en tablas.

## Ruta administrativa aislada
`POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/scientific-intake/private-raster-postapproval-forensic/{role}/{index}`

Usa el mismo payload estricto y el mismo expediente inmutable H14: `schema_version`, `manifest_sha256`, `reservation_sha256`, `idempotency_key`.

La ruta se registra **solo si ambas condiciones se cumplen**:
- `DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_INVENTORY_ENABLED=1`.
- `DBI_ENVIRONMENT=test|development|local`.

`staging`, `production` y entornos no declarados devuelven 404 incluso si se activa el flag. **No configurar el flag en Render**, ni exponer el endpoint a clientes.

## Algoritmo y barreras
1. Exige `DBIPermission.MANAGE` sobre tenant + organización + finca + lote. Toma un **`SELECT FOR UPDATE`** de la Campaign exacta antes de acceder al almacenamiento.
2. Acepta exclusivamente `analysis_type='multispectral'` y estado coherente **`APPROVED` con `approved_at` no nulo y `published_at` nulo**, o **`PUBLISHED` con ambos timestamps no nulos**. Deniega borradores, revisiones, timestamps inconsistentes y scopes ajenos. **No altera** el guard preaprobación de `start`/`inspect`/`abort` del PR #267.
3. Comprueba los bytes y SHA-256 del **manifiesto y reserva JSON** privados, el operador reservador, el rol/índice, el objeto TIFF determinista y la ausencia del TIFF final. Revalida bajo locks las filas SQL Binding, Asset, preparación e inicio S3, incluida su idempotencia.
4. Lista las sesiones **incompletas** del objeto S3 exacto por `DBIS3MultipartAdapter.inspect_incomplete_uploads`, heredado del PR #268. Se rechazan inventarios ilegibles, duplicados o paginación incompleta; no se emiten decisiones positivas ante fallos del proveedor.
5. Clasifica los mismos ocho estados del PR #268 y devuelve solo `incomplete_upload_count`, `unexpected_upload_count`, coincidencia con SQL y estados de revisión. Hace **`rollback` solo para liberar locks**; nunca ejecuta `commit`, `abort`, `initiate` ni escrituras.
6. Devuelve `manual_review_required=true` para **cualquier inicio remoto/SQL aún activo** tras aprobación, incluso si la referencia coincide exactamente; también para huérfanos, cargas adicionales o discrepancias. Los únicos estados sin revisión pendiente son `no_remote_no_sql` y `sql_aborted_no_remote`.

## Advertencias institucionales
- La respuesta incluye `campaign_status=APPROVED|PUBLISHED`, pero **NO** afirma que el TIFF científico esté aprobado o publicado: `raster_institutionally_approved=false`, `raster_published=false`.
- `upload_access_blocked=true`, `cleanup_performed=false`, `ready_for_upload=false`, `grants_issued=false`, `file_received=false`. La respuesta no contiene `UploadId`, bucket, nombre de objeto S3, URL ni credenciales.
- El diagnóstico **no es una autorización para borrar** ni un certificado de integridad: el listado multipart no prueba que existan partes, que un objeto esté completo, ni que su SHA-256 sea correcto. La carga podría cambiar después de la enumeración (instantánea no atómica entre SQL y S3).
- La consulta posaprobación sigue exigiendo el **mismo operador que reservó** el archivo; un protocolo de relevo administrativo entre operadores deberá aprobarse explícitamente antes de introducir cambios.
- **La próxima etapa** debe diseñar un procedimiento de limpieza administrativa postaprobación con auditoría SQL duradera, autorización especial, manejo de commits inciertos, compensación por errores S3 y pruebas efectivas con MinIO local. No habilitar grants ni hacer borrados automáticos antes de cubrir esos requisitos.

## Validación
`.github/scripts/ci_dbi_scientific_raster_postapproval_forensic.py` cubre aprobación/publicación válidas, estados preaprobación rechazados, inconsistencias de timestamps, scope/READ/operador ajenos, huérfanos, carga exacta tras aprobación, cargas faltantes/adicionales, prohibición del endpoint legacy, flag/entorno, ausencia de grants y ausencia de cualquier mutación S3/SQL. Usa almacenamiento y proveedor **simulados offline**, no un ensayo de transferencia real con MinIO.

**No hay migraciones, despliegues, cambios en Render ni publicación de datos clientes.**
