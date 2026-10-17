# H13 — Preflight técnico de seis mapas multiespectrales (no publicación)

**Base:** `main@1ae65a7`. Control aislado del worker geoespacial para preparar, sin activar ni publicar, los seis mapas por campaña.

## Alcance efectivo

Se agrega `banana_analyzer.multispectral_map_preflight.inspect_six_index_maps`, una utilidad **solo local** de validación de seis pares existentes de archivos **GeoTIFF científicos Float32 COG + QGIS QML**, para:

- `ndvi`, `ndre`, `gndvi`, `evi2`, `ci_red_edge` y `ci_green`, exactamente una vez cada uno;
- lectura por Rasterio/GDAL: CRS válido (incluye EPSG:32717), affine/extent finitos, georreferenciación no identidad, grilla pixel-perfect idéntica entre los seis, Float32 monobanda, NoData explícito y finito, escala 1 / offset 0, bloques y overviews en grandes;
- exclusión de compresión con pérdida, de COG duplicado por SHA-256, de productos sin píxeles válidos y de valores no finitos en píxeles considerados válidos;
- lectura limitada y protegida de QML original: XML QGIS, renderer `singlebandpseudocolor` de banda 1, rampa con 2–256 paradas finitas y ordenadas; DTD/ENTITY rechazado;
- evidencia inmutable de **SHA-256 del archivo raster y del QML**, datos de grilla, NoData, píxeles válidos/enmascarados, y `formula_version` obtenida de las definiciones científicas actuales.

**Importante:** el análisis comprueba las propiedades de los archivos, pero **no demuestra** que los valores de los seis GeoTIFF procedan realmente de las bandas reflectantes declaradas, ni certifica la calibración radiométrica, puntos GCP/RTK o la coincidencia con Google Maps. Tampoco coteja el `campaign_id` o `stack_fingerprint` declarados con PostGIS. La prevalidación es insuficiente para publicar.

El expediente entrega siempre:

```json
{
  "disposition": "technical_preflight_only_not_published",
  "campaign_link_verified": false,
  "source_calibration_verified": false,
  "institutional_publication_authorized": false
}
```

No hay mecanismo para transformar estos campos en `true` mediante parámetros del CLI.

## Uso local (cuando existan los archivos reales)

**Archivo:** `services/banana-density/multi_map_preflight.py`.

Preparar en una carpeta local un `six_maps.json` con identidad declarada de Campaign, huella declarada del stack calibrado y seis rutas `raster` y `qml`. Las rutas relativas se resuelven desde la carpeta del JSON:

```json
{
  "campaign_id": "63000000-0000-4000-8000-000000000063",
  "stack_fingerprint": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "files": {
    "ndvi": {"raster": "NDVI.cog.tif", "qml": "NDVI.qml"},
    "ndre": {"raster": "NDRE.cog.tif", "qml": "NDRE.qml"},
    "gndvi": {"raster": "GNDVI.cog.tif", "qml": "GNDVI.qml"},
    "evi2": {"raster": "EVI2.cog.tif", "qml": "EVI2.qml"},
    "ci_red_edge": {"raster": "CI_RE.cog.tif", "qml": "CI_RE.qml"},
    "ci_green": {"raster": "CI_GREEN.cog.tif", "qml": "CI_GREEN.qml"}
  }
}
```

Los identificadores y nombres del ejemplo son **sintéticos**, no prueban que esos archivos existan. Nunca reemplazarlos por datos inventados para simular un vuelo.

Ejecutar desde la raíz del repositorio con Python y Rasterio instalados:

```bash
python services/banana-density/multi_map_preflight.py --input /ruta/six_maps.json --output /ruta/expediente_preflight.json
```

El archivo de salida se crea solo si no existe; nunca se sobrescribe. El programa no modifica los GeoTIFF ni QML originales, ni accede a red ni base de datos.

## Límites de publicación real pendientes

1. Ingesta verificada de cada GeoTIFF científico desde cuatro bandas calibradas, con fórmulas, fuentes originales, versión, NoData y procedencia de vuelo;
2. incorporación y revisión de **los QML reales**. Los nombres QGIS históricos citados en otros documentos no son estilos verificados. El CI usa QML **sintéticos exclusivamente para pruebas**;
3. metadatos e identidad almacenada de **un índice + COG + estilo + Campaign**, control de integridad y firma institucional DALGORO;
4. rutas de tiles temáticos que requieran publicación individual y autorización por tenant/organización/finca/lote, más validación de navegador, móvil y rendimiento;
5. validación planimétrica con puntos de control reales antes de prometer coincidencia métrica con la cartografía.

No altera API pública, esquema DB, permisos, generación científica, COG antiguos ni controles de PUBLISHED existentes. Sin despliegue en Render ni migraciones de producción.

## CI

`dbi-multi-integration.yml` compila el preflight y CLI, y ejecuta un test aislado que fabrica **seis GeoTIFF COG y seis QML temporales sintéticos**, verifica el éxito técnico, huellas intactas, salida CLI y denegación de faltantes, UUID/stack inválidos, COG duplicado, grilla desplazada, NoData ausente, mapa completamente enmascarado y QML/DTD no válido.
