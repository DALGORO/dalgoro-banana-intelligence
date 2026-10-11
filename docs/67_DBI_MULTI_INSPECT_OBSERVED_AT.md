# DBI-MULTI-001 · Fecha de observación INSPECT verificada (Hito 11)

## Problema de integridad temporal

El PR #203 ya permite consultar hasta 20 extracciones multiespectrales
por lote, pero únicamente devuelve `created_at`, que es **la fecha de
persistencia de la extracción**, no la fecha de observación de campo
ni la fecha de captura aérea. La extracción no contiene un
`campaign_id` atribuible de manera inequívoca al producto científico.

Para evitar mezclar esas fechas, este microhito incorpora la
**fecha observada de la versión INSPECT real** al contrato HTTP,
sin adjudicar Campaign o fecha de vuelo por proximidad temporal.

## Contrato de lectura

Los dos GET `/multispectral-extractions` y
`/multispectral-extractions/{extraction_id}` siguen exigiendo
`DBIPermission.READ` con tenant, organización, finca y lote exactos.
Las respuestas incluyen ambos:

- `observed_at`: fecha `datetime` con zona horaria del registro
  inmutable `DBIFieldObservationVersionRecord.observed_at`, siempre
  identificada como **observación de campo**.
- `created_at`: fecha de registro de la extracción derivada,
  sin utilizarla como fecha del vuelo.

`observed_at_by_extraction_scoped` hace **una sola consulta por lote**,
limitada a 20 IDs distintos, y usa JOIN entre extracciones MULTI,
versiones INSPECT **observadas** y su registro padre. Las igualdades
exigen ID de observación y versión, tenant, organización, finca y lote
a ambos lados. La ausencia de coincidencia, un timestamp sin zona
horaria o evidencia inválida producen **HTTP 409** sin información
sensible. Permisos inexistentes permanecen como 404 y el catálogo
autorizado sin filas devuelve `[]`. No se modifica SQL de escritura
ni se generan datos sintéticos en el endpoint.

El panel etiqueta claramente ambas fechas en cada extracción,
mantiene las estadísticas y las limitaciones originales y advierte
que **ninguna identifica por sí sola un vuelo o Campaign**.
No se presentan cambios temporales, diferencias de índices,
diagnósticos o recomendaciones hasta disponer de una vinculación
de campaña verificable y criterios de comparabilidad científica.

## Pruebas

- `.github/scripts/ci_dbi_multi_http.py`: contrato GET y LIST,
  scope, fecha de campo distinta de `created_at`, ausencia del JOIN y
  timestamps ingenuos o corruptos deben bloquear la lectura.
- `.github/scripts/ci_dbi_multi_persistence.py`: consulta real en
  PostgreSQL/PostGIS CI que verifica `observed_at` frente a INSPECT,
  rechazo tenant/org/finca/lote cruzados y límite de IDs.
- Frontend: ESLint, TypeScript y compilación dentro del CI modular;
  las estadísticas de bandas/índices no cambian.

Sin migraciones nuevas, cambios a fórmulas ni modificaciones de la
cadena científica, S3, Render, worker GIS o producción.

## Siguiente microhito

Definir, con base en referencias existentes y sin inferencias,
una asociación explícita de producto científico con Campaign y
la fecha `captured_at` de vuelo. Solo después será legítimo
construir una comparación multifecha, haciendo coincidir ubicación,
soporte espacial, versión de fórmula, normalización/calibración y
calidad de píxeles. Es trabajo funcional de Hito 11 separado de
staging/UAT operacional Hito 13.
