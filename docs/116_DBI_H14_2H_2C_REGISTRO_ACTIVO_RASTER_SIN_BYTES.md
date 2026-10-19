# DBI H14 / 2H-2C — Registro SQL de activos RGB y COG científicos

## Entrega
Esta etapa incorpora un **Asset científico realmente registrado en SQL**, separado del catálogo genérico `dbi_analysis_input_assets`, que no distingue los seis índices científicos. Se preservan las funciones de activos/densidad ya desplegadas. El nuevo registro **todavía no significa que existan bytes del archivo en S3**.

Rama dependiente: **PR #259 → #262 → #263 → #264 → 2H-2C**. No fusionar fuera de orden.

## Esquema y condiciones de integridad
Revisión Alembic `dbi_0031_raster_asset` (después de `dbi_0030_raster_binding`), **NO aplicada en Render**:

- Tabla nueva `dbi_scientific_raster_input_assets` con un Asset por `binding_id`, tipo `orthophoto_rgb` para ortofoto o `scientific_cog` para seis índices (NDVI, NDRE, GNDVI, EVI2, CI-red-edge, CI-green).
- FK compuesta `(binding_id, tenant_ref, campaign_id, role, index_ref)` al vínculo scoped, con unicidad por `binding_id` y `(tenant_ref, target_object_id)`. Así el mismo ID de Asset no representa otra Campaign/rol.
- La tabla de vínculos pasa de `reserved_no_asset` a **`asset_registered_pending_bytes`** con `asset_id` obligatorio. FK compuesta inversa `(asset_id, binding.id)` hacia `(asset.id, asset.binding_id)`; mantiene correspondencia 1:1 exacta. El estado previo permanece permitido para reservas sin registrar. La transición de ambos registros se efectúa en una única transacción SQL, con Campaign bloqueada.
- **Bloqueo SQL CHECK:** solo `status='registered_pending_bytes'`, `file_received=false`, `content_verified=false`, `session_started=false`, `institutional_approved=false`, `published=false` para Asset. Cualquier evolución posterior exige otra revisión SQL explícita.
- Tamaño y SHA-256 siguen siendo **declarados**, no confirmados. MIME `image/tiff` estricto. Asset ID determinista UUIDv5 derivado de `binding_id` y `target_object_id`.

La migración tiene downgrade protegido: rechaza retirar la tabla si existen vínculos activos en lugar de borrar de manera silenciosa expedientes.

## Ruta privada
`POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/scientific-intake/private-raster-assets/{role}/{index}`

Requiere `DBI_SCIENTIFIC_RASTER_ASSET_REGISTRATION_ENABLED=1` **Y** `DBI_ENVIRONMENT=test|development|local`. Cerrada también con flag en production/staging.

Payload estricto: `schema_version=dbi-h14-raster-asset-registration-request.v1`, `manifest_sha256`, `reservation_sha256`. El cliente **no especifica** size, tipo Asset, ruta, objeto S3 ni ID: todo se recalcula del expediente inmutable.

1. Exige MANAGE y `SELECT FOR UPDATE` de Campaign MULTISPECTRAL preaprobación; deniega estado APPROVED/PUBLISHED y timestamps de aprobación/publicación aun inconsistentes.
2. Lee el manifiesto y reserva desde S3 privado, verifica huellas completas de ambos JSON y correspondencia exacta de tenant/organización/finca/lote/Campaign, rol/índice y actor. Confirma que aún no existe el TIFF de destino.
3. Bajo el bloqueo SQL de Campaign, el repositorio bloquea la fila `binding`, valida todo el expediente, inserta Asset con `ON CONFLICT DO NOTHING` y compara todos los campos inmutables con `SELECT FOR UPDATE`. Actualiza el vínculo a `asset_registered_pending_bytes` y `asset_id` en la **misma transacción**. Reintento exacto 200, nuevo 201; conflicto 409; error -> rollback.
4. Respuesta `Cache-Control: no-store` sin claves S3, presigned URLs ni grants.

## NO implementado
- **No** se modifica `AnalysisInputAsset` ni se habilitan uploads multipart antiguos.
- **No** existe sesión, parte, grant, TIFF recibido, SHA de TIFF verificado, validación COG, aprobación institucional, publicación o actualización del visor.
- La tabla y el endpoint requieren migración para funcionar en un entorno habilitado; **no aplicarla en Render/producción ni activar el flag por ahora**. La validación de PostgreSQL en CI es solo en infraestructura efímera de pruebas.
- Auditoría futura: snapshots institutionales de aprobación, retención, control temporal/locks en cada operación multipart, verificación de hashes del TIFF completo y cuarentena científica.

## Comprobaciones
`.github/scripts/ci_dbi_scientific_raster_assets.py` valida siete tipos/roles, registro idempotente, bloqueo con Campaign, prohibición cross-tenant/READ/postaprobación, conflicto de manifiesto/reserva/operador, S3 ausente, atomicidad de repositorio, dos FK compuestas y cierre de ruta en producción. Se suman los tests existentes del grafo Alembic y los jobs de PostgreSQL/PostGIS efímeros; **no se ejecuta ninguna migración productiva**.

## Paso posterior
H14/2H-2D: contrato de sesión multipart aislado del cargador legacy, cada transición reválida Campaign y las huellas de manifiesto/slot/binding/Asset; abort/revoke al aprobar. No habilitar grants hasta pruebas de concurrencia y reanudación, ni declarar contenido verificado hasta SHA-256 *completo* de cada TIFF ensamblado.
