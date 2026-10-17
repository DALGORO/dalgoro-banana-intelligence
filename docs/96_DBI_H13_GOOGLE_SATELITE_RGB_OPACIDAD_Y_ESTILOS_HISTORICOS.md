# H13 — Fondo Google Satélite + rásteres privados alineados, livianos y trazables

## Confirmación geoespacial

**Base de la interfaz:** Google Maps JavaScript API, modo oficial `satellite` con
`mapTypeControl: false`, atribución intacta y clave configurada en frontend.
La disponibilidad continua depende de la conexión, la clave, su facturación y
las condiciones de Google Maps Platform. **No es una descarga libre de Google
Earth:** no recopilar, extraer, cachear offline ni reutilizar sus imágenes como
fuente científica.

**Origen científico:** preservar CRS auténtico del producto, incluido
`EPSG:32717` (WGS 84 / UTM 17 S), transform, bounds, NODATA, checksum.
El render aislado `banana_analyzer/raster_tile_renderer.py` usa
`transform_bounds` + `WarpedVRT` hacia `EPSG:3857` en tiles XYZ.
Google Maps usa WGS84 para LatLng y Mercator para coordenadas de mosaicos.
No se cambia el CRS del maestro ni se asume que todas las fincas son 32717.
La alineación precisa necesita CRS, control de puntos, datum y orientación
correctos de origen; no puede certificarse sólo porque coincidan las etiquetas CRS.

## Qué se implementa en este PR

- Fondo satelital invariable cuando la integración Google está configurada
  (el usuario no puede cambiar accidentalmente a roadmap/hybrid).
- Control accesible **Opacidad RGB 0–100 %** en historial del vuelo. Valor
  inicial 75 %, con Google visible debajo del producto privado autorizado.
  Permite alternar Google solo y fotografía RGB íntegra; no altera ni genera
  la fuente, tampoco el valor científico de ningún índice.
- Mosaicos RGB privados de **256 × 256** y reproyección ya existentes.
- La opacidad actualiza nodos de mosaicos ya descargados; **no vuelve a pedir
  tiles en cada movimiento del control**. El ciclo de vida cancela peticiones
  pendientes y libera object URLs de una capa descartada.
- Si Google no está configurado o falla, no inventar fondo satelital. Se
  mantienen avisos existentes; prueba real con clave/licencia y red necesaria.

## Estilos recuperados y verificación

De conversaciones previas sobre QGIS, se recuperan los nombres:
`NDVI_DIAGNOSTICO_2_98.qml`, `NDRE_DIAGNOSTICO_2_98.qml`,
`RGB_2_98.qml`. No aparecen en el árbol de este repositorio:
**nombres/parametrización histórica no equivalen a QML versionado**.

| Producto | Estilo recuperado | Detalle confirmado en el diseño histórico |
|---|---|---|
| RGB | `RGB_2_98.qml` | Composición R-G-B con estiramiento visual de percentil 2 a 98 por canal |
| NDVI | `NDVI_DIAGNOSTICO_2_98.qml` | pseudocolor monobanda RdYlGn, siete clases continuas, P2–P98, lineal, rojo bajo a verde alto |
| NDRE | `NDRE_DIAGNOSTICO_2_98.qml` | mismo patrón histórico P2–P98, RdYlGn, siete clases, lineal, rango de muestra de referencia NO UNIVERSAL |
| GNDVI, EVI2, CI Red Edge, CI Green | cálculo científico disponible | **no existe paleta QML inequívocamente confirmada en el repo**; no heredar automáticamente escalas de NDVI |

Los números P2–P98 recuperados de un vuelo anterior NO son umbrales
agronómicos globales ni diagnóstico y no deben convertirse en límites fijos
de leyenda para otros vuelos.

## Carga liviana sin degradar ciencia

- El servidor ya utiliza `tile_size=256`, COG con overviews, range reads
  privadas y caché segregada por tenant y huella del producto/estilo.
  El navegador no descarga el GeoTIFF maestro para la vista de mapa.
- `raster_cog.py` ya contiene un perfil **opt-in**
  `cog_rgb_preview_jpeg_v1` (JPEG, calidad 80, YCbCr) para **solo RGB
  visual de 3 bandas uint8 sin nodata**. El builder operativo conserva
  `cog_v1` con DEFLATE. No cambiar la producción sin evaluar fuentes reales,
  transparencia y reducción de bytes medidos.
- Los mosaicos privados hoy salen en PNG RGBA, que puede ser costoso para RGB
  fotográfico. Evaluar WebP/AVIF únicamente como nuevo perfil HTTP versionado
  y con pruebas de navegador/compatibilidad, no como cambio silencioso.
- Los seis mapas temáticos aún requieren rásteres científicos derivados con
  reflectancia calibrada y NODATA, renderer/estilo, QA, revisión DALGORO
  y `PUBLISHED` exacto por Campaign. No construir seis mapas desde medianas.

## Fuentes públicas oficiales

- Google Maps JS, tipos satelitales: https://developers.google.com/maps/documentation/javascript/maptypes
- Coordenadas/mosaicos: https://developers.google.com/maps/documentation/javascript/coordinates
- Condiciones/atribución Google Maps: https://developers.google.com/maps/documentation/javascript/policies
- EPSG:32717: https://epsg.io/32717

**Límites:** sin despliegues, sin cambio de fórmulas, ML, PostGIS o
publicación; sin extracción de Google Earth y sin crear estilos no verificados.
