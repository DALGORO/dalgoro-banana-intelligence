# H14 / 2H-2D/1 — Sesiones preparatorias privadas, SIN iniciar multipart

## Alcance técnico

Se implementa un **ticket SQL de preparación** para los activos TIFF de H14 (RGB y los seis COG), vinculado a la fila Asset científica del PR #265, al vínculo SQL del #264 y al manifiesto/reserva privados. **No es una sesión multipart de proveedor**: no existe `provider_upload_ref`, no se llama a S3 multipart y no se emite ningún permiso de carga, URL o token. El titular puede **preparar, consultar y cancelar** el ticket de manera idempotente; no puede transmitir ninguna parte.

La cadena pendiente de PR es **#259 → #262 → #263 → #264 → #265 → este PR**. Este PR no debe entrar a `main` antes de esas dependencias.

## Nueva revisión (no aplicar a Render)

La revisión Alembic `dbi_0032_raster_session_prep`, derivada de `dbi_0031_raster_asset`, crea `dbi_scientific_raster_session_preparations`.

- FK `(asset_id, binding_id)` contra el Asset científico con vínculo exacto y unicidad por `asset_id`. **Un solo ticket histórico por Asset**; no se reabre de forma silenciosa un ticket expirado/cancelado. Una nueva versión deberá tener expediente/versionado explícito en otra revisión futura.
- Campos Campaign/tenant/organización/finca/lote, `manifest_sha256`, `reservation_sha256`, tamaño y `declared_sha256` de TIFF **declarados**, identificador de usuario, timestamps y `idempotency_key_hash` SHA-256. No persiste la clave idempotente original.
- `prepared_no_provider` o `cancelled_no_provider`; transición de cancelación bajo bloqueo SQL y marca `cancelled_at`. Expira lógicamente al cumplirse `expires_at` (**TTL 1 hora**), sin proceso automático ni permisos de proveedor que revocar.
- Solo tamaños estrictamente **mayores a 64 MiB** (la política existente clasifica esos casos `multipart`), hasta 10 GiB por TIFF. Archivos pequeños se mantienen fuera de este ticket y requerirán flujo síncrono seguro separado.
- Partes nominales **64 MiB**, máximo 10.000 partes, ventana de referencia de 8 y concurrencia máxima planificada de 4, `SHA256/COMPOSITE` **solo de transporte**. No equivale al SHA-256 completo del TIFF.
- La base verifica invariantes por CHECK y FK; el downgrade rechaza borrar un historial con tickets existentes.

## API protegida

Se registra únicamente si **ambas** variables cumplen:
`DBI_SCIENTIFIC_RASTER_SESSION_PREP_ENABLED=1` y
`DBI_ENVIRONMENT=test|development|local`.
`production`, `staging` o variable vacía permanecen cerrados incluso si el flag se activa. **No activar en Render.**

`POST /api/v1/dbi/organizations/{org}/farms/{farm}/plots/{plot}/campaigns/{campaign}/scientific-intake/private-raster-session-preparations/{role}/{index}/{operation}`

Las operaciones permitidas son `prepare`, `inspect` y `cancel`. Para RGB se usa `role=rgb/index=_`; los seis COG usan `role=scientific_cog/index=<índice>`. Payload estricto: `schema_version`, `manifest_sha256`, `reservation_sha256`, `idempotency_key`. No acepta rutas, tamaños, claves S3 ni objetos arbitrarios del cliente.

**En CADA operación:**

1. Exige MANAGE y bloquea Campaign real mediante `SELECT FOR UPDATE`, confirmando MULTISPECTRAL, scope exacto y estado anterior a aprobación/publicación.
2. Lee y verifica los bytes e integridad del **JSON** de manifiesto y reserva S3 privados; comprueba hash solicitado, actor, rol/índice y ausencia de TIFF de destino.
3. Bloquea SQL `binding` y `asset`; confirma que ambos son los registros exactos y que el Asset permanece `registered_pending_bytes`, sin contenido, sin verificación científica ni aprobación.
4. La operación usa una transacción SQL: `prepare` crea solo si no existe, y un reintento con la misma clave y misma evidencia devuelve 200; otra clave/evidencia = 409; `inspect` no escribe; `cancel` sella el ticket, con repetición idempotente. No hay devolución de URLs ni grants; respuesta `Cache-Control: no-store`.

**Condición de concurrencia:** el bloqueo de Campaign protege la operación frente a cambios de estado solo si los escritores de aprobación/publicación siguen el mismo patrón transaccional. Antes de permitir carga real hay que auditar el camino completo de aprobación y revocación.

## Lo que no permite

No inicia `DBIS3MultipartAdapter` ni usa el uploader legacy. **Sin proveedor, sesiones activas, reanudación real, upload de partes, grants, presigned URLs, ETags, bytes TIFF, validación de COG ni publicación cliente.** El reporte impone `ready_for_upload=false`, `provider_started=false`, `session_started=false`, `grants_issued=false`, `file_received=false`, `content_verified=false`, `institutional_approved=false`, `published=false`.

El próximo incremento tendrá que implementar un proveedor real y **validación de Campaign + manifiesto + Asset en cada grant, parte, reanudación, completado y abortado**, con pruebas de concurrencia, compensación ante fallos S3/SQL, expiración/revocación institucional y posterior verificación SHA-256 **completo** del objeto ensamblado.

## Validación

`.github/scripts/ci_dbi_scientific_raster_session_preparations.py`: recorre siete escenarios sintéticos con TIFF de 128 MiB, requiere que el binding y Asset existan previamente, comprueba idempotencia, cancelación, bloqueo de replay, scope, READ, postaprobación, alteración de huellas, fallo S3 y flag cerrado. Revisa CHECK, FK, límites y no emisión de grants. La CI existente comprueba Alembic/PostgreSQL/PostGIS en contenedores **temporales**, no en la base productiva.
