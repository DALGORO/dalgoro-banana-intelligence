# H14 / 2H-2D/3B — Prueba HTTP real de S3 multipart con MinIO descartable

## Propósito
Este incremento **no modifica endpoints, modelos SQL ni el sistema de carga**. Añade una prueba de integración reproducible que ejecuta el `DBIS3MultipartAdapter` de DALGORO contra una instancia MinIO local efímera, dentro de GitHub Actions. Supera la limitación de las pruebas de dobles de H14/2H-2D/2 y /3A para comprobar de forma real la interoperabilidad del contrato multipart S3.

**Dependencias:** #259 → #262 → #263 → #264 → #265 → #266 → #267 → #268 → esta etapa. No fusionar fuera de orden.

## Aislamiento
- Nuevo job de CI `H14 · MinIO real local sin grants` que inicia un contenedor MinIO **exclusivamente en un runner efímero**, con puerto publicado solo en `127.0.0.1:9000`, sin volúmenes con datos reales y con permisos del contenedor reducidos. Dado que el repositorio de imagen oficial retiró el acceso y su servidor de binarios responde 410, se utiliza una **imagen de terceros solo para CI** (`tobi312/minio`) fijada por el digest OCI completo `sha256:e2226dea4b9aef896db02f7396102d48eb58cd339d930332e3d8bdac80012a78`. Fijar un digest evita cambios de imagen entre ejecuciones, pero NO implica aval institucional ni garantía de equivalencia con un binario oficial verificado; queda prohibido usar ese proveedor en producción.
- Credenciales **sintéticas y exclusivas del runner**, nunca reutilizables en Render o para datos reales. Bucket `dbi-h14-test-<UUID aleatorio>` creado por prueba y eliminado al terminar.
- El script exige `DBI_MINIO_E2E_ENABLED=1` y valida que el endpoint HTTP sea loopback. Sin ese opt-in, **falla**, no hace llamadas S3.
- Mantiene intactos flags operativos `DBI_SCIENTIFIC_RASTER_PROVIDER_START_ENABLED` y `DBI_SCIENTIFIC_RASTER_RECONCILIATION_ENABLED`; no se activan ni se configura la API de clientes.

## Contratos comprobados
Con el cliente boto3 real, la prueba:
1. Crea un bucket aislado, prepara un plan técnico declarado de 128 MiB (dos partes de 64 MiB) **sin enviar bytes** y comprueba que el inventario inicial esté vacío.
2. Inicia una carga multipart real mediante el adaptador S3 con `SHA256/COMPOSITE` de **transporte** y verifica que la enumeración por clave exacta devuelve la referencia esperada.
3. Inicia una segunda carga remota para la misma clave, comprueba que aparezca como inesperada, y añade otra carga con prefijo de nombre similar para confirmar **aislamiento de clave exacta**.
4. Aborta únicamente la referencia registrada y observa que la inesperada permanece; después aborta todas las incompletas de **esa clave exacta** y verifica que la carga vecina no se borró.
5. Asegura que no se formó ningún objeto TIFF, ninguna parte y ningún grant; limpia las cargas y el bucket exclusivamente de pruebas.

La prueba valida la interoperabilidad del *inicio/inventario/aborto* en el proveedor MinIO elegido. **No** autoriza transferencias, no comprueba SHA-256 completo de TIFF, no demuestra reanudación ni ensaya la actualización SQL integrada con MinIO.

## Reglas de aceptación
El job debe fallar cuando MinIO no inicie, rechace el contrato `ChecksumType=COMPOSITE`, falle al listar/abortar o el conteo S3 sea incorrecto. **No sustituir** las cabeceras SHA256 por MD5 o modo sin checksum para conseguir un verde artificial. Ante incompatibilidad real del proveedor, documentar el bloqueo y mantener los grants inhabilitados.

## Limitaciones
La prueba se ejecuta con datos sintéticos; no toca campañas ni almacenamiento DALGORO. Los intentos previos fallaron por distribución: Docker Hub denegó el acceso a `minio/minio` y `dl.min.io` devolvió HTTP 410. Se documenta explícitamente la dependencia actual de un contenedor de terceros fijado por digest y su **uso exclusivamente en pruebas descartables sin secretos**. Si tampoco está disponible, el trabajo debe fallar (no saltar pruebas ni degradar el algoritmo SHA256). En una etapa posterior se requieren pruebas reales de pérdida de conexión, retorno S3 desconocido, concurrencia de aprobación/limpieza y recuperación S3↔SQL antes de que una carga científica se considere segura para clientes.

**Sin migraciones, despliegue Render, publicación institucional, cambios de UI ni permisos de subida.**
