# DBI-PORTAL-GIS-007B · Descubrimiento multicapa persistido en importaciones privadas

## Alcance de este microhito

El worker GIS S3 **one-shot** (apagado por defecto) integra `--list-layers`
del conversor existente. Solo después de reclamar por tenant, descargar
desde el objeto S3 privado y verificar metadatos, tamaño y SHA-256,
ejecuta el descubrimiento en un subprocess GIS Linux acotado.

- GeoPackage con **una** capa geométrica: se convierte y se prepara para
  revisión con el flujo anterior.
- GeoPackage con **dos a veinte** capas geométricas: guarda los nombres
  verificados en `dbi_portal_gis_imports.available_layers` (JSONB)
  y transiciona a `needs_selection`. **No convierte, no prepara vista
  previa y no publica** ninguna capa.
- Shapefile ZIP: conserva su conversión anterior.
- Archivo inválido, nombres duplicados, caracteres de control, respuestas
  excesivas o error GDAL: denegación, sin elección arbitraria.

Los nombres provienen exclusivamente del worker aislado; no se reciben
como metadatos confiables desde el navegador. El subprocess no recibe
credenciales DBI/S3 y utiliza los límites de tiempo, CPU, memoria y salida
ya fijados. El JSON de descubrimiento se acota a 4096 bytes y se elimina
del directorio temporal tras la comprobación.

La columna y el estado requieren aplicar **`dbi_0025_gpkg_layer_options`**
en el ambiente autorizado, mediante el procedimiento DBI existente.
No aplicar manualmente migraciones productivas ni activar el worker por
el mero merge.

## Acceso y recuperación

El endpoint de recibos existente (solo `MANAGE`, con tenant,
organización, finca y lote verificados) retorna `available_layers`.
En el navegador, `needs_selection` solo presenta el estado
**«Capas detectadas · pendiente de elección»**, sin selector todavía.

El claim `SKIP LOCKED` solo considera `received` y `processing`
vencido; `needs_selection` no se vuelve a procesar ni consume reintentos
por consultas repetidas. El fencing por `processing_ref` impide guardar
resultados de un intento reemplazado. Las vistas previas siguen siendo
privadas y requieren `prepared` para poder publicarse con `MANAGE`.

## Próxima intervención

Añadir un selector `MANAGE` del nombre de capa detectado y guardar la
elección de forma transaccional y scoped, **sin convertir todavía**.
Después, un microhito separado habilitará la conversión únicamente de
esa capa bajo el mismo worker y las validaciones actuales.

## Pruebas y límites

Las CI cubren descubrimiento S3 aislado, integridad de original,
cadenas de nombres inválidas, persistencia de las opciones,
idempotencia, aislamiento de tenant y ausencia de preview antes de
elegir. Se mantiene el control de aprobación/publicación anterior.

El cambio **no** crea bucket, scheduler, servicio Render o credenciales.
Tampoco significa UAT con GeoPackages reales de clientes.
