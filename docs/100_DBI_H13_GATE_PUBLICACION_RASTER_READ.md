# H13 — Cerradura de lectura pública de productos RGB por Campaign

**Base auditada:** `main@92f374e`.

## Problema observado

La cronología del productor consulta únicamente Campaign `PUBLISHED` con
`approved_at` y `published_at`, pero los tres endpoints de producto
`GET /raster-products/{id}`, `GET /content` y `GET /tiles/...`
admitían cualquier producto COG `ready` con permiso READ y scope lote.
El UUID de un producto no representa autorización para publicarlo.

## Medida conservadora

Las tres rutas requieren ahora, antes de obtener metadata, rango o tile:

- producto `rgb_visual` en estado `ready`, tenant/finca/lote exactos;
- referencia de fuente `source_kind`, `source_ref` y `source_sha256`
  coincidentes con un `DBICampaignArtifact` de tipo `orthophoto_source`
  y versión técnica `current`;
- Campaign del mismo tenant, organización, finca y lote, con análisis técnico
  y estatus `PUBLISHED`, `approved_at` y `published_at` no nulos.

Sin vínculo inequívoco, responder 404 y **no consultar Storage ni renderer**.
Se evita inferir autorización por fecha de vuelo o nombre de archivo.

**Caveat del esquema vigente:** el campo `DBICampaignArtifact.published`
se crea en `false` y la transición de Campaign no lo actualiza; por ello
este gate utiliza la autoridad de Campaign `PUBLISHED` y el artefacto
técnico `current`, igual que la cronología existente. No atribuirle una
aprobación individual que el esquema todavía no certifica.

Los productos `scientific` permanecen accesibles a servicios internos
privados con sus controles propios, pero **no se entregan por estas tres rutas
READ**. Antes de publicar los seis índices se necesita un nuevo contrato
que vincule cada índice, archivo científicamente validado, estilo original,
QA y aprobación institucional, sin abrir directamente el COG maestro.

## Impacto / validación

- Ningún cambio en modelos, datos o migraciones, fórmulas, servicios de
  generación COG o políticas de Google.
- Las pruebas existentes del renderer científico se conservan como pruebas
  **unitarias bajo mocks**; no equivalen a autorización de acceso HTTP real.
- CI HTTP: 404 para metadata/range/tile de productos no publicados y no
  consulta de almacenamiento/renderer; inspección del SQL para identidad,
  scope y marcadores institucionales.
- El endpoint no se destina a revisión técnica preliminar. Cualquier futura
  ruta de revisión privada requiere autorización distinta y explícita.

Sin despliegue Render ni intervención en sistemas productivos.
