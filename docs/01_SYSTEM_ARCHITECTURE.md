# 01 — Arquitectura del sistema

## Estado de la decisión

La arquitectura objetivo se define en `DBI-ARC-001`. `DBI-DATA-001` implementa
la primera barrera de datos: configuración DBI validada y un entorno Alembic
independiente. `DBI-MAP-001` implementa el primer contrato HTTP y consumidor
React del mapa cronológico. `DBI-DATA-002` añade el modelo persistente mínimo
de finca, lote y campaña, todavía sin aplicar migraciones o conectar la API.
`DBI-JOB-001` establece contratos versionados y reglas puras para el futuro
trabajo geoespacial, sin cola, persistencia operativa o ejecución del pipeline.
`DBI-JOB-002` añade persistencia transaccional de trabajos e intentos en
metadatos DBI, todavía sin sesión, endpoint, cola o ejecución.

El diseño y la evidencia están en `docs/17_ARCHITECTURE_DBI-ARC-001.md` y
`docs/18_DATABASE_ISOLATION_DBI-DATA-001.md`. El corte cartográfico se documenta
en `docs/19_MAP_TIMELINE_DBI-MAP-001.md`, el dominio agrícola en
`docs/20_AGRICULTURAL_DOMAIN_DBI-DATA-002.md` y la frontera del trabajo en
`docs/21_ANALYSIS_JOB_CONTRACT_DBI-JOB-001.md`.

## Módulos existentes

| Componente | Ruta | Responsabilidad actual |
|---|---|---|
| Plataforma web | `apps/platform-web/frontend` | Interfaz React que consume la API HTTP |
| Backend | `apps/platform-web/backend` | API FastAPI importada de SST Compliance |
| Bot | `apps/whatsapp-bot` | Webhook Flask, conversación, Green API y persistencia en Google Sheets |
| Motor geoespacial | `services/banana-density` | CLI y pipeline local de análisis de ortofotos |

Los cuatro componentes continúan separados. El contrato cartográfico conecta
únicamente React y FastAPI. No conecta la API con PostGIS, almacenamiento de
objetos o el worker geoespacial.

## Arquitectura objetivo aprobada

```mermaid
flowchart TD
    UI["React / PWA"] --> API["API central FastAPI"]
    BOT["Adaptador WhatsApp"] --> API
    API --> DB["PostgreSQL / PostGIS DBI"]
    API --> QUEUE["Cola de trabajos"]
    QUEUE --> WORKER["Worker geoespacial"]
    WORKER --> OBJECTS["Almacenamiento de objetos"]
    WORKER --> EVENTS["Resultado y manifiesto"]
    EVENTS --> API
    API --> OBJECTS
```

### Plano de control

`apps/platform-web/backend` es el candidato aprobado para evolucionar hacia la
API central. Será propietario de identidad, autorización, organizaciones,
fincas, lotes, trabajos, metadatos, trazabilidad, aprobaciones y auditoría.

La adopción será incremental. Los routers, modelos y migraciones heredados de
SST Compliance no se renombran ni se conectan automáticamente al dominio
agrícola.

### Plano de procesamiento

`services/banana-density` evolucionará como worker independiente. Recibirá
trabajos versionados, procesará datos en almacenamiento temporal, publicará
artefactos en almacenamiento de objetos y devolverá un manifiesto de
resultados.

El motor no se importará dentro del proceso FastAPI y no será invocado mediante
una petición HTTP que espere a que termine el análisis completo.

### Adaptadores

- React y la futura PWA consumirán exclusivamente contratos de la API.
- El bot conservará Green API como transporte y su lógica conversacional
  mientras se construye un adaptador hacia la API.
- Google Sheets continuará como almacenamiento operativo del bot hasta un
  ticket de migración con conciliación y corte explícito.
- Después del corte, Sheets podrá ser una exportación o vista auxiliar, pero no
  una segunda fuente canónica.

## Propiedad de datos

| Clase de información | Fuente canónica objetivo |
|---|---|
| Usuarios, organizaciones, fincas, lotes y permisos | PostgreSQL DBI |
| Metadatos de campañas, trabajos y ejecuciones | PostgreSQL DBI |
| Geometrías operativas y resultados consultables | PostGIS DBI |
| Ortofotos, modelos, GeoPackage, PDF, XLSX y rásteres | Almacenamiento de objetos |
| Manifiestos, huellas y referencias de artefactos | PostgreSQL DBI |
| Estado del bot durante la transición | Google Sheets |
| Estado del bot después del corte aprobado | PostgreSQL DBI |

PostgreSQL/PostGIS no almacenará ortofotos, pesos de modelos ni otros binarios
pesados. La base conservará referencias, metadatos, huellas criptográficas,
estado y trazabilidad.

## Aislamiento de bases

- La plataforma nueva utilizará `DBI_DATABASE_URL`.
- `DATABASE_URL` heredada no se reutilizará ni reemplazará.
- Desarrollo, pruebas, staging y producción tendrán bases independientes.
- Staging y producción usarán servicios nuevos.
- El historial Alembic DBI será independiente.
- Las migraciones de producción requerirán aprobación explícita.
- La aplicación, el migrador y los lectores usarán roles separados.

`DBI-DATA-001` materializa estos controles sin aprovisionar infraestructura:

- `app/db/dbi_config.py` exige `DBI_ENVIRONMENT` y `DBI_DATABASE_URL`;
- los nombres autorizados son `dbi_development`, `dbi_test`, `dbi_staging` y
  `dbi_production`;
- `dbi_alembic.ini` utiliza exclusivamente `dbi_alembic/`;
- el historial DBI comienza en `dbi_0001_baseline`;
- la tabla de versión se denomina `alembic_version_dbi`;
- `alembic/`, `app/core/config.py` y `app/db/session.py` permanecen heredados.

La existencia de esta configuración no significa que una base, esquema, rol o
extensión haya sido creado. Cualquier migración online requiere un ticket y una
aprobación explícitos.

## Mapa cronológico v1

`DBI-MAP-001` añade dos superficies coordinadas:

- la ruta React protegida `/fincas/:fincaId/mapa`;
- `GET /api/v1/dbi/farms/{farm_id}/map/timeline`.

El endpoint devuelve `farm-map-timeline.v1`, ocho tipos de capa y una cronología
vacía. La respuesta no contiene geometrías, mediciones, URLs, rutas locales o
resultados simulados.

MapLibre GL JS se ejecuta con un estilo local neutro y `sources: {}`. La
interfaz muestra carga, error y ausencia de campañas; la comparación permanece
deshabilitada hasta que existan al menos dos fechas reales.

Este corte implementa un contrato y su consumidor. No implementa finca o lote
como tablas, autorización por pertenencia de finca, campañas, tiles, artefactos
ni procesamiento geoespacial. Esas capacidades requieren persistencia DBI y
contratos de acceso autorizados en tickets posteriores.

## Dominio agrícola v1

`DBI-DATA-002` incorpora tres tablas dentro de los metadatos exclusivos de
`DBIBase`: `dbi_farms`, `dbi_plots` y `dbi_campaigns`. Lote y campaña
referencian a finca; los códigos son únicos por organización o finca y los
estados están limitados mediante restricciones explícitas.

Los UUID se generan en la aplicación. La revisión
`dbi_0002_agricultural_domain` no requiere `pgcrypto`, `uuid-ossp` o
PostGIS. Tampoco inserta datos, crea sesiones DBI o conecta el mapa con la base.

`organization_ref` permanece como referencia opaca sin clave foránea hacia la
tabla heredada `companies`. La autoridad de organizaciones y permisos se
definirá en un ticket específico antes de habilitar acceso operativo.

## Contrato de trabajo geoespacial v1

`DBI-JOB-001` implementa `analysis-job-command.v1`,
`analysis-job-result.v1`, `artifact-manifest.v1` y
`agronomic-finding.v1`. Los modelos de la API rechazan campos desconocidos,
rutas locales, URLs de activos y manifiestos sin tamaño o huella válida.

La máquina de estados permite `accepted`, `queued`, `running`, `succeeded`,
`failed`, `cancel_requested` y `canceled`. Repetir un estado es un no-op
idempotente; reintentar desde `failed` exige autorización explícita y los
estados terminales no pueden reabrirse.

El motor de densidad incorpora un adaptador puro que valida el mismo comando
con la biblioteca estándar. No importa el backend, no resuelve activos y no
ejecuta `run_full_pipeline`. Por tanto, este corte define una frontera, no una
orquestación operativa.

## Persistencia de trabajos geoespaciales v1

`DBI-JOB-002` incorpora `dbi_analysis_jobs` y
`dbi_analysis_job_attempts` sobre `DBIBase`. La primera tabla conserva el
estado global, referencias opacas de entrada, versiones y la huella del comando;
la segunda separa cada ejecución o reintento mediante un número único por
trabajo.

La unicidad de `tenant_ref + request_id` respalda idempotencia en la base. Los
estados, números de intento, huellas y fechas tienen restricciones explícitas.
La revisión `dbi_0003_analysis_jobs` desciende directamente del dominio
agrícola y se valida solo mediante SQL offline.

La persistencia del esquema no equivale a operación: todavía no existe motor,
sesión, repositorio, endpoint, autorización, tabla de activos, cola,
almacenamiento de objetos o ejecución del worker.

## Dependencias permitidas

| Origen | Destino permitido |
|---|---|
| React / PWA | API central |
| Adaptador WhatsApp | API central y Green API |
| API central | PostgreSQL/PostGIS DBI, cola y almacenamiento de objetos |
| Worker geoespacial | Cola, almacenamiento temporal y almacenamiento de objetos |
| Consumidor de resultados | API central mediante contrato versionado |

## Dependencias prohibidas

- Frontend o bot conectándose directamente a PostgreSQL/PostGIS.
- API importando PyTorch, GDAL o el pipeline geoespacial.
- Worker escribiendo directamente en tablas de dominio.
- Frontend leyendo artefactos privados sin autorización temporal.
- Uso de rutas locales del equipo del analista como contrato entre servicios.
- Reutilización de bases, credenciales o migraciones de sistemas productivos.
- Actualización automática de un modelo Champion.

## Orden de implementación

1. `DBI-ARC-001`: arquitectura, límites y contratos.
2. `DBI-DATA-001`: configuración DBI aislada e historial Alembic independiente.
3. `DBI-MAP-001`: contrato y primera interfaz cronológica sin datos simulados.
4. `DBI-DATA-002`: persistencia mínima de finca, lote y campaña en DBI.
5. `DBI-JOB-001`: contratos v1, estados y adaptador puro del worker.
6. `DBI-JOB-002`: persistencia offline de trabajos e intentos.
7. Gestión de activos, repositorio DBI, cola y ejecución del worker.
8. Integración del dashboard y la PWA.
9. Migración controlada del bot y conciliación con Google Sheets.
10. Observabilidad, gobierno de modelos y despliegues por ambiente.
