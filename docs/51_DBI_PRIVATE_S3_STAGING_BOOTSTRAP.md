# DBI-PORTAL-GIS-005A · Preparación S3 privada (configuración opt-in)

## Objetivo y estado

En el código del portal DBI, la selección del almacén privado puede apuntar al
adaptador `DBIS3ObjectStore` **solo** si el administrador establece
`DBI_STORAGE_BACKEND=s3`. La selección es compatible con producción y staging,
pero **no constituye un despliegue real ni acredita por sí sola compatibilidad
con el proveedor S3 elegido**. Hasta completar las pruebas de proveedor y la
activación de un worker GIS separado, no se debe ofertar una carga productiva
de SHP/GPKG como completamente automatizada.

### Variables de entorno privadas (Render/backend)

| Nombre | Valor permitido |
|---|---|
| `DBI_ENVIRONMENT` | `staging` o `production` |
| `DBI_DATABASE_URL` | URL Postgres DBI del entorno correspondiente, gestionada como secreto |
| `DBI_STORAGE_BACKEND` | `s3` (opt-in explícito) |
| `DBI_S3_ENDPOINT_URL` | Origen HTTPS S3-compatible, sin path ni credenciales incrustadas |
| `DBI_S3_BUCKET` | Bucket privado reservado a DBI |
| `DBI_S3_REGION` | Región exacta del proveedor |
| `DBI_S3_ACCESS_KEY_ID` | Identificador de acceso del principal DBI, secreto de Render |
| `DBI_S3_SECRET_ACCESS_KEY` | Clave del principal DBI, secreto de Render |
| `DBI_S3_SESSION_TOKEN` | Token temporal opcional, secreto de Render |

**No introducir valores reales de estas variables en GitHub, documentos,
screenshot, logs ni el navegador.** El adaptador exige TLS verificado y
limita cada objeto a 64 MiB. El endpoint debe soportar la semántica del
adaptador (incluida escritura condicional `If-None-Match: *`, etiquetas del
objeto, metadatos SHA y permisos para inspección/lectura/escritura/retiro). No
asumir que todos los proveedores compatibles funcionan idénticamente.

## Activación gradual

1. **No activar en producción aún**. Preparar un bucket privado específico y
   política IAM de mínimo privilegio, sin ACL pública ni publicación web.
2. Probar desde una instancia staging con PostGIS DBI migrado hasta
   `dbi_0024_gis_approval`, usando un tenant y finca de prueba. Comprobar
   GET/PUT, tags, `head_object`, checksum SHA-256, rangos y `retire` con
   objetos sintéticos; validar los grants temporales para el navegador.
3. Configurar el mismo endpoint/bucket lógico con credenciales **diferentes
   y de mínimo privilegio** para el futuro worker GIS. La identidad y rutas
   del objeto derivan del tenant, no de nombres de usuario o archivos.
4. Habilitar el worker de procesamiento geoespacial como servicio separado,
   con colas, tiempo/memoria acotados, observabilidad y cuotas. No ejecutar
   GDAL dentro del proceso HTTP de FastAPI.
5. Realizar UAT completo: subida original privada → estado `received` →
   `prepared` → revisión cartográfica → aprobación `published` → lectura
   desde cuenta cliente del lote correcto, y denegación de acceso cruzado.

El despliegue web **sin** `DBI_STORAGE_BACKEND=s3` no inicializa storage
privado en staging/producción: los endpoints que necesitan objetos responden
no disponible en lugar de escribir en un disco efímero. La ruta local conserva
el comportamiento de desarrollo. Si el entorno intenta mezclar S3 y
`DBI_LOCAL_STORAGE_ROOT`, se rechaza la configuración en arranque.

## Costos y controles por verificar

- S3: capacidad de almacenamiento, operaciones PUT/GET/HEAD/TAG, egreso
  y retención de los archivos originales; revisar costos del proveedor real.
- Render: servicio web y segundo servicio worker siempre encendido o job
  programado (según plan disponible), RAM y CPU para Pyogrio/GDAL,
  almacenamiento temporal para ZIP expandido, tráfico privado hacia PostGIS/S3.
- Revisión: límite de archivo de 30 MiB en frontend/backend, límites de
  reverse proxy y CDN, limpiezas de objetos huérfanos, revocación/rotación
  de credenciales, alertas ante fallos y acumulación de tareas.

**Esta fase solo agrega el enlace de configuración y su prueba offline**:
ninguna migración se aplica en Render, ningún bucket se crea, ni se confirma
que existe un worker de producción.

## Archivos de esta fase

- `apps/platform-web/backend/app/dbi/storage_bootstrap.py`:
  política explícita de selección; nunca revela secretos.
- `apps/platform-web/backend/app/main.py`: montaje en lifespan del backend
  de objetos privados, con renderer local preservado.
- `.github/scripts/ci_dbi_s3_bootstrap.py`: seguridad, compatibilidad
  legacy/offline y cierre correcto del runtime.
