# H14 / 2G — Conciliación privada de QML contra manifiesto (solo lectura)

## Estado y dependencias
Incremento apilado **sobre PR #259 (manifiesto científico privado de 13 archivos)**. La lectura de los originales QML usa las claves **exactamente compatibles con PR #257 (recepción privada de seis QML)**. **Ambos deben ser revisados y fusionados coordinadamente antes de pensar en habilitar el sistema**. Esta entrega no realiza merge, despliegue ni configura S3.

## Qué hace y qué NO certifica
Nueva ruta de verificación, reservada a operadores con MANAGE:
`GET /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/scientific-intake/private-qml-reconciliation`

- Revalida scope y permiso MANAGE antes de leer S3, vuelve a comprobar Campaign MULTISPECTRAL no aprobada ni publicada (mismos controles de H14/2F).
- Lee el **manifiesto inmutable** y verifica su huella SHA-256. Si falta, 404; si el registro está corrupto/inconsistente, 503.
- Para cada índice (NDVI, NDRE, GNDVI, EVI2, CI-red-edge y CI-green), deriva la dirección privada del **QML original según el UUIDv5 H14/2E**, sin aceptar claves del cliente.
- `stat` + `open_read` privado del objeto QML: lee sus bytes (máximo 2 MiB), calcula SHA-256 nuevamente y coteja contenido con la huella registrada en S3. Si el proveedor o los bytes presentan corrupción/inconsistencia, **503**, no un falso positivo.
- Compara **tamaño real verificado** y **SHA-256 real verificado** con los correspondientes valores **declarados en el manifiesto**.
- Devuelve por índice `missing` (aún no está cargado), `size_mismatch`, `sha256_mismatch` o `matched`, con conteos separados. `all_six_qml_match_manifest` solo es verdadero si los seis QML originales recibidos corresponden exactamente al manifiesto.

**Esta bandera NO demuestra procedencia auténtica ni validez semántica XML/QGIS, ni prueba de radiometría, ni seis COG ni ortofoto RGB.** Aun con seis QML `matched`, `all_thirteen_files_received=false`, `scientific_validated=false`, `institutional_approved=false` y `published=false`.

## Seguridad
- Opt-in independiente `DBI_SCIENTIFIC_QML_RECONCILIATION_ENABLED=1`; además `DBI_ENVIRONMENT` debe ser `test`, `development` o `local`. `production`, `staging` y ambiente indefinido permanecen **cerrados incluso con el flag**.
- La ruta solo admite proveedor `DBIS3ObjectStore` privado y durable. Tests usan un doble en memoria únicamente mediante inyección controlada.
- Solo GET. Ninguna ruta PUT nueva, escritura SQL, cambios al manifiesto, modificación de Campaign, S3 `put`, grant, enlace público, visualización READ o interfaz cliente.
- Cada respuesta lleva `Cache-Control: no-store`. Los metadatos de rutas relativas y hashes solo pueden ser vistos por MANAGE verificado; ningún usuario READ tiene acceso.

## Límites intencionales
1. La conciliación es **calculada al consultar**, no constituye certificado firmado ni bitácora institucional duradera; las mutaciones del objeto fuera del flujo permitido fallarán al revalidarse.
2. No exige que la ruta de carga QML haya sido iniciada desde el manifiesto; solo verifica posteriormente identidad Campaign + índice y equivalencia de bytes declarados. El respaldo de origen y expediente formal requiere auditoría adicional.
3. La derivación de UUID de QML se repite exactamente desde H14/2E al no estar integrado todavía PR #257. Tras fusionar ambos, conviene centralizar la función de identidad en módulo compartido y añadir un test cruzado explícito.
4. El visor del cliente conserva sus bloqueos actuales; los productos raster y estilos se publicarán solamente tras las futuras verificaciones de los 13 originales y aprobación institucional.

## Pruebas offline
`.github/scripts/ci_dbi_scientific_qml_reconciliation.py` cubre: ausencia de manifiesto; seis faltantes; uno correcto, uno con hash divergente y uno con tamaño divergente; seis válidos; lectura adulterada con metadatos originales (503); metadatos MIME falsos (503); prohibición de READ y tenant cruzado, Campaign densidad/aprobada/publicada, falta de S3, ruta cerrada en producción/staging y auditoría de ausencia de escrituras/grants. El pipeline principal ejecuta este script en el job Backend.
