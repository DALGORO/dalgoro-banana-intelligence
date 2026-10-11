# DBI · Selección explícita del almacén privado S3 (sin activar producción)

## Propósito

El backend ya dispone de un adaptador para almacenes privados S3 compatibles. Esta mejora conecta ese adaptador al ciclo de vida de FastAPI **solamente si el operador lo selecciona expresamente**. No instala S3 en Render, no crea buckets, no introduce claves en el repositorio y no arranca aún un worker GIS de producción.

## Variables (en secretos del entorno, no en archivos Git)

| Variable | Uso |
|---|---|
| `DBI_STORAGE_PROVIDER` | `s3` para activar S3; vacío preserva el comportamiento previo; `disabled` apaga storage; `local` es solo desarrollo |
| `DBI_ENVIRONMENT` | `staging` o `production` para un servicio remoto HTTPS |
| `DBI_DATABASE_URL` | Base DBI específica del entorno; jamás la base heredada |
| `DBI_S3_ENDPOINT_URL` | URL del origen HTTPS S3 compatible |
| `DBI_S3_BUCKET` | Bucket privado dedicado y sin ACL pública |
| `DBI_S3_REGION` | Región declarada del proveedor |
| `DBI_S3_ACCESS_KEY_ID` | Clave de servicio con privilegios mínimos |
| `DBI_S3_SECRET_ACCESS_KEY` | Secreto del servicio, no imprimir en logs |
| `DBI_S3_SESSION_TOKEN` | Opcional, solo cuando el proveedor entrega token temporal |

### Garantías

- Configuración S3 incompleta o no autorizada: el arranque falla cerrado, sin cambiar silenciosamente a archivos locales.
- En staging y producción se exige endpoint HTTPS con verificación TLS; se rechazan URL con usuario, contraseña, query o fragmento.
- S3 se monta en `application.state.dbi_object_store` para los endpoints actuales; no se duplica el transporte de archivos.
- Cuando el proveedor es S3 no se intenta iniciar el renderer local de ortofotos.
- Ante un fallo de inicialización se libera el runtime DBI.
- Sin `DBI_STORAGE_PROVIDER` se conserva el arranque local existente, sin migrar carpetas ni datos.

## Pasos operativos pendientes antes del despliegue real

1. Elegir proveedor y crear bucket *privado* con cifrado, versionado y ciclo de vida adecuado. Estimar costo de almacenamiento, tráfico y llamadas API.
2. Limitar IAM a ese bucket/namespace, verificar permisos reales de escritura condicional, lecturas de rango, tags, y URLs firmadas.
3. Configurar secretos en Render y validar políticas CORS solo para el origen autorizado del portal (sin origen `*`).
4. Hacer pruebas reales del adaptador S3 con el proveedor escogido, incluidas fallas, integridad SHA, 30 MiB y acceso entre tenants.
5. Desplegar un worker GIS separado (Pyogrio/GDAL/GEOS), con base DBI compartida y credenciales privadas de menor privilegio, límites CPU/RAM y monitoreo.
6. Ejecutar migrations DBI controladas hasta `dbi_0024_gis_approval`, y realizar UAT con archivos QGIS reales (GPKG/SHP), revisión MANAGE y lectura desde sesión de cliente autorizada.

**No declarar este portal listo para producción solamente por fusionar este cambio.** La persistencia real aún depende de infraestructura y credenciales externas que no están disponibles en CI offline. No se modifica GOLD ni el análisis científico.
