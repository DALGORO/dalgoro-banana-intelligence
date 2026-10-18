# H14 / 2H-2B — Vínculo SQL transaccional de reserva científica (sin Asset)

## Decisión de diseño y dependencias
Este PR se apila sobre **#263**, que a su vez requiere **#262** y **#259**. La tabla actual `dbi_analysis_input_assets` no distingue explícitamente COG científico por índice ni posee un vínculo obligatorio Campaign/huella de manifiesto. Por ello, **no se altera esa tabla ni se pretende que `flight_auxiliary` signifique un índice científico**. Se crea una tabla DBI separada para la primera **asociación SQL inmutable** del expediente científico, que quedará en estado `reserved_no_asset`.

**No ejecutar la migración en Render ni en ninguna base productiva.** Se incluye su código Alembic para revisión y validación del grafo; la ruta experimental está bloqueada en producción y staging.

## Modelo y revisión Alembic (no aplicada)
`app/dbi/models/scientific_raster_bindings.py` y revisión `dbi_0030_scientific_raster_binding` / `20261018_30_scientific_raster_bindings.py`:

- Un registro por `(tenant_ref, campaign_id, role, index_ref)`, donde `rgb/_` identifica ortofoto y `scientific_cog/<índice>` uno de seis índices; constraints de índice, tamaño y SHA-256 declarado.
- FK **compuesta** hacia Campaign: `campaign_id, tenant_ref, organization_ref, farm_id, plot_id, analysis_type='multispectral'`. Una colisión de identidad no puede ser redirigida a otro alcance o tipo de Campaign.
- `manifest_object_id`, `manifest_sha256`, `slot_object_id`, `slot_sha256`, `target_object_id`, tamaño/hash declarados del TIFF, operador reservador y operador registrador, fecha SQL.
- `asset_id IS NULL`, `status = 'reserved_no_asset'` **impuestos por CHECK de base de datos**. Ni siquiera SQL manual mediante el esquema actual puede presentar un Asset real o simular upload/verificación/publicación. La futura evolución a Asset científico requiere cambio de esquema y controles separados.
- Identificador SQL UUIDv5 determinista por tenant/organización/finca/lote/Campaign/rol/índice, sin nombres ni rutas de usuario. Restricciones únicas adicionales por objeto destino y objeto de reserva.

## Endpoint experimental y transacción
`POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/scientific-intake/private-raster-sql-bindings/{role}/{index}`

Payload estricto con `schema_version=dbi-h14-sql-raster-binding-request.v1`, `manifest_sha256`, `reservation_sha256`. Para RGB, `index=_`; para un COG, uno de los seis índices.

1. El operador debe disponer de **MANAGE** sobre todo el scope. Antes de leer objetos, `DBICampaignRepository.get_campaign_for_update` ejecuta **`SELECT ... FOR UPDATE`** de la Campaign real, dentro de la misma transacción de inserción. Rechaza Campaign distinta, no MULTISPECTRAL, aprobada o publicada, incluyendo timestamps contradictorios.
2. Dentro de ese bloqueo, lee desde S3 privado el **manifiesto y reserva** previos, y verifica su integridad SHA-256 y el hash exigido en la solicitud. Recalcula el objeto TIFF futuro y comprueba que el destino no está ya ocupado; no acepta datos de tamaño/role ni bucket del cliente.
3. El repositorio hace `INSERT ... ON CONFLICT DO NOTHING`, luego `SELECT ... FOR UPDATE` del binding exacto y **compara todas las propiedades inmutables**. Reintento exacto por el mismo operador = 200; creación = 201; divergencia/conflicto = 409.
4. `session.commit()` solo después de todos los controles. Cualquier rechazo o fallo ejecuta rollback y no concede ningún grant. `Cache-Control: no-store`.

**Límites:** la transacción serializa la creación del registro con cambios concurrentes de Campaign **si todos los escritores de estado siguen el bloqueo de fila**, requisito a auditar antes de habilitar cualquier carga. S3 no forma parte de la misma transacción SQL, pero tanto manifiesto como reserva son inmutables y su contenido se verifica; la futura operación multipart deberá releerlos.

## Bloqueo de exposición y etapas pendientes
Registro solo con `DBI_SCIENTIFIC_RASTER_SQL_BINDING_ENABLED=1` **Y** `DBI_ENVIRONMENT=test|development|local`; sin flag o en `production`/`staging`, la ruta ni se registra y las llamadas directas deniegan. No activar en Render. No existe ninguna nueva ruta para crear un Asset, Session, grant, transcribir partes o exponer TIFF/COG a clientes.

Las próximas tareas son:
- Revisar y autorizar una estrategia formal para `asset_kind='scientific_cog'` o modelo equivalente, relación FK duradera de ese Asset real con `DBIScientificRasterBinding`, contrato de identidad/tamaño/hash y auditoría.
- Incorporar revalidación de Campaign **en todos** los eventos multipart (iniciar, emitir partes, registrar, reintentar, completar, abortar y limpiar); reforzar bloqueo de aprobación concurrente y almacenamiento S3 durable apto para entornos previstos.
- Verificar por streaming SHA-256 **completo** del objeto ensamblado, nunca confundirlo con el checksum compuesto de transporte. Luego validar TIFF/COG científica y obtener aprobación institucional expresa antes de publicar.

## Validación
Nuevo test `.github/scripts/ci_dbi_scientific_raster_sql_bindings.py` con CI backend. Incluye fake S3/SQL para permisos, bloqueo de Campaign, reintentos, rol/índice, hashes desalineados, otro reservador, ámbito cruzado, postaprobación y cierre en production/staging; además compila `ON CONFLICT DO NOTHING` y `SELECT FOR UPDATE` PostgreSQL y revisa FK/constraints y cadena Alembic, **sin ejecutar migraciones**. Los tests de integración PostgreSQL de la tabla se exigirán antes de aprobar cualquier activación operacional; el CI actual no certifica una migración ejecutada.
