# H14 / 2H-2D/3C — Diagnóstico privado postaprobación de cargas S3 sin limpieza

## Motivación y alcance

Tras aprobar o publicar una Campaign, el flujo normal H14 de `start`, `inspect`, `abort` y conciliación previa a la aprobación **se bloquea**. Esto es correcto para proteger el expediente, pero dificulta detectar cargas multipart incompletas que hayan quedado en S3 por fallos parciales.

Esta entrega añade **solo una ruta privada de diagnóstico** de cargas remotas residuales en Campaign **APPROVED** o **PUBLISHED**. No realiza ninguna acción de limpieza, alteración de estado, recepción de bytes o publicación, y no modifica los controles existentes de los otros endpoints. La inspección conserva los mismos controles de identidad de manifesto/slot/Asset/ticket SQL.

**Dependencia:** PR #259 → #262 → #263 → #264 → #265 → #266 → #267 → #268 → #269 → este PR.

## Contrato HTTP

`POST /api/v1/dbi/organizations/{org}/farms/{farm}/plots/{plot}/campaigns/{campaign}/scientific-intake/private-raster-postapproval-audit/{role}/{index}`

Payload estricto, igual que el ticket H14: `schema_version`, `manifest_sha256`, `reservation_sha256` e `idempotency_key` original. Para ortofoto: `rgb/_`; para los seis COG: `scientific_cog/<índice>`.

Solo se registra y ejecuta con:
- `DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED=1` y
- `DBI_ENVIRONMENT=test|development|local`.

En `production`, `staging` y entornos no declarados está **cerrado incluso si el flag está activado**. No configurar en Render.

## Autorización y consistencia

1. Exige **MANAGE** sobre el lote de la organización/tenant; realiza `SELECT ... FOR UPDATE` de la Campaign **exacta**. Acepta únicamente estado `APPROVED` con `approved_at` y sin `published_at`, o `PUBLISHED` con ambos timestamps. Rechaza Campaign de otro tenant, otro tipo de análisis, estados previos o timestamps contradictorios.
2. Relee manifiesto y reserva S3 **privados e inmutables** y verifica sus SHA-256 en JSON, scope, rol, índice, operador reservador e identidad del TIFF de destino. Para esta primera etapa se exige también que el **operador que realiza la auditoría sea el mismo que registró originalmente la reserva**, conservando MANAGE. No existe todavía un contrato de delegación institucional para un administrador distinto.
3. Bloquea y verifica `Binding`, `Asset`, ticket de preparación y referencia del proveedor SQL con sus ámbitos y contenido declarados. La clave de idempotencia correcta evita atribuir a otro expediente una referencia remota.
4. Consulta **solo** `inspect_incomplete_uploads` del adaptador `DBIS3MultipartAdapter` en S3 loopback, usando la clave exacta del objeto DBI. Reutiliza los ocho estados de conciliación de la etapa 3A; devuelve **contadores y banderas**, nunca `UploadId`, bucket, objeto interno, credenciales ni URL.
5. Ejecuta `session.rollback()` para liberar los locks **sin escritura SQL ni S3**. Si S3 no responde, los hashes no cuadran o existen incongruencias, rechaza sin suponer limpieza exitosa.

Los estados `remote_orphan_without_sql`, `sql_active_remote_missing`, `sql_active_remote_replaced`, `sql_active_remote_extra` y `sql_aborted_remote_remains` exigen revisión. En una Campaign ya aprobada, **incluso `active_exact_single_upload` obliga a revisión**: la carga remota sigue abierta y no debe continuar transfiriendo archivos. Solo `no_remote_no_sql` y `sql_aborted_no_remote` pueden declararse sin residuo remoto observable.

La respuesta contiene `remote_cleanup_required=true` si la lista reporta al menos un UploadId incompleto. `manual_review_required` también puede ser verdadero cuando la referencia SQL es contradictoria aunque S3 no tenga cargas incompletas. La aprobación de Campaign **no significa aprobación de los TIFF**: las banderas de asset aprobado/publicado siguen falsas.

## Límites de seguridad

- **No** hay aborto automático postaprobación, borrado, compensación, permisos multipart, grants, descarga, subida de partes, ETags ni envío a clientes.
- El diagnóstico de S3 y la lectura SQL no constituyen una transacción distribuida. El resultado es una instantánea bajo locks de DB; una operación externa S3 podría producir cambios después.
- Si el resultado de `create_multipart_upload` se perdió o el commit SQL tuvo un resultado incierto, la inspección **informa** del residuo, pero no lo recupera ni borra. La conciliación institucional y limpieza posterior necesita una nueva etapa con permiso explícito, pista de auditoría, retención y pruebas de carrera.
- La ruta conserva la restricción **solo-loopback** del adaptador existente; no constituye una autorización para S3 externo.
- No se añade migración, no se modifica el esquema, no se cambian los PR previos ni se realizan fusiones/deploys.

## CI

`.github/scripts/ci_dbi_scientific_raster_postapproval_audit.py` cubre ausencia de inicio SQL, carga remota huérfana, referencia exacta activa tras aprobación, Published, rechazo por Campaign preaprobada o inconsistente, READ/actor/tenant ajeno, S3 caído, y cierre en staging/production. También verifica que el código nuevo no llama a initiate, abort, issue_part_access o commit.

**Siguiente incremento posible:** definir una autorización institucional explícita para limpieza, más registro de auditoría y aborto idempotente de referencias remotas *solo si* la conciliación exacta y la política de retención lo permiten; antes, auditar los bloqueos concurrentes de aprobación del sistema. Esto no habilita transferencia de partes.
