# DBI-PORTAL-GIS-007D · Conversión aislada de capa seleccionada (microhito C)

## Resultado
El worker GIS S3 `--once` ahora admite reclamar un GeoPackage con estado
`needs_selection` **solo cuando** `selected_layer` ha sido guardado previamente
por el gestor autorizado (microhito B / PR #193). Reutiliza exactamente
`services/banana-density/portal_gis_convert_cli.py --layer <nombre>`:
no hay un segundo conversor, ni se utiliza GDAL dentro de FastAPI.

El worker continúa apagado por defecto, limitado a un trabajo por ejecución
y no realiza publicación. El flujo de revisión/publicación existente sigue
separado y requiere `MANAGE`.

## Controles y transición
- El claim aplica filtro por tenant, `attempt_count < 3`, orden estable,
  `FOR UPDATE SKIP LOCKED` y claim de `received`, `processing` vencido o
  `needs_selection` con selección no nula; los multicapa aún sin elegir
  **no son reclamados**.
- La elección y catálogo geométrico persistidos se copian al claim inmutable.
  Se valida que se trate de GPKG y que la capa aparezca entre las opciones
  verificadas (2–20); nombres vacíos, excesivos o con caracteres de control
  son rechazados. Un token de proceso `processing_ref` evita aplicar
  derivados de procesos reemplazados.
- Se descarga el original desde el objeto S3 privado y se vuelven a
  verificar manifiesto de almacenamiento, tamaño y SHA-256 **antes** del
  subprocess GIS. El subprocess conserva CPU, memoria, tamaño máximo,
  timeout, entorno mínimo sin claves y red PROJ deshabilitada.
- El worker reenumera las capas geométricas y pasa `--layer` con el nombre
  **exacto**; nunca elige por índice ni ejecuta una cadena como shell.
  Pyogrio/GDAL valida que la capa siga existiendo; un nombre no reconocido
  no genera un derivado.
- El manifest `dbi-portal-gis-conversion.v1` debe coincidir con
  `selected_layer` además de fuente, output, hash, CRS y recuento. La
  vista previa privada se crea de forma idempotente solo si todo es válido.
- La finalización cercada comprueba que la selección y catálogo almacenados
  no cambiaron durante el procesamiento. Solo entonces se pasa a
  `prepared`. Un fallo marca `failed` sin publicar; una victoria de otro
  proceso retorna `lease_lost` sin reescribir la fila.

Los GPKG de una sola capa y SHP ZIP sin selección continúan con el flujo
anterior de descubrimiento/conversión. Un GPKG multicapa sin selección
permanece en `needs_selection`.

## Pruebas
`.github/scripts/ci_dbi_gis_preparation.py`: transición desde selección,
replay sin duplicados, rechazo de manifiesto de otra capa, tenant, SHA
original y fencing concurrente. `.github/scripts/ci_dbi_gis_s3_worker.py`:
paso exacto de `--layer`, subprocess aislado, secretos excluidos, bloqueo
de nombres inventados, entrada sin selección y límites de descubrimiento.

El cambio no crea servicios en Render ni aplica migraciones (usa la DBI 26
ya declarada). No se han confirmado credenciales, ni ejecución programada
ni funcionamiento con GeoPackages reales de los clientes.

## Microhito siguiente
**D**: verificar el recorrido de la capa ya preparada por los controles
existentes de preview, revisión MANAGE y publicación explícita, con pruebas
end-to-end específicas que protejan Campaign y tenant. No adelantar ese
trabajo en este microhito.
