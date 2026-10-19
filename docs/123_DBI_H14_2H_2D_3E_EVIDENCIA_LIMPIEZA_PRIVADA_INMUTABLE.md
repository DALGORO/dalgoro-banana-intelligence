# H14 / 2H-2D/3E — Archivo privado e inmutable de observaciones de limpieza

## Propósito y cadena de dependencias
Esta etapa depende de **#272** (plan de limpieza no ejecutable), previamente **#270 → #269 → #268 → #267 → #266 → #265 → #264 → #263 → #262 → #259**. El PR paralelo **#271** es una alternativa superpuesta de auditoría y **no debe fusionarse a ciegas junto con #270**.

El plan #272 producía un `evidence_sha256` canónico de una observación S3/SQL, pero no la guardaba. Esta etapa guarda una **copia privada e inmutable** del diagnóstico en S3 con referencia verificable. **No autoriza un borrado:** no confundir el registro con una resolución institucional firmada.

## Endpoint experimental
`PUT /api/v1/dbi/organizations/{org}/farms/{farm}/plots/{plot}/campaigns/{campaign}/scientific-intake/private-raster-cleanup-observations/{role}/{index}`.

Requiere conjuntamente:
- `DBI_SCIENTIFIC_CLEANUP_EVIDENCE_ENABLED=1`.
- `DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED=1`.
- `DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED=1`.
- `DBI_ENVIRONMENT=test|development|local`.

En `production`, `staging` o sin entorno, la ruta no se registra. **No habilitar en Render.**

El payload contiene `schema_version=dbi-h14-cleanup-evidence-submission.v1`, `inspection` (la solicitud original de auditoría H14) y `expected_evidence_sha256` para detectar diagnósticos obsoletos. El cliente **no puede especificar** el estado del proveedor, la acción recomendada, autorización de limpieza, destino S3 ni ubicación privada.

### Flujo
1. Reejecuta `preview_scientific_raster_cleanup` del PR #272, que vuelve a auditar Campaign postaprobación con el **mismo operador reservador** y permiso MANAGE, `SELECT FOR UPDATE`, manifiesto y reserva privados, Binding/Asset/ticket SQL y estado S3 de clave exacta. Su `rollback()` libera los bloqueos.
2. Comprueba que el `evidence_sha256` actual siga siendo el esperado por el operador; deniega cualquier divergencia, flags de autorización, ejecución o publicación activas.
3. Construye JSON **canónico**, máximo **8 KiB**, con tenant, organización, finca, lote, Campaign, actor, rol/índice, SHA de manifiesto/reserva/diagnóstico, estado institucional, clasificación S3, número de cargas remotas y acción sugerida. Todas las banderas de autorización, firma, ejecución y recepción son **falsas**. No guarda UploadId, bucket, URL ni token.
4. Guarda en **DBIS3ObjectStore privado obligatorio** (`ANALYSIS_INPUT`) mediante clave opaca UUIDv5 derivada de scope + actor + huella, `put` inmutable `IfNoneMatch=*`, SHA-256 del JSON y readback inmediato de bytes. Un reintento exacto devuelve 200; nueva observación de evidencia diferente produce otro ID, sin sobrescribir la anterior; objeto divergente/corrupto devuelve error.
5. Devuelve únicamente ID opaco del recibo, SHA-256 del JSON, SHA del diagnóstico, `recorded_at`, `created`, `evidence_persisted=true`, con todos los permisos de limpieza, firma, transferencia, recepción y publicación **falsos**.

## Límites científicos, administrativos y de concurrencia
- **No existe una firma institucional**, orden de borrado, expediente de aprobación delegada, autenticación de doble firma ni autorización de ejecución. El recibo **nunca se interpreta como mandato de limpieza**.
- La lectura previa y la escritura S3 ocurren en instantes separados. Si el proveedor cambia tras la auditoría, el recibo preserva lo que se observó, **no certifica que ese estado siga vigente**. Un proceso futuro de limpieza deberá volver a bloquear Campaign y verificar la referencia exacta inmediatamente antes de actuar.
- El registro S3 es evidencia privada bajo control de acceso, **no un log inviolable o legalmente firmado**, ni sustituye controles institucionales de retención, trazabilidad, copias de seguridad y roles segregados.
- Los siete originales científicos continúan privados: no se guardan ni se validan bytes TIFF, no se conceden grants, no se inician/abortan cargas multipart y no se publican resultados para clientes.
- No se modifican tablas ni migraciones; la dependencia operativa de S3 implica que un fallo impide afirmar persistencia.

## Pruebas
`.github/scripts/ci_dbi_scientific_raster_cleanup_evidence.py` valida escritura y lectura íntegra de bytes del JSON, reintento idempotente, huella obsoleta, identidad diferenciada de observación, rechazo de flags contradictorios, corrupción S3, todos los flags de entorno y ausencia de acciones mutantes. Emplea doble de almacenamiento **solo en CI**: el backend real exige `DBIS3ObjectStore`. Las suites existentes comprueban la auditoría y el protocolo MinIO real independientemente.

## Próximo paso
Expediente institucional de decisión **separado**, con autoridad de responsable/revisor, firma y retención, registro de operaciones compensatorias y pruebas de concurrencia real PostgreSQL + MinIO. Hasta superar esos controles, esta evidencia únicamente sirve para investigar y **no puede desencadenar un aborto S3**.
