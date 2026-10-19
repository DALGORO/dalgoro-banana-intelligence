# H14 / 2F — Manifiesto privado e inmutable de 13 archivos científicos

## Alcance y límites de la evidencia

Este incremento crea un **expediente de metadatos declarado por un operador MANAGE** vinculado a una Campaign real de tipo MULTISPECTRAL. No transmite ni recibe los 13 archivos originales. El manifiesto recibe y conserva nombres/rutas **relativas** de dos carpetas, tamaños declarados, 13 SHA-256 **declarados** y el identificador del operador autenticado.

**Distinción indispensable:** el servidor verifica criptográficamente los bytes del JSON del manifiesto antes de almacenarlo; **no** verifica aquí los SHA-256 de TIFF/COG/QML, sus tamaños efectivos, contenido, autenticidad, ciencia o procedencia externa. `manifest_received_privately=true` nunca significa `file_bytes_received=true`.

Se reutiliza el contrato estricto `ScientificDraftScopeRequest` (exactamente una ortofoto RGB, seis `scientific_cog` y seis `qml_style`; dos raíces locales distintas, índices únicos, rutas relativas seguras, ninguna bandera positiva de recepción/aprobación). El nuevo `PrivateScientificManifestSubmission` añade exactamente **13 SHA-256 declarados**, uno por rol/índice, todos canónicos en hexadecimal minúsculas. El backend rechaza duplicados, roles faltantes y datos extra.

## Seguridad de almacenamiento y Campaign

- **Doble control cerrado:** `DBI_SCIENTIFIC_MANIFEST_ENABLED=1` y `DBI_ENVIRONMENT` en `test`, `development` o `local` son ambos obligatorios. Ausentes los requisitos, el router no se registra y llamadas directas reciben 404. Incluso con el flag en `1`, `staging` y `production` permanecen bloqueados. **No activar en Render** en esta etapa.
- Endpoints internos bajo `/api/v1/dbi`:
  - `PUT /organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/scientific-intake/private-manifest`
  - `GET /organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/scientific-intake/private-manifest`
- Cada PUT y GET exige permiso **MANAGE** sobre tenant/organización/finca/lote; relee la Campaign exacta, exige `MULTISPECTRAL` y estado `DRAFT`, `PROCESSING`, `ANALYZED` o `TECHNICAL_REVIEW`, sin `approved_at` ni `published_at`. Deniega con 404 a READ, scope cruzado, Campaign aprobada/publicada o no existente.
- El almacenador productivo debe ser `DBIS3ObjectStore` **privado y durable**, configurado por el servidor; el endpoint niega proveedores en memoria/disco con 503. CI inyecta un doble de memoria aislado mediante patch explícito.
- Se genera una única clave DBI `ANALYSIS_INPUT` derivada del scope y la Campaign con UUIDv5; no toma nombres, URLs, buckets ni claves S3 del navegador. El documento se serializa como JSON UTF-8 determinista, con orden canónico de piezas y huellas, y se verifica SHA-256 completo antes de guardar.
- **Inmutabilidad:** la misma Campaign admite una sola versión del manifiesto. Reintento con exactamente la misma declaración y operador = idempotente (200); contenido divergente o operador distinto = 409, sin sobrescritura. Un primer registro devuelve 201. Para corregir manifiestos ya recibidos hará falta un futuro mecanismo institucional de revisiones explícitas, **no** mutación silenciosa.
- El `GET` devuelve a MANAGE el mismo manifiesto, operador y fecha de creación proveniente del almacenador, con validación de integridad del objeto. No entrega URLs ni permisos de descarga S3.
- Respuestas privadas llevan `Cache-Control: no-store`. No se crea tabla, migración, grant, tile, raster público, escritura SQL ni cambio de estado Campaign.

## Cuotas contractuales declaradas

| Rol | Cantidad | Cuota por archivo |
| --- | ---: | ---: |
| Ortofoto RGB TIFF | 1 | 10 GiB |
| TIFF COG de índice | 6 | 10 GiB |
| Estilo QML | 6 | 2 MiB |
| **Total declarado** | **13** | **60 GiB conjunto** |

JSON almacenado: máximo **32 KiB**. Las cuotas son una salvaguarda inicial del **manifiesto declarado**, no una autorización de almacenamiento raster ni de multipart; podrán ajustarse tras dimensionar conjuntos reales y políticas DALGORO.

## Auditoría mínima y conciliación pendiente

El manifiesto duradero conserva `submitted_by` a partir de la identidad autenticada y `created_at` del proveedor. Es una **traza técnica de primera inscripción**, no reemplaza una bitácora institucional transaccional con historial de revisiones, eventos, firmas, ni controles de retención.

Esta etapa es **independiente** del PR #257, que propone recepción real privada de los seis QML por índice. Cuando ambos estén revisados/aceptados, se deberá diseñar explícitamente la **conciliación de cada recibo QML con ruta, tamaño y SHA declarado** de este manifiesto. Nunca asumir equivalencia solo por Campaign e índice. RGB y COG requieren carga multipart durable y verificación SHA real de servidor, más reglas para poder correlacionar 13 recibos con una versión de manifiesto.

La UI administrativa de dos carpetas aún no presenta botón de persistir manifiesto: **no habilitar flujo productivo** hasta revisión y UAT. El visor cliente no se modifica ni expone metadatos privados.

## Pruebas

`.github/scripts/ci_dbi_scientific_manifest_private.py` verifica offline contrato de roles/rutas/hashes, las cuotas, control MANAGE y scope/campaign, estado aprobado/publicado, proveedor productivo obligatorio, exclusión de READ, JSON íntegro y determinista, actor y fecha, reintentos idempotentes, alteración 409, GET privado, flag apagado y ausencia de mutaciones SQL.

Cambios acotados al nuevo endpoint, enrutamiento protegido, script CI, línea del workflow y este documento. **No fusionar ni desplegar automáticamente**; revisar CI y posible interacción con los PR #257 y #258 antes de aceptar a `main`.
