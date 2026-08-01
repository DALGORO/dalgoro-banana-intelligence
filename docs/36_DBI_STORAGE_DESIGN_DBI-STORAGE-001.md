# 36 — Implementación final DBI-STORAGE-001

## Identificación

- Ticket: `DBI-STORAGE-001`.
- Issue: #51.
- Pull request: #52.
- Hito: #30.
- Rama: `feat/DBI-STORAGE-001-almacenamiento-privado-objetos`.
- Base: `main` en `c576fd041f819c3c796d93bdfb7a30a70f522429`.
- SHA funcional auditado previo a documentación final:
  `f0aebbad24c0a6f456f0a30a96399d1a37734005`.
- Estado: Etapas A y B implementadas; pendiente auditoría del SHA documental
  final y revisión del PR.

## Objetivo

`DBI-STORAGE-001` implementa una frontera privada y proveedor-neutral para
objetos binarios de DALGORO Banana Intelligence. El dominio conserva solamente
identidades y metadatos verificables; el adaptador traduce esas operaciones a
S3-compatible sin convertir una URL, bucket, credencial, endpoint o clase de
SDK en autoridad de dominio.

La implementación cubre:

- claves relativas canónicas;
- namespace opaco por tenant;
- MIME, tamaño y SHA-256 inmutables;
- escritura verificada, condicional e idempotente;
- lectura privada con verificación de integridad;
- retiro lógico sin reactivación implícita;
- acceso temporal de lectura y carga;
- métricas no sensibles;
- adaptador en memoria;
- adaptador S3-compatible no productivo;
- integración efímera con SeaweedFS mediante datos exclusivamente sintéticos.

## Frontera con activos DBI

`DBI-ASSET-001` sigue siendo propietario de los metadatos persistidos de
`AnalysisInputAsset` y `AnalysisArtifact`.

Este ticket no:

- importa modelos de activos;
- abre sesiones PostgreSQL;
- crea o actualiza filas de activos;
- cambia estados de dominio;
- autoriza operaciones agrícolas;
- crea endpoints HTTP;
- conecta cola o worker;
- publica resultados geoespaciales.

La coordinación entre autorización, registro de activo, concesión de carga,
verificación, cuarentena, compensación y transición de estado permanece en
`DBI-ASSET-002`.

## Arquitectura

### Contratos

Archivo:

```text
apps/platform-web/backend/app/dbi/storage_contracts.py
```

El puerto `DBIPrivateObjectStore` expone únicamente:

- `put`;
- `stat`;
- `open_read`;
- `retire`;
- `issue_temporary_access`.

No existe operación para:

- publicar un objeto;
- asignar ACL pública;
- persistir URL firmada;
- purgar físicamente;
- reactivar un objeto retirado;
- enumerar tenants;
- modificar metadatos en sitio.

Errores normalizados:

- `DBIStorageDenied`;
- `DBIStorageConflict`;
- `DBIStorageNotFound`;
- `DBIStorageIntegrityError`;
- `DBIStorageError`.

### Política canónica

Archivo:

```text
apps/platform-web/backend/app/dbi/storage_policy.py
```

Formato de clave:

```text
tenants/{namespace-opaco}/{purpose}/{object_uuid}
```

El namespace se deriva con SHA-256 y un dominio de separación versionado. La
clave no contiene nombres originales, referencia legible del tenant, correo,
teléfono, ruta local o dato personal.

Se rechazan:

- URL y esquemas;
- rutas absolutas;
- `.` y `..`;
- segmentos vacíos;
- `//` y barras invertidas;
- consulta o fragmento;
- caracteres de control;
- comodines;
- referencias con espacios externos;
- claves fabricadas para otro tenant, propósito o UUID.

### Propósitos y MIME

Propósitos:

- `analysis-inputs`;
- `analysis-artifacts`;
- `model-artifacts`;
- `technical-sources`.

Cada propósito utiliza una lista MIME cerrada. Se rechazan parámetros MIME,
mayúsculas no canónicas y tipos activos no autorizados, como `text/html`.

### Integridad e idempotencia

Toda identidad de objeto contiene:

- dirección canónica;
- MIME canónico;
- tamaño positivo;
- SHA-256 hexadecimal en minúsculas.

La misma clave con los mismos metadatos y contenido devuelve:

```text
created = false
```

La misma clave con MIME, tamaño, SHA-256 o contenido divergente produce
`DBIStorageConflict`.

El adaptador verifica el flujo antes de escribir. Un contenido incompleto,
excedido, textual, corrupto o fuera del límite no deja un objeto parcial.

### Acceso temporal

Una concesión contiene:

- referencia opaca;
- metadatos completos;
- modo `read` o `write`;
- emisión UTC;
- expiración UTC.

TTL admitido:

- mínimo: 30 segundos;
- máximo: 1 hora.

Semántica:

- `read` exige objeto activo y metadatos exactos;
- `write` puede emitirse antes de la existencia del objeto;
- el grant de carga vincula MIME, tamaño, SHA-256, tags y condición de no
  sobrescritura;
- un objeto retirado no admite grant de lectura o carga;
- la URL firmada solo existe dentro del adaptador y se resuelve mediante una
  referencia opaca almacenada en memoria hasta su expiración.

## Adaptadores

### Adaptador en memoria

Archivo:

```text
apps/platform-web/backend/app/dbi/storage_memory.py
```

Uso: pruebas deterministas sin red, filesystem, SQL, SDK o configuración
externa.

Propiedades:

- bloqueo reentrante;
- reloj y generador de grant inyectables;
- verificación por bloques;
- lecturas `BytesIO` aisladas;
- retiro lógico irreversible;
- límite predeterminado de 16 MiB exclusivo del doble de prueba.

### Métricas proveedor-neutrales

Archivo:

```text
apps/platform-web/backend/app/dbi/storage_metrics.py
```

Registra únicamente contadores agregados de:

- intentos y éxitos;
- objetos creados;
- reintentos idempotentes;
- retiros;
- grants;
- bytes verificados, creados y abiertos;
- errores por categoría.

No registra tenant, organización, UUID, clave, MIME, SHA-256, contenido, URL,
credencial, firma o ruta.

Las excepciones del consumidor dentro de `open_read` no se atribuyen al
adaptador.

### Adaptador S3-compatible

Archivo:

```text
apps/platform-web/backend/app/dbi/storage_s3.py
```

Configuración:

- credenciales obligatoriamente explícitas;
- sin cadena implícita de credenciales;
- SigV4;
- path-style;
- retries y timeouts acotados;
- HTTP permitido solo para `localhost`, `127.0.0.1` o `::1`;
- HTTPS exige verificación TLS;
- secretos excluidos de `repr`.

Operaciones:

- `PutObject` condicional con `If-None-Match: *`;
- metadata S3 para SHA-256, tamaño, propósito y UUID;
- tags para estado activo o retirado;
- `HeadObject` y tags para reconstruir el registro;
- `GetObject` con verificación posterior de tamaño y SHA-256;
- `PutObjectTagging` para retiro lógico;
- URL temporal SigV4 de lectura o carga;
- registro opaco de grants únicamente en memoria.

Quedan prohibidos en el adaptador:

- `delete_object`;
- ACL pública;
- `public-read`;
- lectura de `os.environ`;
- `DATABASE_URL`;
- `SessionLocal`;
- SQLAlchemy;
- FastAPI;
- modelos de activos.

## Dependencias fijadas

```text
boto3==1.43.62
botocore==1.43.62
jmespath==1.1.0
python-dateutil==2.9.0.post0
s3transfer==0.19.2
```

La CI comprueba:

- versión exacta instalada;
- requisitos sin conflictos mediante `pip check`;
- ausencia de `awscrt`;
- compatibilidad con Python 3.10 o superior para boto3/botocore;
- licencia declarada aprobada;
- ausencia de marcadores AGPL/GPL no autorizados en el conjunto agregado;
- construcción y firma SigV4 completamente offline.

Licencias declaradas:

- SeaweedFS: Apache 2.0;
- boto3 y botocore: Apache 2.0;
- s3transfer: Apache 2.0;
- jmespath: MIT;
- python-dateutil: licencia dual Apache/BSD.

## Proveedor efímero no productivo

Proveedor de integración:

```text
SeaweedFS 4.29
```

Imagen inmutable:

```text
docker.io/chrislusf/seaweedfs:4.29@sha256:d47c7ee99fcb951351d7194915f4e3a5ea604a8e8871183d713907dec4fb9bf5
```

SeaweedFS no fue seleccionado como proveedor de producción. Su función es
validar la compatibilidad S3 del adaptador en un runner temporal.

Controles del contenedor:

- digest verificado antes de ejecutar;
- prohibido `latest`;
- puerto S3 publicado solo en `127.0.0.1:8333`;
- `cap-drop ALL`;
- solo `CHOWN`, `SETGID` y `SETUID` restituidas para el entrypoint;
- `no-new-privileges`;
- límite de procesos, CPU y memoria;
- `/data` y `/tmp` en `tmpfs`;
- sin bind mounts ni volúmenes persistentes;
- contenedor eliminado al finalizar;
- archivos sintéticos únicamente.

El job de frontera usa 128 MiB de `tmpfs`. El job funcional usa 1 GiB de
`tmpfs`, 1,5 GiB de memoria y volúmenes internos de 64 MiB para permitir las
reservas mínimas de SeaweedFS sin persistencia.

## IAM de mínimo privilegio

La identidad técnica se genera para cada job y no se pasa como variable al
contenedor.

Acciones permitidas exclusivamente sobre `dbi-ci-synthetic`:

```text
Read:dbi-ci-synthetic
List:dbi-ci-synthetic
Tagging:dbi-ci-synthetic
Write:dbi-ci-synthetic
```

No contiene:

- `Admin`;
- wildcard;
- acceso al bucket `dbi-ci-forbidden`;
- privilegios sobre otro tenant;
- credencial personal o productiva.

La configuración IAM:

1. se genera en el runner;
2. se copia al contenedor antes del arranque;
3. se elimina inmediatamente del runner;
4. no aparece en el entorno del contenedor;
5. no aparece en logs;
6. desaparece al destruirse el contenedor.

La prueba negativa confirma que la identidad no puede escribir ni consultar el
bucket prohibido.

## Pruebas

### Offline

```text
.github/scripts/ci_dbi_storage_contracts.py
.github/scripts/ci_dbi_storage_memory.py
.github/scripts/ci_dbi_storage_metrics.py
.github/scripts/ci_dbi_storage_sdk_dependencies.py
.github/scripts/ci_dbi_storage_s3.py
```

Cubren contratos, traversal, MIME, integridad, idempotencia, retiro, grants,
métricas, configuración S3, traducción de errores, firma offline, dependencias
y licencias.

### Integración efímera

```text
.github/scripts/ci_dbi_storage_provider_digest.sh
.github/scripts/ci_dbi_storage_provider_bootstrap.sh
.github/scripts/ci_dbi_storage_s3_integration.py
.github/workflows/dbi-storage-provider.yml
```

La integración real demuestra:

- digest exacto;
- arranque endurecido;
- acceso anónimo `403`;
- escritura directa;
- reintento idempotente;
- lectura verificada;
- carga firmada;
- lectura firmada;
- condición de no sobrescritura;
- metadatos y tags;
- retiro lógico;
- inaccesibilidad posterior;
- no reactivación;
- aislamiento entre buckets;
- recuperación de carga directa incompleta;
- recuperación de carga firmada con header obligatorio ausente;
- eliminación del contenedor y almacenamiento temporal.

## Métricas de la ejecución auditada

SHA funcional:

```text
f0aebbad24c0a6f456f0a30a96399d1a37734005
```

Resultados seguros de la integración:

```text
Duración funcional:            465,1 ms
Objetos sintéticos creados:    4
Bytes sintéticos únicos:       114
Cargas fallidas recuperadas:   2
Costo directo del proveedor:   USD 0,00
```

Operaciones S3 observadas:

```text
generate_presigned_url: 4
get_object:              2
get_object_tagging:     29
head_object:            35
put_object:              9
put_object_tagging:      4
```

El costo de SeaweedFS es cero porque se ejecuta localmente dentro del runner. El
posible costo de minutos de GitHub Actions depende del plan y configuración de
facturación del propietario del repositorio; no se representa como costo del
proveedor de objetos.

## GitHub Actions del SHA funcional

- `CI modular #540`: 6/6 trabajos aprobados.
- `DBI storage provider integration #24`: frontera e integración aprobadas.
- `DBI migrations integration #225`: aprobada.
- Backend, frontend, WhatsApp, densidad, higiene y Gitleaks: aprobados.

## Límites de cifrado y producción

La integración usa HTTP únicamente entre procesos del mismo runner mediante
`127.0.0.1`. No existe tránsito externo y el puerto no escucha en interfaces
públicas.

Los bytes viven exclusivamente en `tmpfs` y se destruyen al terminar. No existe
almacenamiento persistente que permita demostrar cifrado en reposo.

Por tanto, este ticket no afirma haber probado:

- TLS de un proveedor remoto;
- cifrado persistente en reposo;
- KMS o rotación de llaves;
- residencia de datos;
- disponibilidad contractual;
- restauración de backup persistente;
- retención o purga legal;
- costos de producción.

Un proveedor productivo futuro deberá usar HTTPS con validación TLS, cifrado en
reposo, IAM separado por ambiente, retención, recuperación, residencia y costos
aprobados. `DBIS3ObjectStoreConfig` ya rechaza HTTP fuera de loopback y HTTPS
sin verificación TLS.

## Incidencias auditadas

Durante la implementación se detectaron y corrigieron:

1. fixture transversal que reutilizaba una clave original;
2. grant inicialmente sin MIME, tamaño y SHA-256;
3. métricas que podían confundir errores del consumidor;
4. contenedor que requería capacidades mínimas para reducir privilegios;
5. identificador temporal presente en una línea de arranque del modo inicial;
6. falta de capacidad temporal para los volúmenes internos de SeaweedFS;
7. identidad inicial con administración global;
8. propiedad de archivo IAM incompatible con un usuario nominal inexistente.

Cada corrección se aisló y se volvió a auditar. La solución final usa IAM
estático de bucket, no el modo administrativo por variables AWS.

## Límites conservados

Fuera de alcance:

- producción o staging remoto;
- datos reales;
- endpoints de carga;
- tablas de activos;
- cola y worker;
- publicación de artefactos;
- CDN;
- acceso público;
- eliminación física;
- migración de binarios existentes;
- WhatsApp, Google Sheets o Render.

## Condición de cierre

Antes de marcar el PR listo deben completarse:

- auditoría verde del SHA documental final;
- actualización del Issue #51 y PR #52 con la evidencia exacta;
- revisión de diff, dependencias, secretos, logs y conversaciones;
- confirmación de cabeza inmutable y estado mergeable.
