# DBI-RASTER-001 — Métricas y modelo de presupuesto

## Propósito

Definir magnitudes observables y fórmulas reproducibles para operar COG/BigTIFF privados sin introducir precios, credenciales ni detalles de un proveedor específico.

## Métricas agregadas

La capa `DBIMeteredObjectStore` registra únicamente contadores globales de baja cardinalidad. Para acceso parcial Raster interesan especialmente:

- `range_attempts`: solicitudes de rango intentadas;
- `range_reads`: rangos entregados correctamente;
- `range_failures`: rangos que fallaron en la frontera de Storage;
- `bytes_ranged`: bytes efectivamente devueltos por rangos;
- `not_found_errors`, `integrity_errors`, `conflict_errors`, `denied_errors`: fallos normalizados.

No se añaden etiquetas por tenant, finca, lote, producto, object key, SHA, URL o credencial.

Los productos persistidos se miden desde `dbi_raster_products` por estado y `size_bytes`; los tiempos de generación se deben medir en la frontera de ejecución geoespacial/Worker, no dentro de FastAPI. La instrumentación de despliegue puede agregar un histograma de duración de generación sin identificadores de producto.

## Almacenamiento persistente

Para una fuente maestra y un único COG oficial:

`storage_persistent_bytes = master_bytes + cog_bytes`

Si existen varias versiones explícitas de perfil o source SHA, cada COG cuenta como un producto persistente independiente. Nunca se presupone sobrescritura silenciosa.

## Overviews

Para niveles de overview `L = {l1, l2, ...}` la fracción teórica de píxeles adicionales respecto de la resolución completa es:

`overview_raw_pixel_fraction = sum(1 / li^2)`

Ejemplo para niveles 2, 4 y 8:

`1/4 + 1/16 + 1/64 = 0.328125`

El equivalente sin comprimir es:

`overview_uncompressed_equivalent_bytes = ceil(full_resolution_uncompressed_bytes * overview_raw_pixel_fraction)`

Esta cifra **no es el tamaño real del COG**. La compresión, dtype, número de bandas, nodata y estructura interna afectan el tamaño físico; el valor real se obtiene del `size_bytes` verificado en Storage.

## Egreso por lectura parcial

Para HTTP Range:

`range_egress_bytes = sum(end_exclusive - start)`

En operación, `bytes_ranged` es la evidencia directa de bytes entregados por la capa provider-neutral. El costo monetario futuro se calcula como:

`range_egress_cost = range_egress_bytes * provider_egress_rate`

La tarifa del proveedor no pertenece al código ni a este ticket.

## Generación

El presupuesto de generación debe considerar por Worker:

`generation_capacity = concurrent_workers * generation_duration`

La memoria no debe estimarse a partir del tamaño total de la ortofoto. La frontera Worker materializa por streaming; el presupuesto operativo debe separar:

- buffer de streaming;
- working set medido de Rasterio/GDAL;
- espacio temporal para source materializado + COG parcial + COG final;
- concurrencia máxima autorizada.

Como aproximación de disco temporal por trabajo:

`temporary_disk_bytes >= master_bytes + partial_cog_bytes + final_cog_bytes + safety_margin`

`partial_cog_bytes` debe medirse en pruebas reales; no se asume igual al COG final.

## Primera prueba con dron

En cada Flight Test se deben conservar como evidencia mínima:

1. tamaño y SHA-256 de la ortofoto maestra;
2. tamaño y SHA-256 del COG;
3. perfil y versión del generador;
4. niveles de overview;
5. tiempo de generación observado por la frontera Worker/ejecutor;
6. bytes de rango utilizados para validar lectura parcial;
7. resultado de integridad y estado final `ready`.

Esto permite comparar futuras fincas y proveedores sin alterar la autoridad científica de los archivos.
