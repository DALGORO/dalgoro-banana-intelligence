# DBI GIS · entorno mínimo reproducible y workspace privado

Complemento del ejecutor S3 one-shot ya incorporado en `docs/52_DBI_GIS_S3_ONE_SHOT_WORKER.md`.

## Instalación aislada

El archivo `services/banana-density/requirements-gis-worker.txt` define una instalación pequeña para el worker de conversión y control DBI: S3/Boto3, SQLAlchemy/Psycopg y el stack geoespacial Geopandas/Pyogrio/Shapely. No instala Torch, YOLO ni el servicio FastAPI HTTP.

En el entorno aislado del worker, y con las fuentes del repositorio correspondientes:

```bash
python -m pip install -r services/banana-density/requirements-gis-worker.txt
python -m pip check
python services/banana-density/portal_gis_prepare_s3.py --check
```

El comando `--check` valida configuración sin procesar un original. El comando `--once` permanece sujeto al interruptor `DBI_GIS_WORKER_ENABLED=1`, credenciales privadas, tenant explícito, base DBI y proveedor S3, además de la supervisión operativa externa.

## Seguridad del espacio temporal

El worker requiere `DBI_GIS_WORKER_ROOT` absoluto, distinto del repositorio y de los objetos privados, y ahora comprueba que una carpeta existente:

- Sea un directorio real, no un enlace simbólico.
- Pertenezca al usuario Linux que ejecuta el proceso.
- No conceda ningún permiso a grupo u otros usuarios (modo `0700` o más restrictivo).

Comprueba nuevamente los permisos **después de crear la carpeta**, antes de consultar la base de datos o descargar un archivo privado. Una carpeta `0755`, `0777`, externa o vinculada mediante symlink ocasiona una denegación clara. Nunca se corrigen permisos ajenos silenciosamente.

## Verificación automatizada

El job independiente `GIS · instalación mínima S3/PostGIS y conversión controlada` de `.github/workflows/ci.yml` instala solo el requirements mínimo, comprueba las dependencias, ejecuta el test offline del worker con credenciales sintéticas y convierte un SHP ZIP y un GPKG sintéticos. Esto valida reproducibilidad del código, **no** conectividad real a S3 ni despliegue en Render.

Sigue pendiente configurar el worker externo, permisos IAM, secreto/proveedor S3 real, migraciones PostGIS del ambiente y UAT con cuenta gestora y cliente, además de los límites de red, tiempo y memoria del servicio.
