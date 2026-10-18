# H14 / 2H-2D/3B — Prueba HTTP real de S3 multipart con MinIO descartable

## Propósito
Este incremento **no modifica endpoints, modelos SQL ni el sistema de carga**. Añade una prueba de integración reproducible que ejecuta el `DBIS3MultipartAdapter` de DALGORO contra una instancia MinIO local efímera, dentro de GitHub Actions. Supera la limitación de las pruebas de dobles de H14/2H-2D/2 y /3A para comprobar de forma real la interoperabilidad del contrato multipart S3.

**Dependencias:** #259 → #262 → #263 → #264 → #265 → #266 → #267 → #268 → esta etapa. No fusionar fuera de orden.

## Aislamiento
- Nuevo job de CI `H14 · MinIO real local sin grants` que inicia un **binario oficial de MinIO en el runner descartable**, con listener exclusivo `127.0.0.1:9000`. Se descarga de `dl.min.io` la versión `RELEASE.2025-09-07T16-13-09Z` y se comprueba el SHA-256 del binario frente al archivo de checksum servido por el origen oficial (ambos bajo HTTPS). No se usa ninguna imagen Docker de tercero.
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
La prueba se ejecuta con datos sintéticos; no toca campañas ni almacenamiento DALGORO. El sitio oficial de descargas MinIO es una dependencia externa de CI: si el binario o su checksum no están disponibles, el job **falla cerrado**. La primera ejecución comprobó que la imagen oficial Docker ya no podía descargarse y se sustituyó únicamente el modo de instalación de la prueba. En una etapa posterior se requieren pruebas reales de pérdida de conexión, retorno S3 desconocido, concurrencia de aprobación/limpieza y recuperación S3↔SQL antes de que una carga científica se considere segura para clientes.

**Sin migraciones, despliegue Render, publicación institucional, cambios de UI ni permisos de subida.**
