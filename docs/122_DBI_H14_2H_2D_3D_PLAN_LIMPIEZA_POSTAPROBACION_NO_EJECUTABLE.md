# DBI H14/2H-2D/3D — Plan de limpieza postaprobación sin ejecución

## Motivación y dependencias

H14/2H-2D/3A (#268) identifica cargas S3 multipart incompletas. H14/2H-2D/3B (#269) verifica inicio, inventario y aborto frente a un MinIO efímero real. H14/2H-2D/3C (#270) audita las cargas residuales después de que una Campaign está APPROVED o PUBLISHED. **Ninguna de estas etapas autoriza la destrucción de registros ni la emisión de grants.**

Este incremento está **apilado sobre #270**, que depende de #269, #268, #267, #266, #265, #264, #263, #262 y #259. Existe además el **PR paralelo #271**, sobre #268, que implementa inventario forense postaprobación parecido al #270. **No integrar ambos ciegamente**: son alternativas superpuestas que deben compararse y reconciliarse antes de una fusión ordenada.

## Nuevo endpoint experimental

`POST /api/v1/dbi/organizations/{org}/farms/{farm}/plots/{plot}/campaigns/{campaign}/scientific-intake/private-raster-cleanup-dry-run/{role}/{index}`

Requiere:

- `DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED=1` **y** `DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED=1`.
- `DBI_ENVIRONMENT=test|development|local`. La ruta ni se registra en `production` o `staging`, aunque alguien configure ambos flags. **No activar en Render.**
- El mismo payload estricto de H14/2H-2D: `schema_version`, `manifest_sha256`, `reservation_sha256`, `idempotency_key`. No se permite enviar por cliente un estado S3/SQL o un plan de borrado inventado.

Se reutiliza de forma directa la auditoría postaprobación existente, que exige operador reservador con permiso MANAGE, bloquea Campaign con `SELECT FOR UPDATE` y verifica Campaign APPROVED/PUBLISHED con timestamps consistentes, manifiesto y slot S3 privados, Binding/Asset/ticket SQL y listado por clave exacta de cargas incompletas del S3 local. Al terminar la auditoría ejecuta `session.rollback()` **para liberar locks sin escribir**. La política pura solo transforma **la respuesta verificada internamente** en un plan no operativo.

## Política conservadora

| Estado de inventario postaprobación | Propuesta | Ejecución |
| --- | --- | --- |
| `no_remote_no_sql` o `sql_aborted_no_remote` | `none_no_remote_uploads`: nada remoto que limpiar | Ninguna |
| `active_exact_single_upload` | `review_exact_recorded_upload`: única carga SQL ↔ S3 exacta; candidata a revisión de aborto | **Sin autorización** |
| `sql_active_remote_missing` | `investigate_missing_recorded_upload`: referencia SQL sin carga remota | Ninguna |
| `remote_orphan_without_sql`, `sql_active_remote_replaced`, `sql_active_remote_extra`, `sql_aborted_remote_remains` | `investigate_unknown_remote_uploads`: anomalía/huérfano para cuarentena y análisis | Ninguna |

La política rechaza contadores negativos/booleanos, esperados extraños, estados desconocidos, índices y banderas contradictorias. **Ni siquiera el caso de una única carga exacta permite abortar automáticamente.** La decisión de limpieza real exigiría contrato futuro: autoridad institucional expresa, doble control si aplica, auditoría durable y retención, conciliación S3↔SQL ante commit incierto, manejo de carreras y confirmación de borrado exacto.

## Huella del diagnóstico

Se calcula `evidence_sha256` a partir de una serialización JSON canónica con separación de dominio, Campaign/Asset/preparación/rol/índice, estado institucional y estado/contadores de S3↔SQL. Permite comparar **dos lecturas de diagnóstico**: una diferencia de inventario produce una huella distinta.

**Limitaciones:** la huella no es HMAC, firma, recibo inmutable, timestamp certificado, autorización de limpieza ni evento persistido en SQL/S3. El endpoint devuelve `evidence_signed=false` y `evidence_persisted=false`, y no revela UploadId, clave S3, bucket o credenciales. El listado remoto puede cambiar entre auditoría y cualquier operación futura: una huella anterior **no** puede aprobar un aborto posterior.

## Frontera de seguridad

La respuesta fija **`cleanup_authorized=false`**, `cleanup_executed=false`, `ready_for_upload=false`, `grants_issued=false`, `parts_received=false`, `file_received=false`, `content_verified=false`, `institutional_approved=false` y `published=false`. Ninguna ruta nueva inicia, carga partes, concede grants, completa objetos, aborta, borra o publica. Tampoco crea/ejecuta revisiones Alembic, modifica Render, activa la interfaz del cliente ni altera las rutas anteriores.

## Pruebas

`.github/scripts/ci_dbi_scientific_raster_cleanup_dry_run.py` prueba los ocho estados bajo Campaign APPROVED y PUBLISHED, unicidad/estabilidad de huella, rechazo de evidencia inconsistente, los dos flags de activación, cierre de rutas en producción/staging y ausencia de operaciones S3/SQL mutantes. La auditoría de permisos e integridad S3/SQL sigue cubierta por `.github/scripts/ci_dbi_scientific_raster_postapproval_audit.py`; MinIO real por `.github/scripts/ci_dbi_scientific_minio_real.py`.

## Próximo paso

Antes de implementar cualquier aborto real postaprobación, desarrollar un **expediente durable y explícito de autorización administrativa de limpieza**, con identificación inequívoca de UploadId bajo servidor, retención y actor responsable; bloqueo de Campaign y referencias SQL, relectura de S3 inmediatamente antes de borrar, política ante fallos S3↔SQL y pruebas simultáneas PostgreSQL+MinIO con carreras. Hasta entonces las anomalías detectadas **solo se revisan**.
