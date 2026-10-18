# H14 / Etapa 2E — Recepción privada INICIAL de QML científicos (sin publicar)

## Alcance exacto
Esta etapa habilita **solo mediante opt-in de servidor** la primera transferencia privada real de los **seis archivos QML originales** (uno por índice: NDVI, NDRE, GNDVI, EVI2, CI-red-edge y CI-green). Los rásteres COG y la ortofoto RGB se mantienen sin transferencia por este contrato: necesitan recepción multipart durable, cuotas y trazabilidad de origen/campaña.

Se preservan los **bytes** de cada QML sin conversión, normalización XML ni renderizado. Un recibo corresponde exclusivamente a **un archivo**; no prueba ni publica el conjunto de 13 originales.

## Activación deliberadamente cerrada
Variable de backend **`DBI_SCIENTIFIC_QML_INTAKE_ENABLED=1`** y **`DBI_ENVIRONMENT` igual a `test`, `development` o `local`** (ambas condiciones obligatorias). El valor por defecto mantiene las dos rutas fuera del router; en `staging` y `production` se rechazan incluso con el flag activo, y las funciones también devuelven 404 si son invocadas directamente. **No activar en Render** hasta revisión técnica/operativa institucional, almacenamiento S3 privado verificado, cuotas y prueba UAT. Esta entrega **no cambia** variables de producción ni configura buckets.

Los dos endpoints se registran dentro de `/api/v1/dbi`:

- `PUT /organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/scientific-intake/private-qml/{index}`
- `GET /organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/scientific-intake/private-qml/{index}` (solo recibo de metadatos, **nunca GET de bytes**).

`PUT` recibe `Content-Type: application/octet-stream`, `X-DBI-Expected-Size` (entero en bytes) y `X-DBI-Expected-SHA256` (64 caracteres hexadecimales minúsculos). El cuerpo HTTP es **el archivo original crudo**, no Base64 ni multipart/form-data. El servidor lee por bloques, impone **2 MiB máximos por QML**, compara longitud exacta y SHA-256 calculado a partir de los bytes recibidos, y solo entonces solicita `put()` al adaptador privado S3 previamente configurado por el servidor.

No utilizar esta ruta para archivos >2 MiB ni para un COG/RGB. Los QML sin prueba sintáctica/semántica también permanecen sin validar científicamente: esta es una recepción **privada de transporte**, no un estado durable `QUARANTINED` del objeto. El objeto del puerto puede quedar `ACTIVE` en el namespace privado y **no debe** confundirse con publicación.

## Seguridad y persistencia
1. Exige identidad/permiso **MANAGE** sobre tenant/organización/finca/lote y vuelve a leer la Campaign en cada PUT/GET. Solo Campaign **MULTISPECTRAL** en `DRAFT`, `PROCESSING`, `ANALYZED` o `TECHNICAL_REVIEW`, sin aprobación/publicación; READ y ámbitos ajenos obtienen 404 **antes de leer el cuerpo**.
2. La dirección privada se deriva exclusivamente del ámbito autorizado, Campaign e índice; usa `ANALYSIS_INPUT`. No acepta claves S3, rutas de máquina, URLs ni nombres de archivo del cliente. El MIME persistido es `application/octet-stream`, nunca XML ejecutable.
3. Cada Campaign admite **máximo un QML por índice**: misma huella y mismos bytes = reintento idempotente; contenido distinto = 409 **sin sobrescritura**. Se reutiliza la semántica inmutable del puerto DBI (`DBIInMemoryObjectStore` y `DBIS3ObjectStore`).
4. Si falta un adaptador **DBIS3ObjectStore** durable y privado, 503: se rechazan expresamente los adaptadores local o en memoria en la ruta productiva (sin fallback a disco local/efímero). No se crea ni se modifica tabla, Campaign, artefacto aprobado, tile, grant público ni exposición READ. Las respuestas de éxito llevan `Cache-Control: no-store`.
5. El recibo lleva `file_received_privately=true`, `bundle_received=false`, `scientific_validated=false`, `institutional_approved=false` y `published=false`. SHA-256 del **archivo recibido** no equivale a certificación de procedencia ni a aceptación de todo el lote.

## Límite explícito de esta entrega
No se implementa todavía la asociación durable del **nombre/ruta original** al QML, la auditoría persistente de operador ni un manifiesto transaccional de los 13 archivos. La clave estable por Campaign/índice permite recuperar recibo técnico, pero **no constituye un expediente científico completo ni habilita aprobación**. Antes de activar el opt-in se necesita revisar retención, auditoría, modelos de persistencia, conciliación, autenticidad de fuente y políticas institucionales.

La interfaz de dos carpetas del administrador permanece **sin botón de carga QML en esta etapa**: no lanzar una operación experimental desde el navegador antes de validar el contrato backend. El visor del cliente permanece exclusivamente para resultados aprobados/publicados.

## Pruebas automáticas
`.github/scripts/ci_dbi_scientific_qml_private.py` inyecta controladamente un doble `DBIInMemoryObjectStore` y bytes QML sintéticos, y además verifica que la ruta productiva rechace el doble en memoria, sin red, S3 o DB real. Prueba entrega exacta y original inalterado, seis índices aislados, GET privado, reintento idéntico, sobrescritura bloqueada, tamaño y hash incorrectos, MIME, límites, ausencia de store, opt-in apagado y rechazos por READ, scope extraño, Campaign no-MULTI/APPROVED/PUBLISHED.

El job **Backend · instalación y healthcheck** de `.github/workflows/ci.yml` ejecuta el nuevo script en PR. Mantener verde la CI total y verificar post-merge de `main` solo si un mantenedor aprueba la fusión.

## Siguiente incremento (aún no implementado)
Manifiesto durable unificado con 13 roles, nombre/ruta original y procedencia, cuotas agregadas, auditoría, multipart COG/RGB y cotejo de SHA verificado por servidor; previsualización privada MANAGE, aprobación institucional individualizada y publicación atómica únicamente tras firmas/controles de calidad.

**Prohibido asumir que un recibo QML equivale a publicación o validación de mapas.**
