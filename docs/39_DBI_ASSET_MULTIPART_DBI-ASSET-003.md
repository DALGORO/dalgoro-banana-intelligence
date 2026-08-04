# DBI-ASSET-003 — Ingesta multipartes y preservación de maestros grandes

Estado: implementación por bloques en PR Draft  
Issue: #55  
Hito: #30  
Base: `main@122394f0450abc5f00700a94a8acc528550d3aaf`

## 1. Propósito

Este ticket extiende la ingestión privada de DBI para ortofotos maestras y otros
activos grandes, con un rango operativo esperado de 1–10 GB. El binario se
transfiere directamente entre el cliente autorizado y el almacenamiento de
objetos; la API coordina identidad, política, grants efímeros y evidencia, pero
nunca recibe ni mantiene gigabytes en memoria.

El original se conserva privado e inmutable. DBI-ASSET-003 no genera COG,
overviews ni teselas y no implementa cola, worker, procesamiento geoespacial o
frontend.

## 2. Decisiones invariantes

1. Ningún activo se oculta o descarta por superar un límite.
2. El activo principal continúa usando los estados de DBI-ASSET-002:
   `registered`, `verified`, `quarantined` y `retired`.
3. Los estados transitorios de transporte pertenecen a una sesión multipartes
   separada.
4. Completar multipartes no convierte automáticamente un activo en
   `verified`.
5. El ETag multipartes no se interpreta como hash del contenido.
6. Un SHA-256 compuesto por partes no se interpreta como el SHA-256 canónico del
   archivo completo.
7. Las URLs firmadas y sus headers son efímeros y no se persisten.
8. La API no abre, retransmite ni calcula el hash del objeto grande.
9. El flujo existente de hasta 64 MiB permanece compatible.
10. Limpiar una carga incompleta nunca elimina un original completado.

## 3. Fronteras del flujo

```text
cliente autorizado
  | metadata, inicio, partes, finalización
  v
API DBI
  | grants efímeros y operaciones de control
  v
almacenamiento privado

cliente autorizado ------------------> almacenamiento privado
                         binario directo
```

La API recibe solamente solicitudes acotadas: identificadores, números de parte,
tamaños, checksums, ETags devueltos por el proveedor y claves de idempotencia. El
binario de cada parte no atraviesa el proceso web.

## 4. Estados

### 4.1 Activo

El `AnalysisInputAsset` permanece `registered` durante la carga y después de
completar el transporte hasta que exista evidencia válida del SHA-256 canónico
del archivo completo.

Solo el mecanismo de verificación autorizada puede promoverlo a `verified`.
Cuarentena y retiro continúan bajo los contratos de DBI-ASSET-002.

### 4.2 Sesión multipartes

Estados propuestos:

- `initiated`: proveedor y política aceptaron una sesión durable.
- `uploading`: existe al menos una parte observada o concedida.
- `completed_pending_content_verification`: el objeto fue ensamblado y la
  integridad de transporte fue comprobada; falta verificar el SHA-256 canónico.
- `aborted`: aborto solicitado y confirmado.
- `expired`: venció la sesión y se confirmó la limpieza de partes.
- `blocked_by_policy`: el activo es visible, pero el tamaño o tipo excede la
  configuración operativa.

No hay transición desde un terminal hacia `uploading`. Un reintento exacto de
inicio, finalización o aborto devuelve la misma evidencia sin repetir el efecto.

## 5. Integridad

### 5.1 Integridad declarada

El registro conserva:

- tamaño total declarado;
- MIME canónico;
- SHA-256 canónico declarado del archivo completo;
- identidad del tenant, finca, lote y activo;
- clave privada derivada por política.

### 5.2 Integridad por parte

Cada parte registra de forma acotada:

- número de parte;
- tamaño;
- checksum exigido por el proveedor;
- ETag o referencia opaca devuelta;
- fecha de observación;
- identidad de la sesión.

Antes de completar se exige una secuencia contigua, sin duplicados, con suma de
tamaños exacta. La última parte puede ser menor; las demás respetan la política
mínima del proveedor.

### 5.3 Integridad de transporte

La finalización exige que el proveedor confirme el objeto ensamblado, el tamaño,
la identidad privada y el checksum configurado. Para S3 se usarán checksums
soportados explícitamente por la operación multipartes. Cuando se utilice
SHA-256 multipartes, su tipo será `COMPOSITE` y se conservará como evidencia
de transporte, no como hash íntegro.

Los checksums CRC de objeto completo pueden confirmar la reconstrucción del
transporte, pero no reemplazan el SHA-256 canónico declarado por DBI.

### 5.4 Verificación canónica pendiente

Si el proveedor no entrega un checksum criptográfico de objeto completo
demostrablemente equivalente al SHA-256 declarado, la sesión termina en
`completed_pending_content_verification` y el activo sigue `registered`.

Una capacidad posterior autorizada podrá verificar el contenido mediante lectura
streaming fuera del proceso web o mediante una operación del proveedor que
calcule el SHA-256 completo en reposo. Este ticket deja la evidencia durable y no
anticipa worker o cola.

## 6. Política operativa inicial

| Parámetro | Valor inicial | Regla |
|---|---:|---|
| Flujo síncrono existente | hasta 64 MiB | DBI-ASSET-002 |
| Multipartes | más de 64 MiB | DBI-ASSET-003 |
| Máximo operativo por objeto | 20 GiB | configurable |
| Tamaño de parte | 64 MiB | configurable y validado |
| Partes para 10 GiB | 160 | aproximado |
| Partes para 20 GiB | 320 | aproximado |
| Concurrencia recomendada del cliente | 4 | configurable |
| Ventana de grants | máximo 8 partes | emisión bajo demanda |
| TTL de grant | 15 minutos | dentro de la política actual de 30 s–1 h |

El máximo de 20 GiB es una configuración de operación, no una restricción del
modelo de dominio. Un exceso crea o reutiliza el activo y registra
`blocked_by_policy` con código de motivo; no realiza una carga ni oculta el
registro.

## 7. Persistencia propuesta

### 7.1 Sesión

Una tabla versionada de sesiones debe contener como mínimo:

- UUID de sesión;
- tenant y activo;
- estado y código de motivo;
- referencia interna del proveedor, nunca expuesta por la API;
- tamaño total, tamaño de parte y cantidad esperada;
- algoritmo y tipo de checksum de transporte;
- clave de idempotencia normalizada o su huella;
- versión para concurrencia;
- fechas de creación, actividad, expiración, finalización y aborto;
- actor que inició la operación.

La referencia del proveedor no se incluirá en `repr`, respuestas, logs,
métricas o errores. No concede acceso por sí sola y permanece restringida a la
capa de almacenamiento.

La persistencia implementada usa `dbi_asset_multipart_sessions` y
`dbi_asset_multipart_parts`. Las claves foráneas compuestas obligan a que activo,
sesión y partes compartan el mismo tenant. Una restricción única parcial permite
solo una sesión `initiated` o `uploading` por activo y tenant.

La fila `initiated` puede existir antes de recibir la referencia del proveedor;
esto evita cargas remotas sin rastro local. Si el inicio remoto no concluye, la
sesión aún puede pasar de forma durable a `aborted` o `expired`. Toda sesión
activa exige fecha de expiración y las huellas de idempotencia son SHA-256, nunca
la clave original.

### 7.2 Partes

Una tabla hija registra una fila por número de parte. La combinación
`(session_id, part_number)` es única. Un reintento con el mismo tamaño y
checksum es idempotente; cualquier divergencia es conflicto.

### 7.3 Manifiesto de vuelo

Las fotografías fuente y archivos auxiliares se representan como objetos
individuales relacionados por un manifiesto lógico
`flight-source-bundle.v1`. El manifiesto incluye identidad estable, nombre
lógico, tamaño, MIME, SHA-256, sensor/cámara y fecha de captura cuando existan,
más las relaciones autorizadas con finca, lote, vuelo y ortofoto maestra.

No se obliga a crear un ZIP único. Un paquete de descarga futuro será un derivado,
no la única copia.

## 8. Operaciones de aplicación previstas

1. `initiate`: autoriza, valida política, crea o recupera la sesión idempotente
   e inicia multipartes en el proveedor.
2. `grant_parts`: emite una ventana acotada de autorizaciones efímeras para
   números concretos.
3. `record_part`: registra evidencia devuelta después de cargar cada parte.
4. `complete`: bloquea la sesión, compara la lista exacta, completa una vez,
   consulta metadata final y persiste evidencia.
5. `abort`: aborta de forma idempotente y confirma que no quedan partes.
6. `expire_cleanup`: selecciona sesiones vencidas, reclama un lote acotado,
   aborta y registra resultado recuperable.
7. `inspect`: devuelve estado y progreso sin URLs, secretos o referencias
   internas del proveedor.

## 9. Concurrencia e idempotencia

- Inicio: una clave de idempotencia no puede vincularse a dos solicitudes
  diferentes.
- Parte: el mismo número acepta solo evidencia exacta.
- Finalización: una sola transición posee el efecto; los reintentos leen el
  resultado durable.
- Aborto contra finalización: bloqueo transaccional o versión optimista decide
  una única salida.
- Limpieza: usa reclamación por lote y puede reintentarse después de fallos.
- El proveedor se consulta después de un resultado incierto antes de repetir una
  operación irreversible.

## 10. Seguridad multiusuario

Toda operación vuelve a autorizar tenant, organización, finca y lote. Los IDs de
sesión no otorgan autoridad. No se aceptan object keys, bucket, endpoint, upload
ID o URL enviados por el cliente.

Los grants se emiten para una parte, sesión, objeto, método, tamaño y checksum
concretos. Se entregan en respuesta y no se escriben en base de datos. Los
mensajes de error usan códigos estables sin revelar infraestructura.

La cantidad de grants simultáneos y la concurrencia del cliente se mantienen
acotadas para evitar presión de memoria, conexiones y costos cuando muchas
personas carguen ortofotos a la vez.

## 11. Recuperación y costos

Las partes incompletas generan almacenamiento facturable hasta abortarse. Se
requieren:

- expiración explícita de sesión;
- limpieza periódica y reintentable;
- política de ciclo de vida del bucket como defensa adicional;
- métricas de sesiones, bytes, partes, reintentos, conflictos, expiraciones,
  abortos y residuos;
- alarma si existen cargas vencidas sin limpiar;
- ninguna descarga completa desde la API.

La limpieza automática de DBI-ASSET-002 continúa separada de la limpieza de
partes multipartes.

## 12. Orden de implementación

1. [x] Contratos puros y política multipartes.
2. [x] Pruebas offline de límites, estados e idempotencia.
3. [x] Migración y modelos de sesión/partes.
4. [x] Repositorio y servicio de aplicación.
5. [ ] Puerto proveedor-neutral y adaptador S3-compatible no productivo.
6. [ ] API autorizada sin binario.
7. [ ] Aborto, expiración y limpieza.
8. [ ] Manifiesto de fuentes del vuelo.
9. [ ] Integración S3 efímera, métricas y documentación final.
10. [ ] Auditoría de CI sobre el SHA final.

No se inicia DBI-JOB-003 hasta fusionar y cerrar este ticket.

### Bloque de repositorio y servicio de aplicación

El repositorio prepara la sesión dentro de la transacción externa y nunca hace
`commit`, `rollback` o llamadas al almacenamiento. Primero bloquea el activo con
el ámbito exacto de tenant, finca y lote; después inserta la sesión con
`ON CONFLICT DO NOTHING`. Un reintento concurrente solo reutiliza la sesión si
la huella idempotente, el activo, el plan, el actor y los parámetros persistidos
coinciden exactamente.

El servicio autoriza escritura antes de consultar el activo, usa exclusivamente
la metadata durable para decidir entre flujo síncrono, multipartes o bloqueo por
política, y crea sesiones activas con expiración inicial de 24 horas. Los activos
de hasta 64 MiB continúan por DBI-ASSET-002 sin crear una sesión multipartes. Un
exceso de 20 GiB sí conserva una sesión `blocked_by_policy` con motivo visible.

Las vistas de aplicación excluyen la clave idempotente original, su huella
persistida, la referencia interna del proveedor, URLs y credenciales. Este bloque
no registra partes, no completa ni aborta cargas y no anticipa el puerto del
proveedor o la API.

## 13. Referencias oficiales

- Amazon S3 multipart upload limits:
  https://docs.aws.amazon.com/AmazonS3/latest/userguide/qfacts.html
- Multipart upload overview:
  https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html
- Checking object integrity for uploads:
  https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html
- CompleteMultipartUpload API:
  https://docs.aws.amazon.com/AmazonS3/latest/API/API_CompleteMultipartUpload.html
