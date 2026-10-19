# DBI H14 / 2H-2D/3H — Contrastar evidencia revisada con inventario S3 nuevo

## Propósito

Después de **#274** (observación privada inmutable), **#275** (revisión por un operador independiente) y **#277** (integridad de la cadena documental), este incremento responde a una pregunta adicional:

**¿Sigue coincidiendo el inventario S3/SQL observado originalmente con una nueva evaluación del mismo activo científico?**

La comparación es de **solo lectura**, no emite permisos ni crea autorización de limpieza. Un resultado coincidente **no** faculta a nadie para abortar sesiones, cargar archivos o publicar resultados.

Este PR está apilado sobre **#277**; dependencias anteriores: **#275 → #274 → #272 → #270 → #269 → #268 → #267 → #266 → #265 → #264 → #263 → #262 → #259**. El PR #271 contiene una alternativa parcialmente superpuesta a #270: resolverla antes de cualquier fusión. No modificar `main` directamente.

## Separación de identidades

El endpoint `POST /api/v1/dbi/organizations/{org}/farms/{farm}/plots/{plot}/campaigns/{campaign}/scientific-intake/private-raster-reviewed-live-audit/{role}/{index}` es invocado por el **autor original de la observación**, autenticado con MANAGE y exactamente dentro del tenant/organización/finca/lote/Campaign MULTISPECTRAL. Es obligatorio señalar al **revisor original, que debe ser otra persona**, y las huellas de ambos objetos privados y del diagnóstico original.

El solicitante no puede hacerse pasar por el revisor: el servidor relee el objeto inmutable que registró ese revisor previamente, verifica identidad, enlace a la observación original, actor distinto, estado de Campaign, serialización canónica y SHA-256 completo de ambos JSON. Los parámetros no permiten que el cliente suministre contadores S3, acciones, estado SQL ni evidencia viva.

La auditoría actual se ejecuta con las **credenciales y la clave idempotente del autor original** mediante el contrato existente `preview_scientific_raster_cleanup` de #272, que a su vez vuelve a ejecutar la auditoría S3/SQL postaprobación de #270. No existe impersonación del revisor.

## Procedimiento y límites de consistencia

1. `SELECT FOR UPDATE` de Campaign `APPROVED/PUBLISHED` con timestamps coherentes y MANAGE.
2. Lectura estricta de la observación y la constancia del revisor almacenadas en S3 privado: direcciones opacas derivadas del ámbito, MIME, longitud, SHA-256 de **bytes reales**, JSON canónico, referencias y banderas que niegan autorización/ejecución.
3. `session.rollback()` para liberar la primera lectura.
4. Nueva auditoría postaprobación **autorizada como autor original**, que vuelve a bloquear y validar Campaign, Manifest, Slot, Binding, Asset, ticket, referencia SQL e inventario incompleto S3 para el TIFF exacto; ese método también libera sus locks sin escribir.
5. Compara digest de evidencia, estado de conciliación, acción propuesta, contadores S3, candidato registrado y necesidad de revisión manual. Si los datos han cambiado, `evidence_drift_detected=true`; si siguen coincidiendo, `snapshot_matches_live=true`.

**Importante:** los pasos 1–3 y 4 son dos transacciones de solo lectura distintas; **NO** hay atomicidad conjunta S3 ↔ SQL, y el inventario remoto puede modificarse después de la comprobación. La respuesta incluye `separate_nonatomic_read_transactions=true`, `manual_review_required=true` incluso cuando no hay cambios y nunca se toma una decisión ejecutiva automática.

## Protección de despliegue

Ruta registrada solo cuando se establecen simultáneamente:

- `DBI_SCIENTIFIC_REVIEWED_LIVE_RECHECK_ENABLED=1`
- `DBI_SCIENTIFIC_CLEANUP_CHAIN_VERIFY_ENABLED=1`
- `DBI_SCIENTIFIC_CLEANUP_PEER_REVIEW_ENABLED=1`
- `DBI_SCIENTIFIC_CLEANUP_EVIDENCE_ENABLED=1`
- `DBI_SCIENTIFIC_RASTER_CLEANUP_PLAN_ENABLED=1`
- `DBI_SCIENTIFIC_RASTER_POSTAPPROVAL_AUDIT_ENABLED=1`
- `DBI_ENVIRONMENT=test|development|local`

El entorno `production` o `staging` bloquea siempre la ruta aun con flags. **No activar en Render**. El contrato de auditoría original sigue exigiendo S3 privado para los JSON y adaptador multipart S3 solo-loopback; en CI los reemplazan dobles sintéticos.

## Exclusiones

No se modifican SQL ni objetos S3, ni se crean migraciones. No hay `provider.abort`, `provider.initiate`, creación de partes, grants, presigned URLs, reanudación, SHA-256 completo del TIFF ni publicación de resultados. `historical_chain_verified=true` y `live_s3_inventory_rechecked=true` **no** constituyen firma institucional, delegación, aprobación de limpieza ni garantía de que S3 siga igual después.

La próxima etapa requiere definir **autorización institucional firmada y verificable**, delegación/retención, ventanas de caducidad y reconstrucción/validación de evidencia fresca **bajo el mismo protocolo de exclusión/concurrencia que cualquier futura acción**. También se necesitan pruebas E2E conjuntas PostgreSQL+MinIO y fallos de red antes de introducir comandos que aborten sesiones.

## Pruebas

`.github/scripts/ci_dbi_scientific_raster_reviewed_live_audit.py` crea observación y revisión separadas, verifica comparación coincidente y divergente, consulta con el autor real, intentos de impersonación del revisor, READ/tenant ajenos, corrupción JSON, huellas/manifiesto erróneos, Campaign cambiada, flags desactivadas y ausencia de escritura/grants. En estas pruebas la nueva auditoría viva se **simula** mediante el contrato existente. La CI heredada incluye una prueba real de inicio/inventario/aborto de MinIO loopback, **pero no constituye una prueba integrada del nuevo endpoint contra PostgreSQL + MinIO real**.
