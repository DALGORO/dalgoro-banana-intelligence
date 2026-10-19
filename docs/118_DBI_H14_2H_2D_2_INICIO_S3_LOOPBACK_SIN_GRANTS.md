# H14 / 2H-2D/2 — Inicio y aborto S3 multipart *loopback*, sin grants

## Alcance entregado

Primera integración real de transporte **exclusivamente en MinIO/S3 local de pruebas** para las preparaciones científicas creadas en #266. Se admite un inicio multipart del proveedor y un aborto confirmado, vinculados a cada Campaign, manifiesto, reserva, Binding y Asset científicos. **No se permite subir partes**: no existe endpoint de grants, no se retornan URLs ni `provider_upload_ref`, y las respuestas conservan `ready_for_upload=false`, `grants_issued=false`, `parts_received=false`, `file_received=false`, `content_verified=false`, `institutional_approved=false`, `published=false`.

Este PR depende en orden de **#259 → #262 → #263 → #264 → #265 → #266**. No fusionar fuera de orden.

## Nuevo esquema (sin migración productiva)

Revisión Alembic `dbi_0033_raster_provider_start`, después de `dbi_0032_raster_session_prep`. Tabla `dbi_scientific_raster_provider_starts`: una sesión por ticket/Asset/objeto futuro, con FK a preparación y FK compuesta a Asset/Binding. Guarda referencia S3 **solo en base de datos privada** (tratar como dato sensible; requiere cifrado/ACL y auditoría institucional antes de entornos no locales), actor, scope, hash y tamaño **declarados**, estado `initiated_no_grants` o `aborted_no_grants`, fechas. Constraints impiden estados que indiquen recepción o publicación. El downgrade se niega si existen sesiones. **No aplicar en Render.**

## Endpoint y permisos

`POST /api/v1/dbi/organizations/{org}/farms/{farm}/plots/{plot}/campaigns/{campaign}/scientific-intake/private-raster-local-provider/{role}/{index}/{operation}`, operaciones `start`, `inspect` y `abort`, payload de H14/2H-2D/1 (huellas de manifiesto y reserva, clave idempotente).

Registro SOLO con las dos condiciones:
- `DBI_SCIENTIFIC_RASTER_PROVIDER_START_ENABLED=1`
- `DBI_ENVIRONMENT=test|development|local`

**Producción, staging o entorno no especificado siempre cierran la ruta**, aun si el flag está activo. Usa **`request.app.state.dbi_scientific_raster_multipart_store` distinto del uploader legacy**; exige `DBIS3MultipartAdapter` real, cuyo constructor bloquea endpoints no loopback. No se acepta proveedor genérico o `DBIInMemoryObjectStore` en ruta real; CI inyecta dobles.

Para cada operación: MANAGE + `SELECT FOR UPDATE` Campaign MULTISPECTRAL no aprobada/publicada, verificación en S3 privado del manifiesto y la reserva inmutables, confirmación de destino TIFF aún ausente, bloqueo SQL de Asset/Binding y preparación, verificación del TTL cuando se inicia, bloqueo del ledger del proveedor. Reintento exacto de inicio existente no vuelve a iniciar S3; al abortar no reabre. La inspección no devuelve referencias remotas.

## Compensación y límites

Para `start`: mientras se mantiene el bloqueo de Campaign, se invoca S3 `create_multipart_upload`, se valida estrictamente el objeto retornado y se inscribe la referencia remota en SQL. Si falla la persistencia SQL **después de recibir el identificador S3**, se intenta `abort_multipart_upload` y se exige confirmación de limpieza. Si tampoco se confirma limpieza, 503 y **revisión manual obligatoria**; no se atribuye éxito. La iniciación que falla por pérdida de respuesta antes de entregar el identificador sigue siendo un riesgo de reconciliación: no habilitar operación en entornos externos sin un reconciliador fiable por objeto. Un commit SQL de resultado incierto también exige inspección cruzada entre SQL y S3 antes de reintentos operativos.

Para `abort`: aborto S3 de referencia exacta, confirmación de limpieza y sellado de estado en SQL + cancelación de preparación. Fallo SQL posterior al aborto deja un estado remoto y DB a conciliar; no hay grants emitidos. Se mantiene la prohibición de nuevo inicio si la Campaign pasa a APPROVED/PUBLISHED; **el flujo futuro necesitará limpieza administrativa postaprobación bajo política específica**, separada de todo acceso de cliente.

**El checksum `SHA256/COMPOSITE` es solo transporte, nunca equivale al SHA-256 completo del TIFF.** No se reciben partes, no hay transferencia cliente, reanudación, completado de objeto, validación COG, aprobación institucional ni publicación. El adapter local es adecuado para pruebas de protocolo, no está certificado para operar S3 externo o Render.

## Verificación

`.github/scripts/ci_dbi_scientific_raster_local_provider.py` cubre siete activos sintéticos, requisitos previos de preparación, idempotencia, aborto, rechazo postaprobación, denegación de otro operador, cierre del endpoint en entornos no locales, separación del proveedor legacy y ausencia de grants. Los jobs de migraciones se ejecutan solo con PostgreSQL/PostGIS temporales en GitHub, no sobre infraestructura del cliente.

Siguiente incremento: reforzar conciliación de fallos S3↔SQL, aborto administrativo postaprobación, pruebas de concurrencia con aprobación y recuperabilidad antes de habilitar grants de partes. **No activar este flag en Render ni en ningún entorno operativo real**.
