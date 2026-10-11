# DBI-PORTAL-GIS-002 — Conversor aislado de GeoPackage y Shapefile a GeoJSON

## Finalidad
Adaptar **sin recalcular** salidas GIS existentes de DALGORO a GeoJSON WGS84 compatible con el primer cargador privado del visor por Campaign. El archivo original se mantiene **intacto**. El conversor no se importa desde FastAPI, no utiliza el almacén de otros clientes y no modifica el motor Density.

## Formatos
- `.gpkg`: GeoPackage individual hasta 50 MB, capas geométricas; si hay más de una capa el operador debe seleccionar el nombre exacto con `--layer`.
- `.zip`: un Shapefile completo con `.shp/.shx/.dbf/.prj` del mismo nombre, y sidecars opcionales reconocidos. Se rechazan rutas ZIP internas, symlinks, archivos extra, múltiples capas y expansiones desproporcionadas.
- Salida: `<nombre>-<sha_original_12>.geojson` y `<nombre>-<sha_original_12>.manifest.json` en la carpeta indicada.

## Restricciones
Máximo 2.500 entidades, 50.000 vértices y 2 MB de GeoJSON. Comprueba geometrías y CRS de origen real y reproyecta a WGS84 EPSG:4326. Filtra atributos privados de la **capa visual**; el original se mantiene en la ubicación del operador y no se comparte automáticamente con los clientes.

La fecha de captura queda `null`: nunca se infiere a partir de la creación del archivo. La Campaign real debe seleccionarse y verificarse antes de subir la capa al visor.

## Uso local en Windows, desde la raíz del repositorio
El Python utilizado debe contar con las dependencias de `services/banana-density/requirements.txt`. El motor Density ya define GeoPandas y Pyogrio, pero el operador debe instalar su entorno previamente.

### GeoPackage
```powershell
python services/banana-density/portal_gis_convert_cli.py "C:\GIS\densidad.gpkg" --output-dir "C:\GIS\preparados" --layer "nombre_de_capa"
```

### Shapefile ZIP
```powershell
python services/banana-density/portal_gis_convert_cli.py "C:\GIS\plantas.zip" --output-dir "C:\GIS\preparados"
```

Deberán aparecer dos rutas: `GeoJSON preparado` y `Ficha de procedencia`. **No** subir `.manifest.json` al visor: conservarlo como respaldo de procedencia. Desde la cuenta del gestor, abrir finca/lote/fecha correcta y subir el `.geojson` preparado, con el tipo de capa que corresponda.

## Seguridad y límites
Este es un **conversor local de transición**. No habilita aún la carga directa de `.gpkg` ni `.zip` por el navegador del productor. Para conseguir esa experiencia se requiere un puerto de ingestión privada y asíncrona, integrado con autorización DBI y un worker geoespacial aislado. No debe ejecutarse el conversor en el proceso FastAPI ni confiar en una transformación realizada por un navegador como autoridad científica.

## Validación
La CI geoespacial usa archivos GPKG y Shapefile creados durante la prueba para comprobar CRS, conversión de coordenadas, tipos, atributos privados, SHA-256, origen intacto y rechazo de ZIP traversal/CRS ausente. Esta prueba no sustituye un ensayo con tus archivos reales.
