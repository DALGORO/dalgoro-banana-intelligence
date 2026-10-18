# H14 / Etapa 2B — Borrador local de preparación de RGB + seis mapas científicos

## Qué se puede hacer ahora

En «Gestionar y publicar capas GIS» del lote (acceso MANAGE), seleccionar las dos carpetas del levantamiento como antes y el levantamiento real. Aparece un bloque **«Preparar RGB y seis mapas científicos»**, que comprueba el pareamiento de **13 archivos candidatos**: una ortofoto RGB en la carpeta geoespacial y los pares TIFF/QML de los seis índices (`ndvi`, `ndre`, `gndvi`, `evi2`, `ci_red_edge`, `ci_green`) en la carpeta multiespectral.

El administrador obtiene una relación explícita de faltantes, candidatos duplicados, TIFF de la carpeta 1 sin clasificación y archivos de tamaño cero. Solo si hay identidad completa de `tenant_ref`, `organization_ref`, `farm_id`, `plot_id` y un `campaign_id` técnico real, y no existen bloqueos, se habilita **«Exportar borrador JSON local (sin subir archivos)»**.

La descarga contiene nombres de archivo relativos, sus tamaños, identidad de campaña y rol provisional. No se genera ni transmite una URL pública, ni se lee el contenido, ni se genera un hash de archivo ficticio. Es un artefacto de planificación local para facilitar después la subida científica por lotes.

## Garantías negativas del contrato

La estructura `dbi-h14-scientific-reception-draft.v1` declara siempre:

- `state: "local_metadata_only_not_uploaded"`
- `structural_ready: true/false`, **solo validez de clasificación por nombre/ruta**;
- `scientific_validated: false`, `server_received: false`, `institutional_approved: false`, `published: false`;
- para cada archivo `sha256: null` y `file_content_verified: false`.

No debe confundirse con el expediente científico del worker `banana_analyzer.multispectral_map_preflight` (PR #249), que exige **COG Float32 reales, QML reales y lectura independiente de datos**. Tampoco es una licencia de publicación ni habilita tiles `READ` al cliente.

## Restricciones e interacción con etapa 2A

- La carga GIS privada de GPKG/ZIP de PR #252 sigue separada, protegida por servidor y no consume ni confía en este borrador.
- La selección de Carpetas solo acepta rutas relativas `webkitdirectory` válidas; metadatos inválidos o nombres ambiguos se rechazan.
- Se rechazan un índice duplicado, un QML ausente, la falta del RGB, cualquier TIFF geoespacial de tipo incierto y datos vacíos.
- La preparación es parcial si solo se ha entregado una carpeta; no se muestran mapas sintéticos.
- No hay persistencia local de expedientes ni almacenamiento en servidor del borrador, no hay firma criptográfica ni checksum, por lo que **un usuario podría editarlo** y la futura API **deberá revalidar todo**.
- Los estilos QGIS históricos siguen sin constar como archivos verificables dentro del repositorio.
- Con fines de usabilidad, este primer bloque muestra el número exacto `0..13` de candidatos y los problemas pendientes. No pretende ser una vista previa raster real.

## Siguiente hito

Aprobar un **contrato de recepción privada por archivo, con SHA-256, tamaños máximos, identidad completa y procesamiento en el worker Rasterio**, sin ampliar las rutas GIS vectoriales indebidamente. Los tipos `DBIAnalysisInputAsset` y `DBICampaignArtifact` actualmente no modelan los seis productos COG/QML individualmente; no habilitar carga ni publicación multiespectral en producción hasta diseñar la persistencia y migración verificadas.

Después: vista previa privada y conjunta desde el administrador, validación de grillas y estilos, aprobación institucional por índice y publicación por campaña. El productor solo verá capas efectivamente autorizadas.

## Pruebas

`apps/platform-web/frontend/tests/scientificReceptionDraft.test.mjs` valida 13 archivos, seis pares únicos, identidad de scope, cero bytes, duplicados, archivos faltantes, TIFF inciertos y ausencia de publicación. CI usa simulaciones de nombre/ruta; no sustituye pruebas con datos GIS reales o UAT en Render.
