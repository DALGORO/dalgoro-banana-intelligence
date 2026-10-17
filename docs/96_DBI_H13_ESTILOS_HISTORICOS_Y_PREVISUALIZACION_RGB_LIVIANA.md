# H13 · Recuperación de estilos QGIS y previsualización RGB liviana

## Alcance y fuentes

Auditoría de GitHub `main@42c900bcd7d9e4201a20fec19a5965b6a43f00e7`
más decisiones recuperadas de trabajo previo en QGIS durante septiembre
de 2026. **Los QML multiespectrales citados no están versionados en
este repositorio**: sus nombres y principios proceden del historial de
trabajo previo, no de haber inspeccionado sus bytes. Nunca inventar
valores de clasificación ni aplicarlos como hechos a una Campaign.

### RGB — estilo de presentación

- Estilo previo: `RGB_2_98.qml`, composición roja/verde/azul natural
  con contraste de visualización por percentiles **P2–P98** por banda.
- Sin ajustes arbitrarios de brillo o saturación.
- El RGB actual `rgb_visual` en DBI es `uint8` con
  `rgb-natural-v1`: **no implementa todavía ese QML/estiramiento
  como algoritmo del visor web**. Tampoco debe aplicarse un doble stretch
  sin saber si la ortofoto ya fue normalizada.
- Nueva alternativa COG voluntaria: `cog_rgb_preview_jpeg_v1`.
  Se solicita **explícitamente** por el operador/worker al generar
  un COG nuevo, nunca se aplica por defecto ni reemplaza el COG existente.
  Sólo admite RGB uint8 de tres bandas sin NoData: compresión JPEG
  calidad 80, fotometría YCbCr, `BLOCKSIZE=512`,
  overviews y metadatos geoespaciales preservados.
  No aplica el QML ni cambia las fórmulas.
- El archivo GeoTIFF/COG original permanece intacto.
  El derivado visual JPEG **no es un dato científico**, es una
  representación con pérdida exclusivamente para visualización.
  Se conserva nombre de perfil, SHA de la fuente y SHA del derivado.
- El mapa cliente **todavía usa** el COG `cog_v1` publicado y
  teselas privadas PNG de 256 × 256. Este PR habilita una
  alternativa opt-in de *preparación*, **no cambia el mapa del productor
  a JPEG/WebP por sí solo**.
- Ejemplo interno, entorno raster Density (sin tocar fuente):
  `python flight_test_cog.py ORTOFOTO_RGB_3B.tif PREVIEW.cog.tif
  --product-kind rgb_visual --profile-version cog_rgb_preview_jpeg_v1`.
  No usar archivos privados ni COG de una Campaign no publicada
  como prueba client-visible.
- Antes del rollout del portal: comprobar calidad visual,
  tamaños/ratios reales, alpha/NoData, autoridad de publicación del
  `product_id` de tiles directo y presencia de estilos
  P2–P98 en origen. Los COG RGB con cuarta banda o nodata
  requieren conservar DEFLATE sin pérdida.

### Estilos multiespectrales recuperados

| Variable | Referencia histórica | Estilo confirmado hasta donde existe registro |
|---|---|---|
| NDVI | `NDVI_DIAGNOSTICO_2_98.qml` | pseudocolor monobanda, P2–P98, RdYlGn, siete clases, continuo: rojo bajo → amarillo medio → verde alto |
| NDRE | `NDRE_DIAGNOSTICO_2_98.qml` | mismo sistema visual con escala propia de NDRE |
| GNDVI | `GNDVI_DIAGNOSTICO_2_98.qml` | mismo sistema visual con escala propia de GNDVI |
| CI Red Edge | derivado `CI_RE=(NIR/RE)-1` | escala por percentiles propia; **no** limitar a [−1,+1] |
| EVI2 | fórmula científicamente implementada | QML y puntos cromáticos originales **no recuperados** |
| CI Green | fórmula científicamente implementada | QML y puntos cromáticos originales **no recuperados** |

El intervalo `0.0281963–0.4056004` corresponde a un ejemplo
histórico particular de clasificación 2–98, **no** es un rango
universal para NDRE ni para otras fincas.

**Advertencia:** la rampa RdYlGn indica valores relativos dentro
de la escena/escala y NO significa por sí sola cultivo enfermo/sano.
No inferir tratamientos, severidad de Sigatoka ni mejorar/empeorar
entre campañas por usar los mismos colores. En un comparador temporal
se requieren calibración radiométrica, grilla común, máscara y límites
fijos científicamente validados; los percentiles por escena no hacen
comparables sus colores.

### Capas de población en repositorio

Los QML **sí** presentes en `services/banana-density/resources/qgis/styles`
son los de análisis poblacional: `desidad_exagono.qml`,
`densidad_kde_corregida_tiff.qml`, `plantas_patron_espacial.qml`,
candidatos, filas y oportunidades. Tienen clasificaciones, rangos,
opacidades y colores específicos; preservarlos como referencia para
la traducción cartográfica, sin confundir sus umbrales poblacionales
con escalas espectrales.

### Pruebas y aceptación

- Smoke real de Rasterio/GDAL crea COG deflate y preview JPEG
  desde la **misma** fuente RGB sintética y valida CRS, dimensiones,
  transform, overviews, hash de fuente, compresión y tamaño.
- Rechaza Float32 científico con el nuevo perfil y evita sobrescritura.
- Sin cambios a `rgb_visual` por defecto, a los seis cálculos,
  a datos originales, a máscaras COPA_UP, GIS o a permisos HTTP.
- No publicar en Render ni cambiar al portal sin comprobaciones y
  aprobación expresa. Ningún usuario tiene que recrear sus QML.
