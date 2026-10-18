# H14 / 2H-1 — Plan de recepción de siete rásteres científicos (sin transferencia)

## Objetivo y alcance implementado
El expediente H14 conserva dos carpetas y 13 originales: 1 TIFF RGB, 6 TIFF COG para índices NDVI, NDRE, GNDVI, EVI2, CI-red-edge y CI-green, y 6 estilos QML. Este incremento **solo prepara y valida el plan de carga para los siete TIFF**. Reutiliza el manifiesto inmutable del PR #259; no necesita recibir nuevos datos del navegador ni crear un activo o sesión.

Nuevo endpoint de lectura privada:

`GET /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/scientific-intake/private-raster-multipart-preflight`

Antes de acceder a S3, exige permiso **MANAGE** en tenant/organización/finca/lote; vuelve a leer Campaign **MULTISPECTRAL** en estado anterior a aprobación/publicación. Relee el manifiesto del PR #259, revalida la huella SHA-256 de su **JSON** e identidad scoped, y exige correspondencia exacta de siete roles/índices. Si falta el manifiesto: 404; ante corrupción: 503; nunca presenta una campaña ajena.

## Resultado para cada TIFF
El reporte devuelve identidad futura `planned_object_id` derivada exclusivamente del scope/Campaign/rol/índice; ruta relativa del original, tamaño y SHA-256 **declarados, NO VERIFICADOS**, MIME `image/tiff`, estrategia determinada por `DBIMultipartPolicy.build_upload_plan`, cantidad y tamaño de partes, concurrencia y algoritmo de checksum de transporte. Las siete identidades usan `ANALYSIS_INPUT` sin rutas locales, bucket, URL S3 ni secreto.

**La política multipart existente se reutiliza, no se reimplementa:**
- Tamaños de hasta **64 MiB** resultan `synchronous` (solo clasificación; **ningún handler de carga síncrona se activa**).
- Por encima de 64 MiB, hasta el límite permitido por la política, `multipart` con partes nominales de **64 MiB**, máximo **10.000 partes**, ventana de **8 grants** y concurrencia cliente máxima de **4**. Este endpoint **no emite esos grants**.
- Un archivo declarado que supera política multipart devuelve `blocked_by_policy` (si se permitiera desde contrato de entrada). El manifiesto H14/2F ya restringe cada TIFF a **10 GiB** y conjunto 13 archivos a **60 GiB**; la política multipart estándar admite 20 GiB por objeto. Estos límites provienen de capas independientes y se aplican conservadoramente.
- El transporte multipart `SHA256 / COMPOSITE` **NO es el SHA-256 completo del TIFF**. Es requisito futuro hacer streaming de bytes ensamblados desde almacenamiento privado y comparar con el SHA-256 completo declarado antes de certificar el archivo. Un ETag tampoco certifica contenido completo.

## Guardas y prohibiciones
`DBI_SCIENTIFIC_RASTER_PREFLIGHT_ENABLED=1` y `DBI_ENVIRONMENT=test|development|local` son necesarios **conjuntamente** para registrar/invocar la ruta. En `production`, `staging` o sin entorno definido, la ruta permanece inaccesible aunque alguien active el flag. Se exige proveedor `DBIS3ObjectStore` privado para leer el manifiesto; las pruebas reemplazan explícitamente el provider con uno de memoria.

El reporte contiene de modo literal `ready_for_upload=false`, `sessions_created=false`, `grants_issued=false`, `raster_bytes_received=false`, `raster_content_verified=false`, `scientific_validated=false`, `institutional_approved=false` y `published=false`.

**No hay ninguna nueva ruta PUT/POST**, sesiones reales, subida S3, reanudación, escritura SQL, migración, concesión temporal, interfaz administrativa de carga ni producto público. Respuesta `Cache-Control: no-store`; el visor cliente no se modifica.

## Por qué NO conectar directamente el uploader multipart antiguo
El uploader actual `DBIMultipartUploadService` exige un **Asset duradero `registered`**, sesión transaccional y ámbito asociado. El adaptador `DBIS3MultipartAdapter` exige destino **loopback** por contrato y es no productivo. Tampoco el modelo actual vincula automáticamente sus registros de activos con cada uno de los siete roles y SHA-256 del manifiesto científico. Saltarse esas restricciones permitiría sesiones huérfanas, archivos de Campaign equivocada o marcar como completo un checksum compuesto de transporte.

## Próximas etapas necesarias
1. Asociación duradera exacta Campaign + versión/huella de manifiesto + uno de siete roles + Asset + actor, con políticas de idempotencia, caducidad, revocación, quotas y bloqueo postaprobación.
2. Sesiones multipart transaccionales por objeto para entornos permitidos; autorización de partes temporales, cancelación/reanudación, comprobación exacta de rango, tamaño y checksums de partes. Requiere proveedor S3 privado apto para el entorno objetivo, y diseño/test de recuperación tras error.
3. Tras ensamblaje, **verificar SHA-256 completo del TIFF** leyendo el contenido desde S3, inspeccionar TIFF/COG (estructura, metadatos geoespaciales, bandas, CRS, resolución, pixel interpretation), comparar 7 recibos con manifiesto y separar inspección técnica de aprobación institucional.
4. Solo después de aprobación expresa, diseñar la publicación atómica de capas de cliente. **Prohibido activar esta ruta o cualquier uploader experimental en Render ahora**.

## Pruebas
`.github/scripts/ci_dbi_scientific_raster_preflight.py` asegura siete pares únicos, un RGB y seis COG, determinismo de claves scoped, datos declarados vs SHA-256 de bytes reales, políticas síncrona y multipart de 64 MiB, no mutación, ausencia de manifiesto, corrupción, READ/tenant ajenos, Campaign no MULTI/aprobada/publicada y cierre estricto en producción/staging. Se ejecuta en el job de backend de CI.

**Dependencia GitHub:** este PR se prepara desde PR #259 (manifiesto); no debe fusionarse en `main` antes de #259. Es independiente del PR #261 (conciliación QML), por lo que ambos pueden revisarse por separado tras #259.
