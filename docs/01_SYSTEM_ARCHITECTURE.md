# 01 — Arquitectura del sistema

## Estado de la decisión

La arquitectura objetivo se define en `DBI-ARC-001`. Este ticket establece
límites y contratos; no integra módulos, no crea bases y no ejecuta
migraciones.

El diseño detallado y su evidencia están en
`docs/17_ARCHITECTURE_DBI-ARC-001.md`.

## Módulos existentes

| Componente | Ruta | Responsabilidad actual |
|---|---|---|
| Plataforma web | `apps/platform-web/frontend` | Interfaz React que consume la API HTTP |
| Backend | `apps/platform-web/backend` | API FastAPI importada de SST Compliance |
| Bot | `apps/whatsapp-bot` | Webhook Flask, conversación, Green API y persistencia en Google Sheets |
| Motor geoespacial | `services/banana-density` | CLI y pipeline local de análisis de ortofotos |

Los cuatro componentes continúan separados. Ninguna referencia a la
arquitectura objetivo significa que ya estén integrados.

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

Estas bases no se crean en `DBI-ARC-001`. Su implementación corresponde a
`DBI-DATA-001`.

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
2. `DBI-DATA-001`: base DBI aislada e historial Alembic independiente.
3. Esqueleto de dominio y contratos versionados en la API.
4. Orquestación asíncrona y adaptador del worker geoespacial.
5. Integración del dashboard y la PWA.
6. Migración controlada del bot y conciliación con Google Sheets.
7. Observabilidad, gobierno de modelos y despliegues por ambiente.
