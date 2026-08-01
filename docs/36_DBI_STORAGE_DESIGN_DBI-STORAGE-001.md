# 36 — Implementación proveedor-neutral DBI-STORAGE-001

## Identificación

- Ticket: `DBI-STORAGE-001`.
- Issue: #51.
- Pull request: #52.
- Hito: #30.
- Rama: `feat/DBI-STORAGE-001-almacenamiento-privado-objetos`.
- Base auditada: `main` en `c576fd041f819c3c796d93bdfb7a30a70f522429`.
- SHA funcional auditado de Etapa A: `fcf16508f418ac016696c1b2a20a927e09fe710c`.
- Estado: Etapa A funcionalmente completa y auditada; Etapa B bloqueada por aprobación de proveedor.

## Objetivo cumplido en Etapa A

Se implementó una frontera proveedor-neutral para objetos privados que define:

- direcciones y claves relativas canónicas;
- aislamiento criptográfico de namespace por tenant;
- propósitos funcionales explícitos;
- metadatos inmutables de MIME, tamaño y SHA-256;
- escritura verificada e idempotente;
- lectura privada;
- retiro lógico irreversible por defecto;
- concesiones temporales de lectura y carga;
- vinculación de cada concesión a metadatos completos;
- métricas agregadas sin claves, contenido, firmas o secretos;
- un adaptador en memoria sin red, disco, SQL o SDK externo.

La Etapa A no selecciona proveedor, no crea bucket, no incorpora credenciales y
no escribe las tablas DBI de activos o artefactos.

## Frontera con DBI-ASSET-001 y DBI-ASSET-002

`DBI-ASSET-001` continúa siendo propietario de los metadatos persistidos de
activos y artefactos. `DBI-STORAGE-001` no importa sus modelos, no abre sesiones
y no cambia estados de dominio.

La coordinación entre:

- autorización agrícola;
- registro de `AnalysisInputAsset`;
- concesión temporal de carga;
- verificación del objeto;
- transición a `verified`, `quarantined` o `retired`;
- compensación entre PostgreSQL y almacenamiento;

permanece reservada para `DBI-ASSET-002`.

## Componentes implementados

### Contratos

Archivo:

```text
apps/platform-web/backend/app/dbi/storage_contracts.py
```

Tipos principales:

- `DBIStoragePurpose`;
- `DBIStorageAccessMode`;
- `DBIStorageObjectState`;
- `DBIStorageAddress`;
- `DBIStorageObjectMetadata`;
- `DBIStorageWriteRequest`;
- `DBIStorageObjectRecord`;
- `DBIStorageWriteResult`;
- `DBIStorageTemporaryGrant`;
- `DBIPrivateObjectStore`.

Errores normalizados:

- `DBIStorageDenied`;
- `DBIStorageConflict`;
- `DBIStorageNotFound`;
- `DBIStorageIntegrityError`.

El puerto contiene únicamente:

- `put`;
- `stat`;
- `open_read`;
- `retire`;
- `issue_temporary_access`.

No existe operación de publicación, ACL pública, URL permanente, purga física o
reactivación.

### Política canónica

Archivo:

```text
apps/platform-web/backend/app/dbi/storage_policy.py
```

La clave se deriva como:

```text
tenants/{namespace-opaco}/{purpose}/{object_uuid}
```

El namespace del tenant se deriva mediante SHA-256 con un dominio de separación
versionado. La clave no contiene la referencia legible del tenant, nombres de
archivo originales, correos, teléfonos, rutas locales o datos personales.

Se rechazan:

- rutas absolutas;
- esquemas URL;
- `.` y `..`;
- segmentos vacíos;
- `//`;
- barras invertidas;
- consultas y fragmentos;
- caracteres de control;
- comodines;
- referencias con espacios externos;
- claves fabricadas para otro tenant, propósito o UUID.

### Propósitos y MIME

Propósitos admitidos:

- `analysis-inputs`;
- `analysis-artifacts`;
- `model-artifacts`;
- `technical-sources`.

Cada propósito tiene una lista MIME cerrada. Un tipo permitido para un
artefacto no se convierte automáticamente en un tipo permitido para una entrada
de análisis. Los parámetros MIME, mayúsculas no canónicas y tipos web activos
como `text/html` son rechazados.

### Integridad

Toda identidad de objeto contiene:

- dirección canónica;
- MIME canónico;
- tamaño positivo compatible con `BigInteger`;
- SHA-256 hexadecimal en minúsculas.

El adaptador en memoria lee el flujo por bloques y verifica el tamaño y SHA-256
antes de crear el objeto. Un flujo textual, tamaño inferior, tamaño superior,
huella divergente o límite local excedido genera `DBIStorageIntegrityError` y
no deja un objeto parcial.

### Idempotencia

La misma clave con los mismos metadatos y bytes produce:

```text
created = false
```

La misma clave con MIME, tamaño, SHA-256 o contenido diferente produce conflicto.
Un objeto retirado no se reactiva mediante `put` ni mediante una concesión nueva
de carga.

### Acceso temporal

Una concesión contiene:

- referencia opaca no representada en `repr`;
- metadatos completos del objeto;
- modo `read` o `write`;
- emisión UTC;
- expiración UTC.

TTL admitido:

- mínimo: 30 segundos;
- máximo: 1 hora.

La referencia opaca no admite `/`, `:`, consulta, fragmento, espacios o forma de
URL.

Semántica:

- `read` exige un objeto activo y metadatos exactamente coincidentes;
- `write` puede emitirse antes de que exista el objeto;
- `write` sobre un objeto activo exige metadatos exactamente coincidentes;
- un objeto retirado no admite una concesión de lectura ni de carga;
- metadatos divergentes producen conflicto.

Esta definición permite que un futuro adaptador firme una carga con MIME,
tamaño y SHA-256 vinculados sin convertir la firma específica del proveedor en
parte del dominio.

### Retiro lógico

El primer retiro devuelve `true`. Un retiro repetido exacto devuelve `false`.
Después del retiro:

- `stat` no expone el objeto;
- `open_read` no lo expone;
- `read` temporal no se concede;
- `write` temporal no se concede;
- `put` no lo reactiva.

El adaptador en memoria conserva internamente el contenido para reproducir la
semántica de retiro, pero no ofrece una operación de acceso interno o purga.

### Adaptador en memoria

Archivo:

```text
apps/platform-web/backend/app/dbi/storage_memory.py
```

Propiedades:

- sin red;
- sin filesystem;
- sin SQLAlchemy;
- sin `DATABASE_URL`;
- sin SDK de proveedor;
- reloj y generador de referencia inyectables;
- límite de tamaño configurable;
- bloqueo reentrante para operaciones atómicas;
- copias `BytesIO` independientes para lectura.

El límite predeterminado de 16 MiB solo pertenece al doble de prueba; no define
el tamaño operativo de ortofotos o productos reales.

### Métricas

Archivo:

```text
apps/platform-web/backend/app/dbi/storage_metrics.py
```

El decorador `DBIMeteredObjectStore` agrega:

- intentos de escritura, lectura, consulta, retiro y concesión;
- objetos creados y retiros efectivos;
- reintentos idempotentes;
- bytes verificados, creados y abiertos;
- errores normalizados por categoría.

No registra:

- tenant;
- organización;
- clave;
- UUID del objeto;
- MIME;
- SHA-256;
- contenido;
- referencia temporal;
- URL;
- credencial;
- ruta.

Las excepciones `DBIStorage*` lanzadas por el consumidor dentro del bloque
`open_read` se propagan, pero no se contabilizan como fallos del adaptador. Los
errores producidos durante la adquisición o cierre del adaptador sí se agregan.

## Pruebas offline

Scripts:

```text
.github/scripts/ci_dbi_storage_contracts.py
.github/scripts/ci_dbi_storage_memory.py
.github/scripts/ci_dbi_storage_metrics.py
```

Cobertura principal:

- dirección canónica y namespace diferente por tenant;
- traversal, URL, ruta absoluta, barra invertida y segmentos prohibidos;
- MIME permitido y rechazado por propósito;
- tamaño y SHA-256 canónicos;
- TTL mínimo, máximo, zona horaria y referencia opaca;
- grant vinculado a metadatos completos;
- carga temporal previa a existencia;
- lectura temporal solo de objeto activo exacto;
- escritura nueva e idempotente;
- divergencias de metadata y contenido;
- contenido incompleto, excedido y corrupto;
- lectura mediante flujo independiente;
- aislamiento por tenant;
- retiro lógico e irreversibilidad;
- métricas de éxito y error;
- separación entre error del consumidor y error del adaptador;
- ausencia de SDK, red, filesystem, SQL y configuración heredada.

Las tres suites se ejecutan dentro del smoke test completo del backend.

## Evidencia automatizada

SHA funcional de Etapa A:

```text
fcf16508f418ac016696c1b2a20a927e09fe710c
```

Resultados:

- `CI modular #513`: 6/6 trabajos aprobados;
- `DBI migrations integration #198`: aprobada;
- backend completo y smoke test de almacenamiento: aprobados;
- frontend lint/build y auditoría: aprobados;
- WhatsApp smoke test: aprobado;
- densidad geoespacial: aprobada;
- higiene del repositorio: aprobada;
- Gitleaks sobre historial completo: aprobado.

No se añadieron migraciones, modelos, rutas HTTP, dependencias, contenedores o
permisos PostgreSQL.

## Incidencias detectadas y corregidas

### Fixture de clave transversal

El SHA `508f63cc71266aa6c783c6bb315f1d3dbbe43af5` falló porque la prueba usaba
`replace` sobre el tenant sin recalcular el `object_key`; el supuesto key de otro
tenant era en realidad el key original válido. Se corrigió únicamente el
fixture para derivar un key real de `tenant-b`. El SHA
`cd1ccbfacefe590024eb12bd322a0e836708fc9c` quedó verde.

### Auditoría de grants y métricas

La revisión acumulada posterior detectó dos brechas de contrato:

1. una concesión temporal vinculaba solo la dirección, no MIME, tamaño y SHA-256;
2. el decorador de métricas podía contar como error del adaptador una excepción
   `DBIStorage*` lanzada deliberadamente por el consumidor durante la lectura.

Se corrigieron contratos, política, adaptador, métricas y pruebas. El SHA
`fcf16508f418ac016696c1b2a20a927e09fe710c` terminó con ambas Actions en verde.

## Puerta de proveedor

Documento:

```text
docs/37_DBI_STORAGE_PROVIDER_GATE_DBI-STORAGE-001.md
```

Define la evidencia exigida para:

- privacidad;
- IAM;
- aislamiento;
- cifrado;
- integridad;
- escritura condicional;
- acceso temporal;
- cargas multipartes;
- auditoría;
- métricas;
- recuperación;
- retención;
- residencia;
- disponibilidad;
- límites;
- dependencias y licencias;
- costos medidos.

## Etapa B bloqueada

Sin aprobación explícita en el Issue #51 no se incorporará:

- proveedor o servicio concreto;
- SDK;
- contenedor;
- bucket;
- endpoint;
- región;
- credenciales;
- variables específicas;
- workflow de integración externo.

La aprobación debe identificar proveedor, servicio, región de prueba,
justificación técnica/económica, IAM, configuración, dependencia fijada,
reversión y responsable de costos.

## Límites conservados

Fuera de alcance:

- creación o transición de `AnalysisInputAsset`;
- endpoints de activos;
- coordinación base–objeto;
- cola y worker;
- publicación de resultados;
- producción o staging remoto;
- CDN o acceso público;
- purga física;
- WhatsApp, Google Sheets, Render o modelos de IA.

## Condición para marcar el PR listo

El PR #52 permanecerá en borrador hasta que:

- el proveedor no productivo sea aprobado explícitamente;
- se implemente y pruebe el adaptador real requerido por el Issue #51, o se
  apruebe formalmente un cambio del backlog que permita dividir el ticket;
- la documentación final incluya evidencia de integración, costos y
  recuperación;
- diff, dependencias, secretos, logs y conversaciones estén auditados;
- GitHub Actions estén verdes sobre el SHA final.
