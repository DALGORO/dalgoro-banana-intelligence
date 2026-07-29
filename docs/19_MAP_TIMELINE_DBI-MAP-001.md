# 19 — Mapa cronológico DBI-MAP-001

## Identificación

- Ticket: `DBI-MAP-001`
- Issue: #12
- Fecha: 2026-07-29
- Rama: `feat/DBI-MAP-001-mapa-cronologico-v1`
- Base: `main` en `4abd2ae1d67114098a73f269924bcb9ad91b3779`
- Pull request: #13
- Estado: completado

## Objetivo

Implementar el primer corte vertical de la interfaz cronológica de mapas sin
crear persistencia, conectar servicios geoespaciales o presentar datos
simulados como evidencia.

El resultado une una ruta React protegida con un contrato FastAPI versionado.
La interfaz es operable en estado vacío y deja explícito qué capacidades todavía
no existen.

## Evidencia revisada

La revisión de `main` confirmó:

- React consume la API exclusivamente por HTTP;
- el frontend no tenía una biblioteca cartográfica ni ruta de finca;
- FastAPI montaba 12 routers, uno de ellos condicional;
- DBI disponía de configuración y Alembic aislados, pero no de modelos;
- no existían finca, lote, campaña, artefacto o hallazgo DBI;
- la arquitectura aprobada separa API, worker, PostGIS y objetos;
- el contrato conceptual usa referencias internas opacas;
- las salidas agronómicas deben conservar clasificación, fuente, confianza y
  revisión profesional.

## Riesgo controlado

| Riesgo | Barrera implementada |
|---|---|
| Confundir catálogo con datos disponibles | Cronología inicial vacía y mensaje explícito |
| Inventar resultados para llenar la pantalla | No hay geometrías, fechas, índices o métricas de muestra |
| Exponer rutas o activos privados | El contrato no contiene URL ni ruta local |
| Dependencia silenciosa de un proveedor de mapas | Estilo MapLibre local con `sources: {}` |
| Comparar campañas inexistentes | Se requieren dos fechas reales distintas |
| Presentar inferencias como observaciones | Clasificación obligatoria por entrada |
| Equivaler confianza con aprobación | Campos separados de confianza y revisión |
| Alterar la base antes del modelo | Sin ORM, migración o conexión DBI |

## Contrato HTTP

La API incorpora:

```text
GET /api/v1/dbi/farms/{farm_id}/map/timeline
```

La ruta usa la autenticación existente. `farm_id` es una referencia opaca de 1
a 128 caracteres formada por letras, números, guion o guion bajo.

La respuesta inicial tiene esta semántica:

```json
{
  "schema_version": "farm-map-timeline.v1",
  "farm_id": "internal-farm-reference",
  "status": "awaiting_data",
  "available_layers": [],
  "timeline": [],
  "comparison": {
    "minimum_dates": 2,
    "available_dates": [],
    "enabled": false
  }
}
```

`available_layers` se muestra vacío en el ejemplo para evitar duplicar el
catálogo completo. La implementación devuelve exactamente ocho entradas.

Los modelos Pydantic usan `extra="forbid"`. Una ampliación incompatible no se
acepta silenciosamente.

## Catálogo de capas

| Tipo | Etiqueta | Clasificación predeterminada |
|---|---|---|
| `rgb` | RGB | Dato observado |
| `ndvi` | NDVI | Inferencia |
| `ndre` | NDRE | Inferencia |
| `density` | Densidad | Inferencia |
| `anomalies` | Anomalías | Inferencia |
| `inspections` | Inspecciones | Dato observado |
| `production` | Producción | Dato observado |
| `sst` | SST | Dato observado |

La clasificación predeterminada describe la naturaleza usual de la capa, no
autoriza a omitir la clasificación de una entrada real.

## Trazabilidad futura

Cada `MapTimelineEntry` exige:

- identificador interno;
- tipo de capa;
- fecha de captura;
- título;
- clasificación;
- artefacto fuente;
- confianza opcional con método;
- estado de revisión profesional.

Las clasificaciones permitidas son `observed`, `inference`, `hypothesis` y
`recommendation`. La confianza no sustituye la aprobación profesional.

## Interfaz React

La ruta protegida es:

```text
/fincas/:fincaId/mapa
```

`FarmMapTimeline.tsx` incorpora:

- MapLibre GL JS 6.0.0;
- worker autocontenido mediante el patrón oficial de Vite;
- mapa interactivo con estilo local neutro;
- selector de fecha;
- filtros para ocho capas;
- selector de comparación;
- estados de carga, error y cronología vacía;
- texto explícito que impide interpretar el vacío como resultados.

La página se carga de forma diferida desde `routes.tsx` para aislar el peso de
MapLibre del resto de rutas.

No existe todavía un enlace general porque el dominio finca aún no dispone de
registros persistidos. La ruta será enlazada desde el detalle de finca cuando
ese dominio sea implementado.

## Implementación por archivo

### Backend

- `app/schemas/dbi_map.py`: contrato, enumeraciones, catálogo y constructor
  vacío.
- `app/api/v1/dbi_map.py`: endpoint autenticado.
- `app/api/v1/__init__.py`: montaje del router.

### Frontend

- `src/features/mapTimeline.ts`: tipos y cliente HTTP.
- `src/pages/FarmMapTimeline.tsx`: visor y controles.
- `src/app/routes.tsx`: ruta protegida y carga diferida.
- `src/components/AppShell.tsx`: metadatos de la página.
- `package.json` y `package-lock.json`: MapLibre 6.0.0 y dependencias
  transitivas obligatorias.

### Integración continua

- `.github/scripts/ci_map_contract.py`: contrato, seguridad, endpoint y
  coherencia Python/TypeScript.
- `.github/workflows/ci.yml`: ejecución dentro del trabajo backend.

## Validaciones locales ejecutadas

| Verificación | Resultado |
|---|---|
| Compilación Python | Aprobada |
| Contrato Pydantic y campos desconocidos | Aprobado |
| Ocho capas exactas | Aprobado |
| Cronología y comparación iniciales | Vacías y deshabilitadas |
| Ausencia de URL y ruta local | Aprobada |
| Router FastAPI aislado | Aprobado |
| ID inválido con espacios | Rechazado con 422 |
| TypeScript estricto focalizado | Aprobado |
| ESLint de archivos nuevos | Cero avisos |
| Bundling Vite y worker MapLibre | Aprobado |
| Lockfile frente a `main` | Sin actualizaciones o eliminaciones heredadas |
| Conexiones externas de aplicación | Cero |

La prueba de bundling confirmó que Vite produce un worker MapLibre
autocontenido. El tamaño del módulo cartográfico justifica su carga diferida.

## Validación remota

GitHub Actions aprobó dos ejecuciones completas:

- `30454509983`: seis de seis trabajos sobre el SHA técnico inicial
  `614a1aea`;
- `30454883303`: seis de seis trabajos sobre el SHA técnico final
  `167892a9`.

La ejecución final confirmó:

- higiene del repositorio y activos canónicos;
- frontend con `npm ci`, lint y build completos;
- backend con instalación, ambos grafos Alembic, aislamiento DBI, contrato
  cartográfico y healthcheck;
- bot de WhatsApp con instalación, compilación y smoke test;
- motor de densidad con dependencias geoespaciales, compilación, importaciones
  y CLI;
- detección de secretos sobre el historial.

## Criterios de aceptación

| Criterio | Evidencia |
|---|---|
| Ruta React protegida | `routes.tsx` y `FarmMapTimeline.tsx` |
| MapLibre sin tiles externos | Estilo local con `sources: {}` |
| Ocho capas previstas | Catálogo Python y unión TypeScript |
| Estados claros | Carga, error y vacío en la página |
| Comparación real | Dos fechas distintas obligatorias |
| Contrato estricto | Pydantic con campos adicionales prohibidos |
| Endpoint autenticado | Dependencia `current_user` |
| Sin datos simulados | `timeline: []` y comparación deshabilitada |
| CI completa | GitHub Actions `30454883303`: seis de seis |
| Estado documentado | Documentos 01, 06, 13 y 19 |

## Fuentes técnicas

- [MapLibre GL JS — Introducción e instalación](https://www.maplibre.org/maplibre-gl-js/docs/)
- [MapLibre GL JS — Paquete npm](https://www.npmjs.com/package/maplibre-gl)
- [FastAPI — Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [Pydantic — Model configuration](https://docs.pydantic.dev/latest/concepts/config/)

## Riesgos residuales

- No existe una tabla o autorización de pertenencia de finca.
- No existen campañas o fechas persistidas.
- No existe un contrato de entrega de tiles o GeoJSON autorizados.
- No existe integración con PostGIS, objetos o worker.
- El visor muestra una superficie neutra hasta que se apruebe una fuente base.
- MapLibre incrementa el peso de la ruta cartográfica.
- La clasificación predeterminada debe revisarse al incorporar cada fuente
  real.

## Exclusiones confirmadas

- No se creó ni consultó una base.
- No se creó, alteró o ejecutó una migración.
- No se habilitó PostGIS.
- No se añadieron geometrías, ortofotos, tiles o índices reales.
- No se conectó el worker geoespacial.
- No se modificaron Render, Green API o Google Sheets.
- No se modificó la lógica conversacional del bot.
- No se descargaron, actualizaron o promovieron modelos de IA.
