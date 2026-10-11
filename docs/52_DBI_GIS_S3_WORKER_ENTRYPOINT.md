# DBI-PORTAL-GIS-006 · Ejecutor GIS separado para S3 privado

## Alcance del incremento

El archivo `services/banana-density/portal_gis_prepare_s3.py` habilita una **única iteración de preparación GIS** desde un proceso geoespacial distinto del backend web. Reutiliza el mismo `DBIPortalGISPreparationWorker` que ya implementa claim transaccional `SKIP LOCKED`, token de fencing y límites de reintentos, y el mismo convertidor GPKG/SHP ZIP con Pyogrio y Shapely. No modifica los motores Density/GOLD y **nunca ejecuta la aprobación o publicación**.

La dependencia ligera `services/banana-density/requirements-gis-worker.txt` solo incluye GIS/S3/PostGIS; excluye YOLO, Torch y herramientas de inferencia. El job independiente `Portal GIS · preparación privada S3 aislada` comprueba instalación, permisos de arranque y conversión de fuentes sintéticas.

## Configuración para una ejecución controlada

**Esto es una guía de puesta en marcha, no un worker desplegado.** Antes de ejecutar se necesita un servicio aislado con:

- `DBI_ENVIRONMENT=staging` (o `production` únicamente tras UAT)
- `DBI_DATABASE_URL` de la base DBI del mismo entorno
- `DBI_STORAGE_BACKEND=s3`, y las variables S3 documentadas en `docs/51_DBI_PRIVATE_S3_STAGING_BOOTSTRAP.md`
- `DBI_GIS_WORKER_ROOT` absoluto, previamente creado por el usuario del servicio con permisos `0700`; no symlink
- Identificador exacto y autorizado del tenant de ese entorno, provisto por la configuración administrativa confiable (nunca derivarlo de nombres de archivos ni aceptar peticiones públicas)

Preparar el entorno con `pip install -r services/banana-density/requirements-gis-worker.txt` y ejecutar, desde `services/banana-density`:

```bash
python portal_gis_prepare_s3.py --tenant REFERENCIA_TENANT_AUTORIZADA
```

Cada invocación toma como máximo un original pendiente del tenant y prepara un GeoJSON privado (`prepared`); si no hay trabajo devuelve un mensaje informativo. Ninguna ejecución registra capas visibles; solo una posterior revisión `MANAGE` en el portal puede publicar.

## Restricciones de seguridad y pendientes antes de automatizar en Render

- Backend FastAPI y worker GIS deben tener **roles/credenciales distintos**, pero apuntar a la misma base DBI y el mismo bucket privado con namespaces segregados por tenant. No reutilizar credenciales de migrador.
- Usar ejecución en contenedor o worker con recursos restringidos (CPU, RAM, tiempo máximo, volumen temporal), sin privilegios y sin exponer puertos web. El ejecutor es one-shot y **no incluye scheduler** ni servicio Render automático.
- `PROJ_NETWORK=OFF` impide descargas automáticas de grids; `GDAL_PAM_ENABLED=NO` evita metadatos externos auxiliares. Limitar además el egress del proceso mediante red del despliegue cuando sea compatible con la conexión necesaria a S3 y PostGIS.
- Conservar `HTTPS`, TLS verificado y almacenamiento S3 privado. `DBI_LOCAL_STORAGE_ROOT` no está permitido para este worker remoto.
- Verificar manejo de `processing` expirado, seguimiento de intentos agotados, limpieza del workspace y alertas operativas. La recuperación tras caída depende de claims y `STALE_AFTER`; no confundirla con monitoreo ya habilitado.
- Aplicar las migraciones existentes hasta `dbi_0024_gis_approval` y ejecutar pruebas de extremo a extremo contra un lote real de staging, con perfiles `MANAGE` y `READ` independientes.

No se ha creado ni activado un despliegue externo, un cron, una cola productiva ni nuevas credenciales en esta fase.
