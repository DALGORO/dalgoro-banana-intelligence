# DBI-PORTAL-GIS-005B · Ejecutor S3 aislado de UNA importación GIS

## Estado

Código disponible para integrar en un servicio geoespacial **separado del
backend web**. No configura Render ni crea un scheduler, bucket, base,
credenciales o permisos. No debe anunciarse como worker 24/7 en producción
hasta ejecutar UAT real de punta a punta.

Entrada: `services/banana-density/portal_gis_prepare_s3.py`.
Se limita a procesar UNA importación en estado `received` por invocación.
La clase compartida de preparación usa claims PostgreSQL SKIP LOCKED,
fencing y un máximo de tres intentos (docs/49). No publica capas; estas
solo se vuelven visibles con la aprobación MANAGE independiente (docs/50).

## Variables y habilitación

Todas se configuran como secrets del servicio worker (nunca en el navegador):

- `DBI_ENVIRONMENT=staging` o `production`.
- `DBI_DATABASE_URL`: base DBI Postgres estrictamente del entorno.
- `DBI_STORAGE_BACKEND=s3`, `DBI_S3_ENDPOINT_URL` (HTTPS),
  `DBI_S3_BUCKET`, `DBI_S3_REGION`, `DBI_S3_ACCESS_KEY_ID` y
  `DBI_S3_SECRET_ACCESS_KEY`, con `DBI_S3_SESSION_TOKEN` si corresponde.
- `DBI_GIS_WORKER_TENANT`: un único tenant autorizado para esta instancia.
- `DBI_GIS_WORKER_ROOT`: carpeta absoluta temporal, fuera del repositorio,
  con permisos solo del proceso, distinta de cualquier almacenamiento duradero.
- `DBI_GIS_WORKER_ENABLED=1`: **interruptor obligatorio**; sin él la
  invocación no se conecta a S3 ni reclama trabajos.

Preflight estático (sin abrir S3 ni Postgres, sin procesar archivos):

```bash
python services/banana-density/portal_gis_prepare_s3.py --check
```

Invocación explícita en un servicio ya provisionado y previamente auditado:

```bash
python services/banana-density/portal_gis_prepare_s3.py --once
```

No agregar un bucle automático hasta disponer de scheduler/supervisión y
cierre ordenado; el proveedor Render y el costo del servicio deben definirse
en el ambiente staging. Tampoco ejecutar en el proceso HTTP del backend.

## Límites del proceso secundario

- Los bytes privados se descargan mediante el puerto S3 verificado por
  tamaño y SHA-256; ningún archivo se obtiene de una URL del usuario.
- El worker llama al conversor existente mediante `subprocess.run`, no
  pasando rutas desde el navegador ni ejecutando shell.
- Timeout duro de 120 segundos por conversión, máximo 80 segundos CPU,
  memoria virtual limitada a 4 GiB, tamaño máximo de salida por archivo
  4 MiB, máximo de 128 descriptores; exige Linux.
- El subprocess no hereda `DBI_DATABASE_URL`, claves S3 ni otro material
  secreto del ambiente; `PROJ_NETWORK=OFF`, GDAL auxiliar deshabilitado.
- El original queda persistido en bucket S3 privado, el derivado WGS84
  aparece únicamente en la tabla de vista previa privada y se revisa antes
  de su publicación. Los directorios temporales se limpian al terminar.
- Si el módulo `pyogrio`, `geopandas` o `shapely` falta, falla cerrado
  **antes** de reclamar una importación. Las dependencias del worker deben
  instalarse en su entorno aislado y auditarse allí.

La limitación de recursos en `preexec_fn` se aplica al proceso Python hijo
y NO sustituye límites de memoria/contenedor, timeouts de infraestructura,
aislamiento de red externo, ni supervisión.

## Próximos bloqueadores operativos

1. Provisionar staging: PostGIS migrado a `dbi_0026_gpkg_layer_choice`,
   bucket S3 verdaderamente privado con compatibilidad HEAD/GET/PUT/tags.
2. Empaquetar backend DBI + bibliotecas geoespaciales en imagen exclusiva
   del worker, probar Pyogrio/GDAL del proveedor exacto.
3. Crear el proceso/cron y supervisión de Render sin instalar worker dentro
   de FastAPI; configurar alertas para importaciones `failed`/estancadas.
4. Probar GPKG/SHP reales de QGIS y la secuencia `received → prepared →
   published` con cuentas de gestor y cliente diferentes, además de cruces
   tenant/plot, reintento e interrupción/reinicio.
5. Validar cuotas, tráfico/CORS, límites de proxy 30 MiB, costos mensuales,
   limpieza de archivos huérfanos y estrategia de recuperación ante fallos.

No se ha desplegado este ejecutor ni se ha comprobado el servidor real.
No se modifica GOLD, segmentación ni el pipeline Density.


> **Nota operativa (microhito E1):** la referencia de revisión DBI 26 es
> requisito del **código**, no comprobación de una base staging real.
> El controlador de migraciones conectado actual **bloquea staging**;
> no se autoriza aplicar Alembic directamente. Ver
> [gate offline y bloqueos](59_DBI_GIS_STAGING_OFFLINE_READINESS.md).
