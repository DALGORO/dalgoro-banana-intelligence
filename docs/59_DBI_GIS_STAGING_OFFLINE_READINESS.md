# DBI-PORTAL-GIS-008A · Staging: inventario de bloqueos y gate offline

## Alcance de este microhito E1

El circuito GeoPackage multicapa (A–D) está fusionado, pero el código y sus
tests **NO** demuestran que exista un staging operativo. Este microhito
introduce un gate **exclusivamente offline** de configuración y grafo de
migraciones. No ejecuta SQL, no crea conexiones, clientes S3, buckets,
workers, cron jobs, objetos, migraciones ni importaciones, y no modifica
los permisos de despliegue existentes.

### Comando para el operador (entorno aislado, con secretos fuera de GitHub)

Con variables **reales solamente en el gestor de secretos del ambiente
controlado**, y el worker aún desactivado, ejecutar:

```bash
python services/banana-density/portal_gis_staging_readiness.py --offline
```

Antes: instalar el entorno GIS aislado con
`services/banana-density/requirements-gis-worker.txt` y dependencias de
backend requeridas por el preflight existente. El script reutiliza
`portal_gis_prepare_s3.preflight()` sin conectarse a S3 o PostGIS. Solo
acepta `DBI_ENVIRONMENT=staging` y
`DBI_GIS_WORKER_ENABLED` ausente o `0`. Conserva los requisitos de
`DBI_DATABASE_URL`, proveedor S3 HTTPS, credenciales, tenant y workspace
Linux privado 0700. No imprime estos valores ni los detalles de
excepciones que pudieran incluir secretos.

El gate inspecciona estáticamente `dbi_alembic/versions`, exige un
único linaje íntegro que **incluya**
`dbi_0026_gpkg_layer_choice` y emite su revisión HEAD **del código**.
No consulta `alembic_version_dbi` de ninguna base de datos.

- Exit code **0**: únicamente configuración offline aceptada; respuesta
  `offline_configuration=validated` y
  `deployment_readiness=NOT_VERIFIED`.
- Exit code **2**: configuración o grafo inválido; mensaje JSON redactado,
  sin URL, token, host, secreto, tenant ni rutas privadas.
- La respuesta enumera los gates no comprobados; nunca dice `READY`.
  No existe opción `--once`, ni modo de aplicar migraciones.

## Bloqueos reales antes de una prueba staging

| Comprobación | Evidencia actual | Estado |
|---|---|---|
| Código integrado y CI | PR #192–#195 y tests offline/efímeros | Aprobado en CI |
| Migraciones de código | Alembic incluye DBI 26 (selección multicapa) | Versionado; **no verificado en staging** |
| Aplicación/verificación remota staging | `migration_cli` permite operaciones conectadas solo en desarrollo local/test efímero; no staging | **Bloqueado por política actual** |
| Base/roles PostGIS staging | Sin conectividad/roles ni revisión comprobados | No verificado |
| Bucket S3 privado e IAM | Adaptador y prueba efímera no confirman proveedor/tenant real | No verificado |
| Render: web y worker aislados | Sin manifiesto `render.yaml` ni evidencia de servicio/scheduler GIS | No verificado |
| Archivo real de QGIS | Sin UAT con fuente real consentida ni gestores/clientes aislados | No verificado |

**No sortear** las barreras de `migration_cli` con
`alembic upgrade` manual, SSH, `stamp`, SQL ad hoc, forzando
`DBI_ENVIRONMENT=test` contra staging, o reusando credenciales de
producción. Antes de operar staging hace falta diseñar y aprobar una
ruta de migraciones explícitamente autorizada para ese ambiente en otro
microhito con revisión de riesgo, mínimos privilegios, backup y rollback.

## Secuencia autorizable posterior (aún NO realizada)

1. Decidir infraestructura y costos staging (PostGIS, bucket S3 privado,
   trabajador geoespacial Linux separado de FastAPI, IAM mínimo,
   límites de CPU/RAM y temporales 0700).
2. Aprobar ruta controlada de migraciones staging; respaldar y verificar
   revisión DBI 26 o posterior desde un usuario migrador limitado.
3. Validar conexiones y operaciones reales S3 HEAD/PUT/GET/tags, huella SHA,
   permisos cross-tenant y retiro con objetos sintéticos.
4. Validar worker instalado, capacidad, timeouts, red, logs redactados y
   ejecución `--check` antes de habilitar `--once` supervisado.
5. Ejecutar UAT autorizado: GPKG real con dos capas, escoger solo una,
   worker un paso, preview MANAGE, aprobación manual y lectura READ
   scoped; documentar rechazos de acceso cruzado y reintentos.
6. Recién después evaluar lanzamiento productivo, monitoreo y presupuestos.

## CI

`.github/scripts/ci_dbi_gis_staging_readiness.py` prueba con valores
**sintéticos**: sin sockets, prohibición de production/worker activado,
secretos redactados, raíz insegura, base incorrecta y grafo de migraciones
ausente, bifurcado o cíclico. Se ejecuta dentro de `CI modular`.

No implica acceso a Render ni a cuentas, servidores, S3 o PostgreSQL
reales. Este microhito E1 documenta los bloqueos, no los elimina.
