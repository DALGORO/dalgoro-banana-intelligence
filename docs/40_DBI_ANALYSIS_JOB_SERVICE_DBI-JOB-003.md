# 40 — Servicio y API de trabajos DBI-JOB-003

<!-- markdownlint-disable MD013 -->

## Identificación

- Ticket: `DBI-JOB-003`.
- Issue: #58.
- Hito: #30.
- Rama: `feat/DBI-JOB-003-servicio-api-idempotente-trabajos`.
- Base: `main` en `cfd1e0629387619670c6cfc2a8560224c3e19c3a`.
- Estado: diseño aprobado; implementación funcional pendiente.
- Pull request: borrador vinculado al Issue #58.
- Fecha: 2026-08-04.

## 1. Objetivo

Crear la frontera autorizada e idempotente que convierte una solicitud HTTP
válida en un trabajo geoespacial persistido, sin transferir binarios, publicar
mensajes ni ejecutar el pipeline.

El trabajo nace en estado `accepted`. `DBI-QUEUE-001` será responsable de la
entrega durable que permita avanzar a `queued`; `DBI-WORKER-001` asumirá la
ejecución. Este ticket no simula esas capacidades pendientes.

La API también expondrá consulta, cancelación y reintento. Esas operaciones
respetarán la máquina de estados existente, incluso cuando ello signifique
devolver un conflicto mientras la cola o el worker aún no hayan llevado el
trabajo a un estado compatible.

## 2. Dependencias confirmadas

| Dependencia | Evidencia disponible | Uso en este ticket |
| --- | --- | --- |
| `DBI-JOB-001` | Comando v1 y máquina de estados | Contrato canónico y transiciones |
| `DBI-JOB-002` | Tablas de trabajos e intentos | Persistencia del estado global |
| `DBI-API-001` | Sesión DBI en FastAPI | Frontera transaccional |
| `DBI-AUTH-001..002` | Contexto y permisos DBI | Autorización cerrada por defecto |
| `DBI-ASSET-001..003` | Activos, verificación y maestros grandes | Entradas verificadas por referencia |
| `DBI-STORAGE-001` | Objetos privados | Separación de metadata y binario |

Las lecturas existentes ya publican trabajos por finca en
`/organizations/{organization_ref}/farms/{farm_id}/jobs`. El nuevo router debe
conservar esa semántica y no crear una segunda representación incompatible.

## 3. Estado real de la base

La tabla `dbi_analysis_jobs` ya conserva:

- identidad UUID del trabajo;
- `tenant_ref + request_id` como clave idempotente única;
- finca, lote y campaña opcional;
- referencias de ortofoto, límite y exclusiones;
- versión de modelo y configuración del pipeline;
- actor solicitante, correlación, SHA-256 del comando y estado;
- fechas UTC de aceptación, creación y actualización.

Las referencias de activos están persistidas actualmente como texto opaco de
hasta 128 caracteres, mientras `dbi_analysis_input_assets.id` usa UUID. No se
cambiará ese tipo mediante una conversión ciega.

### 3.1 Decisión de persistencia del bloque 4

La evidencia del modelo y de la migración vigente permite conservar las
referencias de activos como texto opaco de hasta 128 caracteres. Este ticket no
convierte esas columnas a UUID, no las renombra y no añade claves foráneas de
forma retrospectiva.

Toda escritura nueva persiste exclusivamente la representación canónica
`str(UUID)`, en minúsculas y con guiones. Antes de crear el trabajo, el
repositorio consulta y bloquea el activo real mediante
`dbi_analysis_input_assets.id`, y comprueba tenant, finca, lote, clase y estado
`verified` dentro de la misma transacción.

Una referencia histórica se considera canónica únicamente cuando:

1. puede interpretarse como UUID;
2. su texto almacenado coincide exactamente con `str(UUID)`; y
3. corresponde al activo solicitado dentro del ámbito autorizado.

Una referencia histórica vacía, inválida, no canónica o transversal falla de
forma cerrada. La repetición no corrige, reemplaza ni elimina la fila existente,
y la respuesta pública no revela qué dato histórico produjo el conflicto.

No se añade una columna `request_fingerprint`. La intención HTTP estable puede
reconstruirse de manera completa desde:

- `tenant_ref`;
- `request_id`;
- `farm_id`;
- `plot_id`;
- `campaign_id`;
- `orthophoto_asset_ref`;
- `boundary_asset_ref`;
- `exclusions_asset_ref`;
- `requested_by_ref`; y
- la versión fija del contrato de intención.

El repositorio reconstruye `AnalysisJobRequestIntent`, calcula nuevamente
`request_fingerprint` y compara la intención histórica con la intención
entrante. La restricción única `tenant_ref + request_id` continúa siendo la
defensa final ante carreras concurrentes.

`command_sha256` permanece separado y representa únicamente los bytes canónicos
de `analysis-job-command.v1`. No se reutiliza para comparar la intención HTTP,
porque el comando también contiene el perfil resuelto y referencias generadas
por el servidor.

La evidencia actual no exige una migración. El bloque siguiente confirmará
formalmente que la migración condicional no aplica antes de iniciar el
repositorio transaccional. Una evidencia posterior contradictoria obligaría a
detener la implementación y diseñar una migración aditiva, nunca una conversión
destructiva.

## 4. Autoridad y ámbito

Toda operación recibe un `DBIAccessContext` ya resuelto. Un identificador no
concede autoridad.

La creación exige `DBIPermission.SUBMIT_ANALYSIS` para:

1. tenant del contexto;
2. organización de la ruta;
3. finca de la ruta;
4. lote de la ruta.

La autorización ocurre antes de buscar activos. Después se vuelven a comprobar
las relaciones persistidas:

- el lote pertenece a la finca;
- la finca pertenece al ámbito organizacional autorizado;
- la campaña opcional pertenece a la misma finca y cubre el lote según las
  reglas vigentes;
- todos los activos pertenecen al tenant, finca y lote exactos.

Una denegación o una referencia transversal usa una respuesta no enumerable. La
API no distingue públicamente entre recurso inexistente y recurso fuera del
ámbito autorizado.

## 5. Entradas agrícolas válidas

Un trabajo de análisis solo puede construirse con entradas científicamente
trazables y listas para procesar.

| Rol | Clase esperada | Estado requerido | Regla espacial |
| --- | --- | --- | --- |
| Ortofoto | maestro de ortofoto aprobado | `verified` | misma finca y lote |
| Límite | límite autorizado | `verified` | mismo tenant, finca y lote |
| Exclusiones | máscara o exclusiones aprobadas | `verified` | mismo tenant, finca y lote |

Las clases exactas se alinearán con el enum vigente de activos; no se aceptarán
alias inventados por la API.

Un maestro multipartes que terminó el transporte pero permanece
`registered`, pendiente del SHA-256 canónico del contenido, no es una entrada
válida. Tampoco lo son activos `quarantined` o `retired`.

El servicio no descarga el GeoTIFF, no calcula índices y no abre objetos. Usa
exclusivamente metadata durable y referencias internas.

## 6. Contrato HTTP propuesto

### 6.1 Crear trabajo

`POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/jobs`

Solicitud estricta y sin campos desconocidos:

- `schema_version = dbi-analysis-job-request.v1`;
- `request_id`;
- `campaign_id` opcional;
- `orthophoto_asset_id`;
- `boundary_asset_id`;
- `exclusions_asset_id` opcional.

El cliente no envía tenant, actor, correlación, estado, object key, URL,
checksum, versión de modelo o configuración de pipeline.

Respuesta acotada:

- `schema_version = dbi-analysis-job-response.v1`;
- `job_id`;
- `status`;
- `accepted_at`;
- `created`, para distinguir alta de repetición exacta.

Resultado HTTP:

- `201 Created` cuando la solicitud crea el trabajo;
- `200 OK` cuando una repetición exacta recupera el mismo trabajo;
- `409 Conflict` cuando el mismo `request_id` representa otra intención.

### 6.2 Consultar trabajo

Se reutiliza:

`GET /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}`

La respuesta de lectura continúa sin exponer SHA del comando, actor interno,
referencias de objetos, credenciales o payload del comando.

### 6.3 Solicitar cancelación

`POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}/cancel`

La operación bloquea el trabajo y evalúa la transición pura:

- `queued -> cancel_requested`;
- `running -> cancel_requested`;
- repetición en `cancel_requested`: no-op idempotente;
- `accepted`, `failed`, `succeeded` o `canceled`: conflicto.

La API no cambiará `accepted` directamente porque esa transición no existe en
`DBI-JOB-001`. La futura cola permitirá que los trabajos aceptados avancen a
`queued`.

### 6.4 Reintentar

`POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}/retry`

Solo admite `failed -> queued` con autorización explícita. Una repetición sobre
`queued` es un no-op idempotente. Este ticket persiste la transición, pero no
publica un mensaje ni crea un intento; esos efectos pertenecen a la cola y al
worker.

## 7. Perfil de análisis aprobado

El contrato de ejecución exige `model_version_id` y
`pipeline_config_version`. El cliente HTTP no puede escogerlos libremente.

Hasta implementar `DBI-ML-001`, el servicio recibirá un puerto puro e
inyectable que resuelva un perfil aprobado por el servidor. Su salida contiene:

- referencia opaca y versionada del modelo;
- versión inmutable de configuración del pipeline;
- identificador de política o revisión usada para resolverlos.

La implementación inicial puede usar una política explícita no productiva y
probada. No consulta un proveedor remoto, no descarga modelos y no representa un
registro Champion/Challenger.

Ausencia, ambigüedad o perfil no aprobado fallan antes de persistir el trabajo.

## 8. Intención canónica y comando v1

La huella de solicitud idempotente representa únicamente la intención HTTP
estable y los datos confiables del actor:

- tenant;
- `request_id`;
- finca, lote y campaña;
- UUID canónicos de entradas;
- actor solicitante;
- versión del contrato.

El perfil de análisis aprobado no forma parte de `request_fingerprint`. Un cambio
posterior de política no debe convertir una repetición HTTP exacta en una
intención divergente. El perfil sí forma parte del
`analysis-job-command.v1` y, por tanto, de `command_sha256`.

El servidor genera `job_id` y `correlation_id`. El comando
`analysis-job-command.v1` se serializa con:

- orden determinista de claves;
- UTF-8;
- representación canónica de UUID;
- sin espacios variables;
- exclusiones ausentes representadas de una única forma.

El SHA-256 se calcula sobre esos bytes. Una repetición reconstruye la misma
intención desde la solicitud, el contexto y el perfil vigente. Si el perfil
aprobado cambió después de la primera solicitud, el repositorio recupera el
trabajo existente y compara la intención histórica antes de decidir; no
reinterpreta silenciosamente una solicitud antigua con un modelo nuevo.

La implementación debe separar:

- `request fingerprint`: comparación de la intención HTTP estable; y
- `command_sha256`: evidencia exacta del comando persistido.

Si el modelo actual no permite conservar ambas evidencias, el bloque de
persistencia evaluará una columna aditiva. Nunca se reutilizará
`command_sha256` para comparar datos que no pertenezcan al comando.

## 9. Algoritmo idempotente

Dentro de una única transacción:

1. autorizar el ámbito;
2. validar finca, lote y campaña;
3. bloquear y validar los activos exactos;
4. construir la intención canónica;
5. resolver o recuperar el perfil aplicable;
6. intentar insertar el trabajo con `ON CONFLICT DO NOTHING`;
7. recuperar por `tenant_ref + request_id`;
8. bloquear la fila recuperada;
9. reconstruir y comparar toda la intención persistida;
10. devolver el trabajo existente solo si coincide exactamente.

La restricción única de base es la defensa final. Los bloqueos evitan que un
activo cambie a retirado entre la validación y la creación del trabajo.

Ningún camino ejecuta llamadas de almacenamiento, cola, worker o modelo remoto.

## 10. Transacciones y responsabilidades

| Capa | Responsabilidad | Prohibición |
| --- | --- | --- |
| API | validar HTTP, confirmar o revertir | ejecutar pipeline |
| Servicio | autorizar y coordinar reglas | `commit` o `rollback` |
| Repositorio | consultas, bloqueos e inserción | autorización o efectos externos |
| Política de perfil | resolver versión aprobada | descargar o promover modelos |
| Cola futura | entregar comando durable | incluirse en este ticket |

El router realiza `commit` solo después de completar la operación. Cualquier
excepción ejecuta `rollback`. El repositorio no cierra la sesión.

## 11. Concurrencia multiusuario

Las pruebas PostgreSQL deben cubrir, como mínimo:

- dos solicitudes exactas simultáneas crean un solo UUID;
- misma clave y diferente activo produce conflicto;
- misma clave en tenants distintos no colisiona;
- un retiro concurrente no permite crear el trabajo con un activo retirado;
- cancelaciones simultáneas producen una sola transición;
- reintentos simultáneos producen una sola transición;
- una autorización de otro lote no puede observar la existencia del trabajo;
- el rollback no deja un trabajo parcial.

Las pruebas usan datos sintéticos y no transfieren ortofotos. El tamaño de 1–10
GB no aumenta memoria, tiempo de request o payload porque la API solo recibe
UUID.

## 12. Errores públicos

| Condición | HTTP | Semántica |
| --- | --- | --- |
| No autenticado | 401 | identidad ausente |
| Ámbito o recurso no visible | 404 | respuesta no enumerable |
| Solicitud inválida | 422 | contrato estricto |
| Idempotencia divergente | 409 | misma clave, otra intención |
| Estado no compatible | 409 | transición inválida |
| Perfil no disponible | 503 o código estable acordado | política cerrada |
| Fallo transaccional | 500 | rollback confirmado |

No se devuelven detalles de SQL, tenant, object key, URL, checksum, bucket,
proveedor, comando completo o credenciales.

## 13. Observabilidad y costos

Este ticket mide efectos de control, no bytes del maestro:

- solicitudes creadas;
- repeticiones exactas;
- conflictos idempotentes;
- denegaciones;
- activos no verificables;
- cancelaciones y reintentos;
- duración agregada del servicio;
- rollbacks.

Las etiquetas no incluyen identificadores de tenant, organización, finca, lote,
activo, trabajo, request, correlación o persona.

El costo incremental esperado es metadata en PostgreSQL y tráfico HTTP pequeño.
No existe egreso de ortofotos, inferencia, GPU, almacenamiento duplicado o
solicitud de teselas dentro de DBI-JOB-003. Esos costos se medirán en los tickets
que introduzcan sus efectos.

## 14. Riesgos y controles

| Riesgo | Control |
| --- | --- |
| Duplicar trabajo por reintento | unicidad, bloqueo y comparación total |
| Cruzar activos entre clientes | ámbito exacto antes y después de leer |
| Procesar maestro no verificado | exigir `verified` |
| Modelo arbitrario | perfil resuelto por servidor |
| Efecto de cola prematuro | trabajo termina en `accepted` |
| Migración destructiva | puerta de evidencia y ruta no destructiva |
| Enumeración | 404 uniforme y autorización previa |
| Filtración en logs | métricas agregadas sin identificadores |
| Cancelación ficticia | respetar estados de DBI-JOB-001 |
| Reintento duplicado | transición bloqueada e idempotente |

## 15. Orden de implementación

1. [x] Issue #58 y diseño de invariantes.
2. [x] Contratos HTTP, intención canónica y política de perfil.
3. [x] Pruebas offline de contratos e idempotencia pura.
4. [x] Decisión documentada sobre persistencia de referencias y fingerprint.
5. [ ] Migración aditiva solo si la evidencia la exige.
6. [ ] Repositorio con bloqueos e inserción idempotente.
7. [ ] Servicio autorizado de creación.
8. [ ] Consulta, cancelación y reintento autorizados.
9. [ ] API transaccional y montaje del router.
10. [ ] Integración PostgreSQL/PostGIS y concurrencia.
11. [ ] Métricas seguras y documentación oficial.
12. [ ] Auditoría final sobre el SHA exacto.

Cada bloque requiere revisión antes de avanzar. El Draft PR no pasa a Ready for
review ni se fusiona sin aprobación explícita.

### Evidencia del bloque 2

- `app/dbi/jobs/service_contracts.py` define la solicitud y respuesta HTTP.
- La solicitud acepta únicamente referencias UUID y `request_id`.
- `AnalysisJobRequestIntent` separa la intención HTTP estable.
- `ApprovedAnalysisProfile` y `AnalysisProfilePolicy` impiden que el cliente
  seleccione directamente el modelo o la configuración.
- La serialización canónica usa UTF-8, claves ordenadas, separadores compactos y
  representación explícita de valores opcionales.
- `request_fingerprint` permanece separado de `command_sha256`.
- No se modifican modelos SQLAlchemy, migraciones, repositorios, API, cola,
  worker, almacenamiento, frontend o servicios productivos.

### Evidencia del bloque 3

- `.github/scripts/ci_analysis_job_service_contracts.py` valida los contratos
  sin base de datos, red, almacenamiento ni servicios externos.
- La solicitud rechaza campos adicionales, UUID inválidos, referencias
  obligatorias ausentes y versiones de contrato desconocidas.
- La respuesta exige `accepted_at` consciente de zona horaria.
- Los contratos permanecen inmutables después de ser validados.
- La intención produce bytes canónicos UTF-8 con claves ordenadas,
  separadores compactos y valores opcionales representados como `null`.
- El mismo contenido produce el mismo `request_fingerprint`, aunque el orden
  de entrada sea diferente.
- Una modificación semántica de la intención produce una huella distinta.
- La resolución de un perfil diferente no altera la huella estable de la
  solicitud HTTP.
- `AnalysisProfilePolicy` se valida como frontera estructural y falla cerrada
  mediante `AnalysisProfileUnavailable`.
- La barrera impide introducir SQLAlchemy, FastAPI, sesiones, bases de datos,
  colas, broker, Redis, Celery o clientes externos en los contratos puros.
- `.github/workflows/ci.yml` ejecuta la nueva validación antes de las pruebas
  de persistencia.
- No se modifican modelos, migraciones, repositorios, servicios, API, cola,
  worker, almacenamiento, frontend o despliegues.

### Evidencia del bloque 4

- `AnalysisJob` conserva las referencias de ortofoto, límite y exclusiones en
  columnas `String(128)`.
- `AnalysisInputAsset.id` utiliza UUID como identidad primaria.
- Las nuevas referencias se persistirán exclusivamente mediante `str(UUID)`.
- Las referencias históricas no canónicas fallarán de forma cerrada y no serán
  reescritas durante una repetición.
- La tabla ya conserva todos los campos necesarios para reconstruir
  `AnalysisJobRequestIntent`.
- `tenant_ref + request_id` continúa siendo la clave idempotente única.
- `request_fingerprint` se reconstruirá desde la intención histórica y no
  requiere una columna nueva.
- `command_sha256` permanece como evidencia independiente del comando exacto.
- La evidencia actual no exige modificar el modelo ni crear una migración.
- No se asume que las bases estén vacías y no se eliminan filas históricas.
- No se modifican modelos SQLAlchemy, migraciones, repositorios, servicios,
  API, cola, worker, frontend, almacenamiento ni despliegues.

## 16. Fuera de alcance

- cola, broker, outbox, productor o consumidor;
- creación de intentos de ejecución;
- worker y etapas del pipeline;
- lectura o descarga de binarios;
- registro Champion/Challenger;
- resultados, artefactos y hallazgos;
- COG, BigTIFF, overviews, teselas y caché;
- frontend;
- proveedor productivo, datos reales o despliegue;
- cambios en WhatsApp, Green API, Google Sheets o Render.

## 17. Puerta de salida

DBI-JOB-003 se considera completo únicamente cuando una solicitud autorizada:

1. selecciona activos verificados y del ámbito exacto;
2. produce un comando v1 canónico;
3. persiste un único trabajo `accepted`;
4. neutraliza repeticiones exactas y rechaza divergencias;
5. permite consulta y transiciones válidas sin enumeración;
6. demuestra concurrencia e aislamiento en PostgreSQL/PostGIS;
7. mantiene binarios, cola, worker y modelos productivos fuera del proceso;
8. aprueba CI sobre la cabeza final;
9. actualiza el Issue #58 y el Hito #30 después de la fusión.
