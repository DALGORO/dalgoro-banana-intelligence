# Importación GIS DALGORO — SHP y GeoPackage (primer puente hacia el portal)

## Qué permite este incremento

La herramienta `banana_analyzer.portal_vector_convert` prepara **archivos existentes**, ya analizados en QGIS, para publicar sus resultados en el visor privado del cliente. No modifica la fuente, no recalcula densidades, no ejecuta segmentación y **no publica por sí misma** en ninguna cuenta.

| Origen | Requisitos | Salida |
|---|---|---|
| GeoPackage `.gpkg` | Contener 1 capa vectorial; con varias, seleccionar por nombre `--layer` | GeoJSON WGS84 |
| Shapefile `.zip` | ZIP con una única capa y `.shp`, `.shx`, `.dbf`, `.prj` | GeoJSON WGS84 |

Se producen **dos archivos nuevos**: `nombre.geojson` (para subir al portal) y `nombre.manifest.json` (evidencia de procedencia y hashes SHA-256 del archivo original y del resultado). El original se mantiene intacto.

## Uso técnico interno (equipo DALGORO)

El conversor funciona en el entorno geoespacial existente `services/banana-density`, donde ya están disponibles GeoPandas/Pyogrio. No se instala GDAL en FastAPI.

Desde `services/banana-density` con ese entorno Python:

```bash
PYTHONPATH=src python -m banana_analyzer.portal_vector_convert --input /ruta/levantamiento.gpkg --output /ruta/portal_resultado.geojson
```

Para un GeoPackage con varias capas:

```bash
PYTHONPATH=src python -m banana_analyzer.portal_vector_convert --input /ruta/levantamiento.gpkg --layer "densidad_hexagonos" --output /ruta/resultado.geojson
```

Para Shapefile:

```bash
PYTHONPATH=src python -m banana_analyzer.portal_vector_convert --input /ruta/capa.zip --output /ruta/capa.geojson
```

Luego, un usuario DALGORO con autorización de publicación accede a **Mis fincas → Lote → Fecha → Añadir resultado cartográfico**, elige el `.geojson` generado, selecciona tipo de resultado y lo publica. El cliente del lote visualiza la capa con su usuario.

## Reglas automáticas

- Formato real/magic bytes, ZIP sin rutas `../` ni enlaces simbólicos, archivos cifrados, archivos extraños o expansión desproporcionada.
- Hasta 128 MiB por archivo de entrada (procesamiento fuera de FastAPI); máximo 2500 elementos / 50.000 vértices / 2 MiB de GeoJSON resultante.
- CRS auténtico obligatorio, transformación controlada a WGS84 EPSG:4326.
- Geometrías válidas Point/MultiPoint/LineString/MultiLineString/Polygon/MultiPolygon; sin reparar ni inventar geometrías.
- Atributos escalares acotados y campos de rutas/credenciales eliminados.
- No sobreescribe salidas existentes; almacena hash del original separado del derivado.

## Lo que aún falta para carga directa del cliente

Esta versión **no permite arrastrar un GPKG o ZIP SHP al navegador para convertirlo automáticamente**. El próximo bloque de #160 debe conectar carga privada temporal → worker aislado de conversión → validación profesional → asociación a Campaign → publicación selectiva. La pantalla del cliente únicamente consume capas ya autorizadas.

Ni el CLI ni el manifiesto justifican afirmar UAT con datos reales. Se debe validar primero con archivos históricos reales de DALGORO y realizar las pruebas de #155 de RGB/COG/MapLibre.
