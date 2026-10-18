# H14 / Etapa 2A — Recepción privada de GIS detectado en carpeta 1

## Estado funcional
Se amplía el inventario de dos carpetas de H14 con una **primera recepción real de originales GIS** mediante el endpoint **existente** `POST .../map/gis-imports` protegido por permisos `MANAGE`, identidad de tenant/organización/finca/lote/Campaign y bloqueo en servidor de Campaign `PUBLISHED`.

En la misma sección de gestión del lote:

1. Seleccionar la **carpeta 1** de análisis geoespacial y, si se dispone, la **carpeta 2** multiespectral (inventario local).
2. El sistema localiza automáticamente exclusivamente `*.gpkg` y `*.zip` de la carpeta geoespacial. Muestra sus rutas y extensiones; no afirma identificar sus capas por dentro.
3. Elegir explícitamente un **levantamiento técnico real**, que no aparezca como `APPROVED` ni `PUBLISHED` en el selector de la UI.
4. Pulsar **Guardar originales GIS en privado**. Sólo entonces se envía cada `File` seleccionado en serie, uno por solicitud, con clase `other` (el nombre no acredita plantas, densidad ni límites).
5. El backend existente valida el original (ZIP/SQLite y límites) y guarda un recibo privado `received`, nunca una capa `READ`. La interfaz actualiza los recibos en «Archivos GIS y estado de revisión». Cada fuente sigue requiriendo worker de conversión, preview `MANAGE` y aprobación separada.
6. Si una operación falla se detiene la secuencia. Las entregas anteriores se muestran como recibidas; ningún registro se declara publicado.

## Controles
- Máximo **8 archivos GIS originales por intento** y **30 MiB cada uno**; cero bytes, rutas sin directorio válido, carpetas con errores, múltiples raíces, nombres >100 caracteres o duplicados de forma ambigua detienen el plan.
- Antes de iniciar, se consulta el servidor por recibos existentes y se **bloquea un nombre ya recibido** en la misma Campaign, en vez de presumir identidad entre archivos del mismo nombre. La consulta está limitada por el servidor a 50 recibos; no constituye idempotencia duradera ni evita todas las carreras.
- El botón se habilita sólo tras seleccionar Campaign autorizada y resolver todos los bloqueos. No se lee contenido de los TIFF/QML ni se ofrece publicación.
- El panel se desmonta por cambio de `gisScopeKey`, conservando el aislamiento del inventario en navegador.
- Se usan rutas privadas ya existentes y protección de servidor. No hay nuevo endpoint, credenciales o permisos públicos, tampoco migraciones.

## Fuera de esta etapa, explícitamente
- **No se suben ni preparan** COG RGB grandes, seis COG científicos, estilos QML, PDFs o GeoJSON desde el selector de carpetas. El flujo de carga de ortofotos existente no equivale a importación masiva de una carpeta.
- **No hay selección automática de layer_kind**; `other` es una categoría de espera no semántica.
- No hay carga directa desde carpeta 2: únicamente inventario y reporte de pares faltantes/ambiguos.
- No se completan ni se aprueban GIS automáticamente: dependerá de un worker conectado a almacenamiento privado, staging, preview y autorización final.
- Sin garantía de reanudación entre sesiones, cancelación de solicitudes ya enviadas, publicación atómica de toda la carpeta, checksum de contenido calculado por cliente ni carga de volúmenes enormes.
- La ruta legacy GeoJSON sigue siendo una funcionalidad separada que merece un endurecimiento posterior para exigir revisión antes de cualquier publicación.

## Próximos pasos en orden
1. Diseñar manifiesto vinculante de dos carpetas con campaña y firma/hash servidor, seguido de carga privada por partes de **COG/QML/PDF** y cotejo de huellas, sin tocar DB productiva sin migración planificada.
2. Preparación de ambos análisis por worker geoespacial aislado y validación de archivos **reales**, no sólo nombres.
3. Vista previa del conjunto al administrador con imágenes RGB, GIS, seis COG y estilos QGIS verificables.
4. Aprobación institucional de productos individualizados y publicación atómica de una versión, y solo entonces activación en el cliente.

## Verificación
`node --test tests/privateGISUploadPlan.test.mjs` (CI frontend) comprueba el plan de carga por tipo, privacidad, tamaños, ambigüedad, duplicados y exclusión de RGB/QML/PDF/GeoJSON. Mantener también `analysisFolderInventory.test.mjs`. CI no sustituye UAT real con S3/Render, worker y archivos de productores.
