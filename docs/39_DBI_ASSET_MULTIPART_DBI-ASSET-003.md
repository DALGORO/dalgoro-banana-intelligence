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
5. [x] Puerto proveedor-neutral y adaptador S3-compatible no productivo.
6. [x] API autorizada sin binario.
7. [x] Aborto, expiración y limpieza.
8. [x] Manifiesto de fuentes del vuelo.
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

### Bloque de puerto proveedor-neutral y adaptador S3-compatible

El puerto puro define contratos para iniciar una carga, emitir acceso temporal a
una parte exacta, completar el conjunto esperado e inspeccionar el objeto ya
ensamblado. Sus tipos no conocen SDKs, endpoints, buckets, credenciales, base de
datos ni HTTP. La política del puerto exige que metadata, plan, sesión, tamaños,
checksums y ventana temporal coincidan antes de invocar al proveedor.

El adaptador S3-compatible de este bloque solo acepta endpoints loopback y usa la
configuración explícita del proveedor de DBI-STORAGE. Inicia la carga con metadata
privada, genera acceso firmado para el `UploadId`, número, tamaño y checksum
exactos de cada parte, y completa únicamente el manifiesto íntegro esperado. Una
repetición posterior a una finalización exitosa inspecciona el objeto ensamblado
en vez de duplicarlo.

`UploadId`, URLs, cabeceras, ETags y checksums de transporte quedan fuera de
representaciones públicas; los grants resueltos viven solo en memoria y expiran.
La finalización confirma tamaño, tipo de contenido, metadata y checksum del
transporte, pero no promueve el activo a `verified`: el SHA-256 canónico del
archivo completo sigue pendiente del flujo autorizado de DBI-ASSET-002.

Este bloque permanece offline y no incorpora API, descarga binaria, credenciales
de entorno, persistencia adicional, aborto ni limpieza. Esas operaciones se
implementan en los pasos posteriores del orden aprobado.

### Bloque de API autorizada sin binario

La API multipartes incorpora cinco operaciones de metadata bajo
`/api/v1/dbi/assets/{asset_id}/multipart`: iniciar, emitir grants por ventana,
registrar evidencia de una parte, completar e inspeccionar. Todas vuelven a
autorizar tenant, organización, finca y lote antes de consultar la sesión. Un
identificador de activo o sesión nunca concede autoridad ni permite enumeración
transversal.

El inicio reutiliza la preparación idempotente y solo llama al proveedor cuando
la ruta durable es `multipart`. Los activos pequeños conservan la ruta síncrona y
los excesos de política siguen visibles como `blocked_by_policy`. La referencia
del proveedor se vincula internamente y la sesión transita a `uploading`; nunca se
devuelve al cliente.

Los grants aceptan únicamente número y checksum de partes dentro de la ventana
durable. El tamaño se deriva del plan guardado, y la respuesta efímera contiene
solo método `PUT`, URL, headers y expiración. Registrar una parte persiste tamaño,
checksum y ETag exactos de forma idempotente. Completar exige el conjunto íntegro
de partes, confirma metadata e integridad de transporte con el proveedor y deja
el activo en `registered` con la sesión
`completed_pending_content_verification`.

La inspección devuelve estado, límites y progreso sin claves idempotentes,
huellas, URLs, checksums, ETags o referencias remotas. Ningún endpoint acepta
bucket, endpoint, object key, upload ID, archivo, stream o cuerpo binario. La
transacción HTTP hace `commit` o `rollback`; repositorio, servicio y adaptador
continúan sin controlar la unidad de trabajo.

El proveedor se inyecta desde la configuración del despliegue y, en este bloque,
solo existe el adaptador S3-compatible loopback no productivo. Todavía no se
habilitan proveedor productivo, datos reales, descarga, frontend, cola o worker.

### Bloque de aborto, expiración y limpieza

La API incorpora una sexta operación autorizada,
`POST /api/v1/dbi/assets/{asset_id}/multipart/{session_id}/abort`. El servicio
vuelve a autorizar tenant, organización, finca y lote antes de bloquear la
sesión. Solo `initiated` y `uploading` pueden pasar a `aborted`; una repetición
exacta sobre `aborted` devuelve la misma evidencia sin repetir el efecto remoto.
Las sesiones completadas, expiradas o bloqueadas por política fallan cerradas.

El puerto proveedor-neutral admite aborto con referencia remota vinculada y
recuperación de una sesión `initiated` todavía no vinculada. Para el segundo
caso, el adaptador no productivo descubre únicamente cargas incompletas de la
clave privada exacta y las aborta en páginas acotadas. Después confirma la
ausencia de la carga o de sus partes antes de permitir la transición durable.
Nunca ejecuta `delete_object`, por lo que un original ya ensamblado no se borra.

La limpieza automática reclama por defecto 25 sesiones activas vencidas y
admite un máximo de 100 por lote. La consulta usa bloqueo con
`SKIP LOCKED`, orden determinista por vencimiento e identidad, y permite varios
limpiadores sin que reclamen la misma fila. Los fallos remotos dejan la sesión
activa para reintento; solo una confirmación positiva cambia el estado a
`expired`.

Al cerrar una sesión se elimina la referencia remota interna, pero se conservan
la sesión, el estado terminal, sus fechas y toda la evidencia durable de partes.
Por tanto, la limpieza reduce el almacenamiento incompleto del proveedor sin
ocultar los datos tomados en campo ni su trazabilidad. La activación periódica,
las métricas y alarmas quedan para la integración final; este bloque continúa
sin proveedor productivo, scheduler, frontend, cola o worker.

### Bloque de manifiesto de fuentes del vuelo

Las fotografías originales y los auxiliares se registran primero como activos
individuales `flight_photo` o `flight_auxiliary`. Cada uno conserva su objeto
privado e inmutable y puede usar el flujo síncrono o multipartes según su tamaño.
El manifiesto no mueve, empaqueta, descarga ni abre esos binarios.

`dbi_flight_source_bundles` relaciona una identidad estable de conjunto con el
tenant, finca, lote opcional, `flight_ref` y ortofoto maestra. Mientras el dominio
no incorpore una entidad `Flight` en su ticket correspondiente, `flight_ref` es
una referencia canónica estable y no una clave foránea inventada. Las claves
compuestas impiden enlazar una ortofoto o una fuente perteneciente a otro tenant.
La capa autorizada exige además coincidencia exacta de finca y lote antes de
consultar activos.

`dbi_flight_source_entries` guarda una instantánea verificable por objeto:
identificador de activo, orden determinista, rol, nombre lógico, MIME, tamaño,
SHA-256, sensor/cámara y fecha de captura cuando existen. No admite duplicar un
activo, nombre lógico u ordinal dentro del mismo conjunto. Solo activos
`registered` o `verified` pueden incorporarse; activos `quarantined` o `retired`
fallan cerrados.

El contenido canónico ordenado produce `manifest_sha256`. Repetir la creación
con los mismos datos devuelve el mismo conjunto sin duplicarlo; cualquier cambio
bajo el mismo UUID o vuelo es conflicto. El manifiesto no expone `object_key`,
URLs, referencias del proveedor, checksums multipartes ni credenciales.

La API añade creación autorizada bajo
`POST /api/v1/dbi/assets/{master_asset_id}/flight-source-manifests` y lectura
paginada bajo
`GET /api/v1/dbi/assets/{master_asset_id}/flight-source-manifests/{bundle_id}`.
Una página contiene como máximo 500 entradas y usa el ordinal estable, de modo
que el cliente puede recorrer y representar todos los datos sin cargar miles de
filas o archivos originales simultáneamente en memoria.

No se crea un ZIP obligatorio. Un paquete de descarga futuro seguirá siendo un
derivado adicional. Este bloque no incorpora frontend, entidad de vuelo, COG,
teselas, cola, worker, proveedor productivo ni datos reales.

## 13. Referencias oficiales

- Amazon S3 multipart upload limits:
  https://docs.aws.amazon.com/AmazonS3/latest/userguide/qfacts.html
- Multipart upload overview:
  https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html
- Checking object integrity for uploads:
  https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html
- CompleteMultipartUpload API:
  https://docs.aws.amazon.com/AmazonS3/latest/API/API_CompleteMultipartUpload.html
