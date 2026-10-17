# H13 — Google Satélite estable, ráster RGB liviano y estilos recuperados

**Base inspeccionada:** `main@e142503cff82913b5ceb51d9f88447f02d1e1ef5`.
**Alcance de este PR:** resiliencia de la carga del proveedor Google, notificación y reintento del RGB privado. No altera ciencia, tiles, COG, CRS, autorización, publicación o producción.

## Funcionamiento real de la superposición

- Fondo Google Maps JavaScript API oficial con `mapTypeId: "satellite"` y atribuciones visibles.
- Los productos propios pueden estar en **EPSG:32717 (WGS84 / UTM 17S)** o cualquier otro CRS auténtico registrado; los rásteres se reproyectan **al vuelo** vía Rasterio `WarpedVRT` hacia **EPSG:3857** para tiles XYZ compatibles con Google; se preserva el maestro y sus metadatos.
- Google utiliza longitud/latitud WGS84 para ubicaciones y la proyección Mercator para la cuadrícula de tiles. Disponer del CRS correcto no garantiza alineación centimétrica: el control exige ortorrectificación, GCP/RTK y comparación de puntos independientes.
- Google Earth no entrega mosaicos libres para descargar y redistribuir. Usar Google Maps Platform con clave, facturación, autorización de dominio y atribución; no scrape, pre-cache ni usarlo como insumo para identificar plantas.

## Problemas corregidos en este PR

1. Si el SDK no responde, la carga falla tras **18 segundos**. Se limpia el script fallido, el callback y el estado de promesa para permitir un reintento real desde la interfaz.
2. El productor ve **Conectando con Google Satélite…**, un mensaje de error y un botón **Reintentar Google Satélite**; nunca se simula el fondo.
3. Si el tile RGB falla por 401/403/429, error de servidor, red o contenido inválido, se informa que Google continúa de fondo y se ofrece **Reintentar fotografía RGB**, sin desmontar/reiniciar el mapa de Google.
4. Los tiles fuera del vuelo que devuelven 404 no disparan alarmas de error. Los abortos normales por navegación tampoco.
5. La opacidad RGB 0 % conserva Google y deja de pedir RGB; sus tiles autorizados siguen siendo de **256 × 256** y las URL Blob se liberan al descartar la capa.

## Rendimiento actual y próximo gate

- El COG RGB oficial utiliza bloques de 512 y overviews; el modo normal `cog_v1` con compresión DEFLATE sigue activo en `pilot_builder.py`.
- Está implementado pero **sin activar por defecto** el perfil opt-in `cog_rgb_preview_jpeg_v1`: JPEG/YCBCR calidad 80 para copia de presentación RGB **3 bandas uint8 sin NoData**. El GeoTIFF científico original no se modifica.
- El cliente consume tiles PNG 256×256; el preview JPEG en disco no implica por sí mismo menor descarga al navegador. Para ganar ancho de banda, evaluar **WebP** RGB versionado, preferiblemente con transparencia válida y caché segura, medir kilobytes, latencia, CPU y compatibilidad antes de activarlo.
- **No** cambiar a JPEG productos científicos Float32; evitar reducir o descartar bandas, valores de reflectancia, georreferencia y máscara NoData.

## Estilos históricos vs archivos confirmados

Referencias de trabajo previo en QGIS, no `.qml` espectrales en este repositorio:

- RGB `RGB_2_98.qml`: composición natural R/G/B y stretch visual P2–P98 por banda; la web actual usa `rgb-natural-v1` sin estiramiento extra para no duplicar normalización.
- NDVI `NDVI_DIAGNOSTICO_2_98.qml`, NDRE `NDRE_DIAGNOSTICO_2_98.qml`: pseudocolor RdYlGn (rojo menor, amarillo intermedio, verde mayor), siete clases interpoladas y corte P2–P98 propio del vuelo.
- GNDVI: existe referencia histórica al nombre `GNDVI_DIAGNOSTICO_2_98.qml` pero **no sus paradas de color exactas**.
- EVI2, CI Red Edge y CI Green: cálculos científicos presentes, QML exactos no recuperados.
- Los estilos GIS de plantas, hexágonos y zonas de población **sí** están versionados en `services/banana-density/resources/qgis/styles/`. No confundir clasificaciones de densidad con índices espectrales.

El color relativo de una escena no diagnostica por sí solo enfermedades ni hace comparables campañas distintas. Las seis capas de índices **en formato raster georreferenciado** permanecen pendientes de construir, validar y publicar institucionalmente.

## Pruebas y límites

- Pruebas de integración estática para loader, timeout, recuperación, scope, tamaño del tile, ausencia de fondo ficticio y limpieza de recursos.
- Las pruebas CI de frontend y backend no sustituyen una prueba de carga real con una clave Google válida ni una ortofoto aprobada en Render.
- No se despliega, acredita personal ni se modifica cualquier workflow de aprobación o módulo ML/GIS científico.
