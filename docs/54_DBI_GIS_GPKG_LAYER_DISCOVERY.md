# DBI-PORTAL-GIS-007A · Descubrimiento seguro de capas GeoPackage (primer tramo)

El conversor geoespacial de `services/banana-density` ahora puede enumerar **solo nombres de capas geométricas reales** de un GeoPackage QGIS, sin elegir ninguna si hay varias. Esta operación utiliza Pyogrio/GDAL únicamente en el proceso GIS aislado, **nunca en FastAPI**.

En el entorno del worker geoespacial:

```bash
python services/banana-density/portal_gis_convert_cli.py /ruta/privada/levantamiento.gpkg --list-layers
```

Salida JSON, por ejemplo `{"layers":["plantas","limites"]}`. El parser exige archivo local GeoPackage menor o igual a 50 MiB, firma SQLite, nombres sin controles y no más de veinte capas geométricas. No lista tablas sin geometría ni divulga rutas, SQL, credenciales o el contenido de las entidades.

La conversión continúa requiriendo **selección exacta** cuando existen varias capas:

```bash
python services/banana-density/portal_gis_convert_cli.py /ruta/privada/levantamiento.gpkg --layer plantas --output-dir /ruta/efimera/derivados
```

Una capa inexistente o una selección omitida en archivo multicapa se rechaza. Los Shapefiles y los GPKG de una sola capa siguen con el comportamiento previo. La selección y el derivado mantienen todas las validaciones de CRS, geometrías, huellas y GeoJSON vigentes.

**Alcance aún pendiente:** esta revisión no agrega el selector al portal ni cambia el estado de las importaciones recibidas. Es el contrato probado que necesitará el siguiente tramo: reclamar el original desde S3, descubrir opciones en subprocess aislado, persistirlas en la importación scoped, permitir elección MANAGE y reintentar de modo idempotente. No introducir metadatos no verificados desde el navegador ni desactivar controles de publicación.

Pruebas de CI usan un GPKG sintético con dos capas, bloqueo de autoelección, selección exacta, rechazo de nombres inventados y salida JSON del CLI. No es una validación E2E con archivos reales ni un despliegue.
