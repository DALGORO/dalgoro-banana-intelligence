# DBI-PORTAL-GIS-004A · Preparación GIS privada sin publicación

## Alcance

Este incremento convierte **un archivo GIS recibido** en una **vista previa GeoJSON privada**, asociada a la misma Campaign del origen. La capa **NO** aparece en el visor del cliente ni se inserta en `dbi_portal_vector_layers`: un gestor con MANAGE debe revisar la capa antes de publicar (incremento siguiente).

La recepción web está en `docs/48_DBI_PORTAL_PRIVATE_GIS_RECEIPTS.md`. La conversión real sigue estando exclusivamente en `services/banana-density/portal_gis_convert_cli.py`; FastAPI no importa ni Pyogrio ni GDAL.

## Flujo implementado

1. Un proceso geoespacial independiente ejecuta `DBIPortalGISPreparationWorker.process_one(tenant_ref=...)`, con una única identidad de tenant explícita. Claim PostgreSQL `FOR UPDATE SKIP LOCKED`, estado `processing`, `processing_ref` aleatorio y máximo de tres intentos. Claims activos de otro proceso no se reclaman hasta 15 minutos.
2. Se deriva por servidor la dirección privada `TECHNICAL_SOURCE` con tenant y UUID, y se descarga por streaming verificando íntegramente tamaño, tipo MIME y SHA-256. Los bytes originales no se entregan al cliente.
3. En un directorio temporal aislado se llama al conversor GIS existente que comprueba geometría, CRS, atributos y límites. El worker comprueba nuevamente manifiesto, hash del origen y del derivado, tamaño, `captured_at: null` y GeoJSON válido WGS84.
4. Se guarda hasta 2 MiB de capa convertida en **`dbi_portal_gis_previews`** y marca `prepared`. Un intento que perdió el `processing_ref` no puede escribir resultados. Se eliminan los temporales.
5. `GET /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/gis-imports/{import_id}/preview` exige `MANAGE` y scope exacto; no facilita la capa si todavía no está `prepared` ni expone el original.

Los fallos de fuente, manifiesto o validación se marcan `failed`, sin publicar. Un cierre abrupto deja `processing` hasta vencer el claim; si se agotaron tres intentos, requiere intervención operativa, no reintento infinito.

## Ejecución para pruebas locales (no producción)

En un entorno Python que disponga de las dependencias tanto del backend DBI como del motor geoespacial, y con PostgreSQL DBI ya migrado a `dbi_0023_gis_previews`, configurar:

- `DBI_ENVIRONMENT=local` o `development`, y `DBI_DATABASE_URL` (según configuración del runtime DBI).
- `DBI_LOCAL_STORAGE_ROOT` **absoluto y persistente**, el mismo utilizado para recibir el archivo.
- `DBI_GIS_WORKER_ROOT` **absoluto y separado** para temporales GIS.

Una operación por vez:

```powershell
python services/banana-density/portal_gis_prepare_local.py --tenant "<tenant DBI autorizado>"
```

El argumento tenant debe venir del servicio autorizado, nunca de una petición pública al worker. Esta utilidad rechaza expresamente entornos de producción. Se fuerza `PROJ_NETWORK=OFF` y `GDAL_PAM_ENABLED=NO`. Para producción quedan pendientes orquestador separado, storage privado persistente compartido, límites de procesos y monitoreo.

## Publicación intencionalmente pendiente

Falta la **acción MANAGE explícita de aprobar/publicar la vista previa**, con revalidación de Campaign/lote y una transacción idempotente que cree `DBIPortalVectorLayer`. Hasta que eso se implemente y pruebe, solo se muestran los estados `received`, `processing`, `prepared` o `failed` en el panel de gestores.

## Pruebas

`ci_dbi_gis_preparation.py` verifica claim, tenant, SHA, persistencia preview, no-publicación, limpieza temporal, error de fuente y scope de vista previa. `ci_portal_gis_converter.py` continúa validando el conversor real con GPKG y SHP sintéticos; pruebas de integración PostGIS verifican migración y restricciones de esquema. Faltan pruebas de extremo a extremo con archivos reales de clientes y almacenamiento S3 productivo.

Nada de este flujo modifica GOLD, YOLO, Density ni las máscaras científicas.
