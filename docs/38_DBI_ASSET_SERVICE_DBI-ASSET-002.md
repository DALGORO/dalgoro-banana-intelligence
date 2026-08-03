# 38 — Diseño e implementación DBI-ASSET-002

## Identificación

- Ticket: `DBI-ASSET-002`.
- Issue: #53.
- Hito: #30.
- Rama: `feat/DBI-ASSET-002-registro-carga-verificacion-activos`.
- Base: `main` en `623ca91d68f8136223ec81591034c58defc74c7c`.
- Estado: implementación funcional en curso; pruebas offline activas e
  integración conjunta PostgreSQL/PostGIS + S3 incorporada en CI; evidencia de
  ejecución y revisión final pendientes.

## Objetivo

Coordinar el registro autorizado de `AnalysisInputAsset` con objetos privados de
`DBIPrivateObjectStore`, incluyendo idempotencia, carga temporal, verificación,
cuarentena, retiro lógico y recuperación compensatoria.

No se modifican `AnalysisArtifact`, trabajos, cola, worker ni pipeline.

## Avance funcional confirmado

La rama ya contiene contratos estrictos, registro idempotente, repositorio con
locking, servicio de carga temporal, verificación criptográfica, cuarentena,
limpieza compensatoria, retiro lógico, endpoints autorizados y pruebas offline.

El subhito de consistencia del 2026-08-03 refuerza tres invariantes:

1. la clave persistida debe coincidir exactamente con la dirección canónica
   derivada de tenant, propósito y UUID antes de leer un objeto;
2. solo un activo `registered` puede recibir un nuevo grant de carga; los
   estados `verified`, `quarantined` y `retired` generan conflicto sin
   contactar al proveedor;
3. retirar un activo cuyo objeto ya no existe es un no-op idempotente del
   almacenamiento y aun permite completar el estado `retired` en DBI.

El subhito de integración incorpora un rol PostgreSQL mínimo exclusivo para
activos, fixtures geoespaciales sintéticos, SeaweedFS efímero y un ciclo de API
real de registro, carga, verificación, aislamiento, recuperación y retiro. La
prueba registra métricas seguras de latencia, bytes, operaciones, conflictos y
recuperaciones sin exponer URLs, claves o secretos.

La evidencia de la primera ejecución verde y la revisión final continúan
pendientes. Ninguna capacidad productiva queda autorizada por este avance.

## Dependencias confirmadas

- `DBI-ASSET-001`: modelo y tabla de activos.
- `DBI-STORAGE-001`: dirección canónica, integridad, grants y retiro lógico.
- `DBI-API-001`: sesión DBI y ciclo de vida FastAPI.
- `DBI-API-002`: lecturas no enumerables.
- `DBI-API-003`: patrón de escrituras autorizadas.
- `DBI-AUTH-002`: `DBIAccessContext` y permisos de finca/lote.

## Modelo existente

`AnalysisInputAsset` ya contiene:

- `id`;
- `tenant_ref`;
- `farm_id` y `plot_id`;
- `asset_kind`;
- `status`;
- `object_key`;
- `content_type`;
- `size_bytes`;
- `sha256`;
- `crs`;
- `created_by_ref`;
- `verified_at`;
- `created_at` y `updated_at`.

Estados existentes:

```text
registered
verified
quarantined
retired
```

La primera implementación no requiere migración. Cualquier necesidad de nueva
columna deberá demostrarse mediante una prueba o invariantes imposibles de
representar con el esquema actual.

## Idempotencia

El cliente aporta un `asset_id` UUID estable. El servidor nunca acepta
`object_key`.

La dirección se deriva así:

```text
tenant_ref + analysis-inputs + asset_id
```

Un reintento exacto debe devolver el activo existente con su estado persistido
real, no el estado tentativo del intento. Esta evidencia impide emitir un grant
nuevo si el activo ya está `verified`, `quarantined` o `retired`. El mismo
`asset_id` con
finca, lote, tipo, MIME, tamaño, SHA-256 o CRS divergentes debe producir
conflicto.

No se deduplican activos distintos únicamente por SHA-256, porque el mismo
contenido puede tener distinto propósito operativo o pertenencia autorizada.

## Autoridad

Campos controlados exclusivamente por el servidor:

- `tenant_ref`;
- `created_by_ref`;
- `status`;
- `object_key`;
- `verified_at`;
- fechas internas.

Reglas:

1. La finca exige `WRITE` dentro de la organización.
2. Un `plot_id` exige `WRITE` sobre el lote.
3. El lote debe pertenecer exactamente a la finca y organización solicitadas.
4. Un recurso fuera de ámbito se responde igual que uno inexistente.
5. La autorización se comprueba antes de consultar activos no autorizados.

## Ciclo de vida

Transiciones iniciales:

```text
registered -> verified
registered -> quarantined
registered -> retired
verified -> retired
quarantined -> retired
```

Quedan prohibidas:

```text
verified -> registered
quarantined -> registered
retired -> cualquier otro estado
```

### Registro

- valida autorización;
- valida finca y lote;
- deriva dirección y metadata de almacenamiento;
- crea el activo en `registered`;
- acepta reintento exacto;
- no emite ni persiste una URL.

### Grant de carga

- exige activo `registered`;
- un reintento exacto en `verified`, `quarantined` o `retired` produce
  conflicto antes de contactar al almacenamiento;
- una clave ya ocupada produce conflicto de estado y no se clasifica como caída
  del proveedor;
- bloquea la fila antes de decidir;
- construye metadata desde la fila, nunca desde el payload;
- solicita un grant `WRITE` al almacenamiento;
- resuelve el material temporal en una frontera separada;
- devuelve URL, método, headers y expiración solo en la respuesta HTTP;
- nunca registra URL, firma o secreto.

### Verificación

- bloquea la fila;
- exige que `row.object_key` coincida con la dirección canónica derivada antes
  de consultar el almacenamiento;
- permite reintento;
- consulta `stat` mediante la dirección canónica;
- objeto ausente: conflicto reintentable, sin cambio de estado;
- metadata exacta: `verified` y `verified_at` UTC;
- metadata inválida o divergente: `quarantined`;
- `verified` exacto repetido: no-op;
- `retired`: conflicto irreversible.

### Cuarentena y limpieza

La cuarentena se persiste antes de intentar limpieza lógica. El retiro del objeto
es idempotente y puede reintentarse sin volver a habilitar el activo.

Si la limpieza falla, el activo permanece `quarantined`; una nueva operación de
limpieza o retiro puede completar la compensación.

### Retiro

El objeto se retira primero. Después se persiste el estado `retired`.

Si el objeto ya no existe, el retiro del almacenamiento se considera un no-op
idempotente y se completa el estado DBI. Una indisponibilidad real del proveedor
continúa siendo un error y no modifica la fila.

Si el commit falla después del retiro, el reintento observa que el objeto ya
está retirado, acepta el no-op del almacenamiento y completa el estado DBI.

## Contratos previstos

### Registro

Entrada:

- `asset_id`;
- `plot_id` opcional;
- `asset_kind`;
- `content_type`;
- `size_bytes`;
- `sha256`;
- `crs` opcional.

Salida:

- datos públicos seguros del activo;
- indicador `created`.

### Transferencia temporal

Salida efímera:

- `grant_ref`;
- `method`;
- `url`;
- headers obligatorios;
- `expires_at`.

La respuesta debe evitar `repr`, auditoría o logs con URL y headers.

### Verificación y retiro

Salida:

- estado seguro del activo;
- indicador de cambio o no-op;
- ninguna ubicación interna del objeto.

## Servicios y transacciones

El servicio de dominio:

- recibe sesión, repositorio y almacenamiento explícitos;
- no abre sesiones;
- no llama `commit`;
- no lee variables de entorno;
- no importa FastAPI;
- no devuelve `HTTPException`;
- serializa decisiones mediante locking de fila;
- devuelve resultados deterministas o errores de dominio.

La frontera HTTP:

- autoriza;
- traduce contratos;
- controla `commit`, `rollback` y `refresh`;
- normaliza 404, 409, 422 y fallos temporales;
- no construye `object_key` manualmente.

## Extensión de almacenamiento

`DBIPrivateObjectStore` entrega una concesión opaca. La API necesita resolverla
sin depender de `DBIS3ObjectStore`.

Se definirá un protocolo separado de resolución temporal. Este protocolo puede
ser implementado por S3 y sustituido por un doble en pruebas. La URL no se
convierte en parte del dominio persistido.

## Endpoints previstos

```text
POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/assets
POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/assets/{asset_id}/upload-grant
POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/assets/{asset_id}/verify
POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/assets/{asset_id}/retire
```

Las rutas GET existentes permanecen sin cambios y no exponen `object_key`,
SHA-256 o referencias del creador.

## Pruebas obligatorias

### Offline

- contratos estrictos y `extra=forbid`;
- campos controlados por el servidor ausentes del payload;
- dirección canónica derivada;
- reintento exacto y duplicado divergente;
- autorización de finca y lote;
- 404 no enumerable;
- locking y concurrencia;
- transiciones válidas e inválidas;
- objeto ausente;
- metadata exacta o divergente;
- grant solo para `registered`;
- URL ausente de estado, modelos y logs;
- rollback de base;
- compensación y retiro repetido.

### Integración

La automatización `DBI asset integration` ejecuta y mide el ciclo conjunto sin
infraestructura persistente ni datos reales.

- PostgreSQL/PostGIS efímero con rol API mínimo;
- SeaweedFS efímero y datos sintéticos;
- registro, grant, carga, verificación y retiro;
- intento transversal por tenant/finca/lote;
- carga incompleta y recuperación;
- fallo de commit simulado después del retiro;
- ausencia de residuos persistentes;
- métricas de latencia, operaciones, bytes, conflictos y recuperación.

## Fuera de alcance

- `AnalysisArtifact`;
- trabajos y comandos;
- cola y worker;
- ejecución geoespacial;
- publicación de resultados;
- frontend;
- datos reales;
- proveedor productivo;
- eliminación física;
- producción o staging remoto.

## Regla de avance

El Draft PR debe existir antes del código funcional. Cada subhito tendrá diff,
SHA y GitHub Actions auditados. El PR no se marcará listo hasta completar
servicio, API, integración, documentación y revisión final.