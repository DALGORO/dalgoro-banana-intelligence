# DBI-MULTI-001 · Procedencia Campaign para rásteres científicos (Hito 11)

## Diseño aprobado para este microhito

La imagen de referencia del portal DALGORO es **una visualización conceptual**, no
una captura real ni una garantía de que cada capa esté desplegada. La interfaz
implementada del Hito 11 debe mostrar exclusivamente datos realmente autorizados.

Antes del cambio, las extracciones tenían fecha **INSPECT observed_at** y fecha
**created_at del cálculo**; ninguna acreditaba la fecha del vuelo. Ahora los dos
GET MULTI devuelven adicionalmente:

- `campaign_id` (UUID o `null`)
- `captured_at` (fecha de vuelo **de Campaign**, o `null`)
- `campaign_linkage`: `verified_job_chain` o `unverified`

Solo se atribuye una Campaign si existe una cadena **completa y exacta**:

`extraction.source_raster_product_id` → `dbi_raster_products.id` con
`product_kind=scientific`, `status=ready` y
`source_kind=analysis_artifact` → `dbi_analysis_artifacts.id =
raster.source_ref` y `sha256 = raster.source_sha256` →
`dbi_analysis_job_attempts` del mismo artefacto/job, `status=succeeded` →
`dbi_analysis_jobs` `status=succeeded` del mismo tenant/finca/lote →
`dbi_campaigns` con `id=job.campaign_id` y
`source_job_id=job.id`, `analysis_type=multispectral`, coincidente en
tenant, organización, finca y lote, y `captured_at` definido.

Toda consulta requiere el permiso **READ** de lote y aplica filtros SQL por
tenant, organización, finca y lote. El catálogo permanece limitado a 20
extracciones; no se buscan campañas de terceros ni se cruzan datos en memoria.

Si el ráster proviene directamente de un `input_asset`, no se puede seguir
esta cadena o hay un campo discordante, la asociación queda
**`unverified` y ambas referencias son nulas**. No se inventa una
Campaign por fechas, proximidad, nombre, UUID parecido o afinidad de imágenes.
Una fecha de vuelo sin zona horaria también se rechaza como 409. La falta de
autorización se responde 404 no enumerable.

## Interfaz de cliente

En `MultispectralEvidencePanel`, la vista muestra separadamente:
observación de campo INSPECT; registro de extracción; campaña y fecha de
captura **solo cuando el vínculo es `verified_job_chain`**.
En cualquier otro caso se muestran «Campaña no verificada» y
«Fecha de vuelo no verificada».

Las estadísticas de cuatro bandas y seis índices mantienen
`evidence_kind=derived`, soporte `copa_up` o `window` y su limitación.
**No se calcula una tendencia temporal**, no se confunden vuelos con
observaciones ni se asignan diagnósticos Sigatoka.

## Validación y despliegue

- `.github/scripts/ci_dbi_multi_http.py`: contrato de detalle/catálogo,
  vínculo ausente/consistente, fechas inválidas, autorización y scope.
- `.github/scripts/ci_dbi_multi_persistence.py`: prueba PostGIS efímera
  con Campaign, trabajo, intento, artefacto y ráster sintéticos realmente
  vinculados; negativa cruzada por tenant/org/finca/lote y manipulación de
  SHA, estado del trabajo y vínculo de Campaign. No hay información real.
- CI modular frontend y backend, y workflow real de migraciones PostGIS.
- No hay nueva revisión Alembic, cambios a los modelos científicos,
  tablas productivas, lógica YOLO/GOLD/Density/COPA_UP, S3 o worker.

**Limitación residual:** las fuentes `input_asset` y cadenas legacy que no
posean esta referencia completa permanecerán explícitamente sin verificar.
La comparación entre campañas exige **otro microhito**, con equivalencia
de ubicación/unidad productiva, calibración, soporte espacial, calidad de
píxeles y versiones de fórmulas. CI no implica staging desplegado ni UAT
con datos reales.
