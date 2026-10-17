# H13 · Fondo Google Satélite prioritario con recuperación cartográfica segura

## Estado verificado en GitHub

- Para lotes autenticados con `VITE_GOOGLE_MAPS_API_KEY`, el visor usa Google Maps JavaScript API con `mapTypeId: "satellite"`, **no** servicios de descarga de Google Earth.
- Google sirve su mapa en la proyección de mosaicos Web Mercator `EPSG:3857`. La fuente agrícola puede estar en WGS 84 / UTM 17 sur `EPSG:32717`; la transformación ocurre en la generación de mosaicos XYZ sin modificar el CRS original.
- El motor de densidad usa `WarpedVRT` y entrega mosaicos privados **256 × 256 px** por XYZ y autorización del lote. El cliente no descarga el GeoTIFF maestro.
- Hay un perfil de COG RGB visual `cog_rgb_preview_jpeg_v1`, comprimido en JPEG para fuentes RGB compatibles, independiente del COG científico y del maestro; no se cambia el contenido de las bandas científicas.
- Los tiles RGB siguen en formato PNG con transparencia sobre el fondo Google y caché regenerable; no se sustituyen por JPEG opaco ni se descargan los mapas de Google fuera de sus servicios oficiales.

## Mejora de este PR

Si el SDK de Google no inicializa por error de conexión, clave, dominios o cuota, el contenedor cambia a MapLibre con **fondo neutro explícito** y mantiene solo las ortofotos RGB/capas GIS reales y publicadas que ya ofrece el portal. Se presenta un aviso de la causa y un botón de reintento, sin imágenes ficticias ni peticiones a proveedores de imágenes no autorizados. La falla se asocia al scope exacto tenant/organización/finca/lote: no se arrastra a otros lotes.

**Limitación:** el fondo satelital de Google solo puede garantizarse si la cuenta, clave, servicio y conectividad están operativos. Google Maps no equivale a «descargar Google Earth gratuitamente» ni a imágenes georreferenciadas localmente en `EPSG:32717`.

## Sin cambios en

Fórmulas de seis índices, estilo científico sin confirmar, raster científico maestro, pipeline COG, precisión georreferenciada, autorización tenant/scope, aprobación institucional, almacenamiento, producción o Render.

## Criterios de aceptación

- Google disponible: la API sigue mostrando `satellite`, RGB y vectores en la misma vista.
- Error inicial del SDK: las capas autorizadas siguen disponibles sobre base neutra con texto honesto.
- Reintentar: se vuelve a intentar la carga de Google sin perder selección de Campaign/fecha.
- Cambio de lote: no se hereda un fallo de otro scope.
- CI frontend, backend, PostGIS y seguridad en verde; sesión real en navegador pendiente (no se simula Google).
