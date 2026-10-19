# H14 / 2H-2A — Reserva privada e inmutable de siete posiciones raster

## Alcance exacto
Primera parte de H14/2H-2. El objetivo final sigue siendo enlazar los siete TIFF científicos con **Campaign + manifiesto + registro durable de activo + sesión multipart**. Esta entrega cubre **únicamente la reserva duradera de metadatos** por ranura, sin sesiones multipart ni transferencias.

Se apila sobre H14/2H-1 (#262) y H14/2F (#259). Las siete posiciones son una ortofoto `rgb` y seis `scientific_cog` (NDVI, NDRE, GNDVI, EVI2, CI-red-edge, CI-green). La fuente de autoridad de rol, tamaño declarado, ruta original y SHA-256 declarado es el **manifiesto inmutable ya escrito**.

## Contrato HTTP
Solo al activar conjuntamente `DBI_SCIENTIFIC_RASTER_RESERVATION_ENABLED=1` y `DBI_ENVIRONMENT=test|development|local`:

- `PUT /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/scientific-intake/private-raster-slots/{role}/{index}`
- `GET` sobre la misma ruta, solo metadatos autorizados.

Para la ortofoto RGB: `role=rgb`, `index=_` (sentinela de URL, guardado internamente como `null`); para COG `role=scientific_cog`, `index` igual a uno de los seis índices. Cualquier otra combinación se rechaza.

`PUT` recibe solo `{"schema_version":"dbi-h14-raster-slot-request.v1","manifest_sha256":"<64 caracteres hexadecimales minúsculos>"}`. No acepta SHA, tamaño, ruta, clave S3 ni rol de archivo arbitrarios en el cuerpo. El servidor deriva todos esos datos del manifiesto con huella exacta, no de metadatos del cliente.

## Controles
1. **MANAGE** sobre organización/finca/lote, lectura nueva y exacta de Campaign MULTISPECTRAL antes de aprobada/publicada en cada operación. READ o ámbito ajeno obtiene 404, sin revelar el almacenamiento.
2. **Solo DBIS3ObjectStore privado y durable** para escritura y lectura. Se niega almacenamiento local o memoria en ruta real; test offline usa inyección controlada. No se activa en Render, staging ni producción.
3. Un objeto de reserva JSON `ANALYSIS_INPUT` con UUIDv5 opaco para **tenant + organización + finca + lote + Campaign + rol + índice**, **distinto** del UUIDv5 del futuro archivo TIFF. Así un JSON nunca ocupa o sobrescribe la dirección futura del raster.
4. El objeto incluye `manifest_object_id`, `manifest_sha256`, `target_object_id`, ruta original relativa, hash y tamaño declarados, actor autenticado `reserved_by`, y todas las banderas de ejecución/validación/publicación **falsas**. El registro de creación S3 aporta `created_at`. Hasta siete reservas por campaña, una por rol/índice.
5. Serialización canónica JSON, **8 KiB máximo por reserva**, `sha256` del JSON y `put` condicional `IfNoneMatch=*` del puerto DBI. Un reintento exacto devuelve 200; reserva distinta (incluido otro actor) devuelve 409; una nueva devuelve 201. El GET verifica los bytes del JSON, la identidad del objeto y su coherencia actual con el manifiesto. Otros administradores autorizados pueden inspeccionar sin reemplazar el primer actor.
6. Si el objeto TIFF destino ya existe sin este flujo, PUT niega reserva (409) en vez de generar una asociación retroactiva potencialmente falsa. La reserva no crea ni actualiza ese destino, Asset ni Session.
7. `Cache-Control: no-store`. No emite claves de acceso, URL ni grant.

## Lo que NO se ha implementado
- La reserva es persistencia privada **en S3**, no un vínculo transaccional con tablas `AnalysisInputAsset` ni `AssetMultipartSession`. No sustituye una auditoría SQL institucional ni un evento firmado.
- **No registra un Asset** ni inicia sesiones/reanudación/cancelación. No hay PUT de bytes raster, presigned URLs, endpoints para partes, cambios de Campaign, migraciones ni publicación.
- **No valida** que el TIFF/COG real tenga el tamaño y SHA declarados, ni bandas, CRS, estructura o cálculo de índices. Un recibo de reserva **no** acredita recepción.
- No reutilizar sin revisión `DBIMultipartUploadService`: actualmente exige Asset `registered` con tipos `orthophoto` / `flight_auxiliary`, pero no hay `scientific_cog` de Campaign en el modelo, y su adaptador S3 multipart solo acepta endpoints loopback. Tampoco las rutas de grants/completado legacy releen la Campaign.
- La futura incorporación de sesiones requerirá **identidad de activo científico durable** y bloqueo transaccional ligado al manifiesto, validación Campaign en **cada** operación (crear, conceder partes, registrar evidencia, completar, abortar, limpiar, reanudar), control de concurrencia, y prueba de integridad completa de objeto ensamblado, además de políticas institucionales de retención.
- **No activar este flag en producción o staging** (incluso si se configurase allí, el código deniega el endpoint).

## Validación CI
`.github/scripts/ci_dbi_scientific_raster_reservations.py` usa siete ranuras sintéticas y el puerto DBI en memoria solo como doble inyectado. Verifica: cuenta exacta y claves distintas, coincidencia con manifiesto, identidad futura distinta de la reserva, SHA del JSON, actor de creación, idempotencia, GET de otro MANAGE, rechazos de roles/índices/manifest divergente, READ/tenant ajenos, Campaign no-MULTI/aprobada/publicada, corrupción, almacenamiento ausente y denegación en `production`/`staging`. Sin red, DB real ni Render.

**Dependencias GitHub:** PR #259 -> #262 -> este PR; el #261 (conciliación QML) es independiente de los slots raster. No fusionar a `main` fuera de orden.
