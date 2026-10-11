# DBI-MULTI-001 · Lectura HTTP autorizada de extracciones derivadas (Hito 11)

## Decisión de prioridad

Tras el microhito E6, no se requiere E7 para continuar **desarrollo
funcional**. E1–E6 establecieron defensas de preparación de staging,
auditoría y un ensayo real con PostGIS **efímero CI**. Staging real,
recuperación operativa, RPO/RTO, autenticidad de evidencias de respaldo,
infraestructura S3/Render, capacidad y UAT permanecen puertas
**obligatorias de despliegue** del Hito 13, no bloqueantes del
desarrollo local del Hito 11.

Este microhito retoma el Issue #80 / DBI-MULTI-001 y expone evidencia
multiespectral persistida en un contrato HTTP de **solo lectura**.

## Nuevo contrato

```http
GET /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/multispectral-extractions/{extraction_id}
X-DBI-Tenant: <tenant autorizado>
Authorization: Bearer <credenciales del usuario>
```

El backend resuelve la identidad DBI existente y requiere permiso
`READ` sobre organización, finca y lote exactos; una denegación
devuelve 404 no enumerable. La consulta SQL exige simultáneamente
`id`, `tenant_ref`, `organization_ref`, `farm_id` y `plot_id`,
sin buscar ni listar registros de terceros.

Respuesta estricta `DBIMultispectralExtractionRead`:

- `extraction_id`: identidad determinista del derivado;
- `created_at`: fecha de persistencia inmutable;
- `payload`: `DBIMultispectralExtractionCandidate` validado;
  incluye versión INSPECT observada, fuente científica, soporte
  `copa_up` o `window`, limitación explícita de ventana,
  huella del stack y exactamente cuatro bandas más seis índices.
  Todos son `evidence_kind=derived`, no diagnóstico observado ni
  recomendación aprobada.

La ruta verifica **antes de responder**:
- firma SHA-256 del `payload_json` y su codificación canónica;
- `multispectral_extraction_id(payload)` idéntica al identificador
  solicitado y persistido;
- igualdad de tenant/organización/finca/lote, observación versión,
  ráster científico, Sampling/UP, perfil, modalidad, huella,
  recuento y naturaleza `derived` entre contrato y fila;
- validación completa de resúmenes y límites por Pydantic.

Una fila malformada/corrupta devuelve **409** con error genérico sin
exponer el contenido. No hay operaciones POST, persistencia de nuevos
datos, sesión de escritura, consulta de la ruta del COG ni descarga
de fuentes científicas.

## Validación

- `.github/scripts/ci_dbi_multi_http.py` prueba respuesta estable,
  registro de ruta GET, denegación READ inexistente, tenant/org/finca/lote,
  extracción inexistente, mutaciones de SHA/IDs/payload, correspondencia
  de fuente/versiones, y ausencia de información privada.
- `.github/scripts/ci_dbi_multi_persistence.py` extiende la prueba
  existente de SQL real en PostGIS efímero a filtros exactos
  `organization_ref` y otras organizaciones, conservando pruebas
  de persistencia append-only, INSPECT y ráster científico.
- CI modular backend ejecuta el test HTTP offline; el workflow
  multiespectral y migraciones conservan sus ensayos.
- No hay migración nueva ni cambios en índices espectrales, fórmulas,
  modelos Champion/Challenger, GOLD, YOLO, COPA_UP o científicos Density.

## Pendiente

El siguiente incremento de Hito 11 podrá conectar esta consulta con
una interfaz del dashboard agrícola y/o listar extracciones por
Campaign/versión de observación bajo límites de paginación. Cualquier
gráfico debe distinguir derivado de observado e inferido y preservar
`support_limitation`; los valores espectrales aislados no equivalen
a Sigatoka confirmada, fumigación ni predicción productiva.

Las pruebas automáticas no sustituyen la validación local con un
vuelo autorizado ni la operación de staging.
