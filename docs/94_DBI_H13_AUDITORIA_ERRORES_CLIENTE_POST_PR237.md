# Auditoría de errores — Portal DBI del productor (posterior a PR #237)

Fecha de auditoría de código: 16-oct-2026 (Ecuador).
Base revisada: `main@f5e7bbe6cc680ee1a46a391892ecd11cbbd2bea6`.
**Alcance:** lectura de código GitHub conectado, contratos frontend/API, smoke/CI de main y selectores.
No hubo acceso autenticado al despliegue de Render, consola del navegador, datos reales de fincas ni pruebas táctiles con productores. **No afirmar que lo aquí hallado ya ocurrió en producción.**

## Resultados confirmados

| Código | Severidad | Hallazgo | Fuente | Estado |
|---|---|---|---|---|
| MAP-A01 | Alta | La respuesta tardía de `getPlotMapTimeline` restablecía `selectedDate`, `specificMapCampaign` y `comparisonDate` después de una elección manual posible desde el historial GIS cargado previamente. | `pages/FarmMapTimeline.tsx`, efecto del `request.then` y `chooseMapVisit`. | **Corregido en este PR**: las rutas scoped esperan a la selección por identidad exacta de `mapVisits`; la respuesta RGB ya no pisa la elección del cliente. |
| MAP-A02 | Media | Clientes READ hacían `GET /map/gis-imports` aunque el backend exige MANAGE y oculta originales privados a lectores. La excepción se ignoraba. | `FarmMapTimeline.tsx`, `dbi_portal_gis_imports.py` `list_gis_imports`. | **Corregido en este PR**: el GET de originales solo se solicita si `canPublish` realmente es true (servidor sigue autorizando). |
| MAP-A03 | Media | «Todas las fechas» inducía a pensar que el mapa permite superponer levantamientos; el diseño actual requiere seleccionar exactamente uno. | `FarmMapTimeline.tsx`, selectores móvil y lateral. | **Corregido en este PR**: «Elegir un levantamiento». |
| MAP-A04 | Media | «Comparar con» ofrecía un selector habilitado sin un antes/después cartográfico implementado. | `FarmMapTimeline.tsx`. | **Corregido parcialmente en este PR**: se deshabilita el selector y se rotula «próximamente». No existe comparación nueva. |
| MAP-A05 | Alta | Si falla una descarga en `Promise.all(toLoad.map(getVectorLayer))`, no se guardan tampoco otras respuestas buenas del lote ni se comunica al cliente el error. | `FarmMapTimeline.tsx`, carga `visibleVectorMeta`. | **Pendiente**: manejar por capa, estado de fallo e intento explícito, sin bucles de reintentos ni mezcla entre tenant/lote. |
| MAP-A06 | Alta | Si hay clave Google Maps pero la librería falla al cargar, `GoogleSatelliteViewer` solo muestra error; no existe transición automática segura a MapLibre. | `GoogleSatelliteViewer.tsx` / `FarmMapTimeline.tsx` `useGoogleBase`. | **Pendiente**: fallback y pruebas en navegador; no basta con que `VITE_GOOGLE_MAPS_API_KEY` exista. |
| MAP-A07 | Media | El historial RGB/GIS está limitado por `GET /vector-campaigns` y `GET /vector-layers`, que usan `limit(100)`; el usuario no tiene paginación. | `dbi_portal_vectors.py`, `producerMapVisits.ts`. | **Pendiente**: historial paginado por Campaign y fecha, nunca deducir identidad por proximidad. |
| MAP-A08 | Media | El historial de índices recorta **20 extracciones**, no 20 vuelos, por lo que un levantamiento con muchas muestras puede desplazar anteriores. | `dbi_multispectral.py`; `multispectralCampaignHistory.ts`. | **Pendiente**: vista específica por campañas verificadas paginada. |
| MAP-A09 | Media | El UI considera «capa visible» datos descargados, pero cuando no hay tile RGB autorizado o el request falla, no se distingue de fondo satelital de Google; no hay indicador por tile. | `GoogleSatelliteViewer.tsx` (`fetch` ignora !ok/content-type) y `FarmMapTimeline.tsx`. | **Pendiente**: mensajes de carga/estado reales y separación inequívoca entre fondo satelital y ortofoto del vuelo. |
| MAP-A10 | Media | Los popups vectoriales muestran hasta 15 nombres de atributos GIS crudos; la comprensión para el productor no fue comprobada. | `gisPresentation.ts`, `createGISFeatureDetails`. | **Pendiente**: etiquetas legibles y ocultar atributos técnicos opcionalmente. |
| MAP-A11 | Media | Solo hay ortofotos RGB reales en `plot/map/timeline` y estadísticas MULTI, no mapas NDVI/NDRE georreferenciados con leyendas verificadas. | `dbi/map_timeline.py`, contrato `RasterTileTimelineEntry`. | **Funcionalidad pendiente**, no se debe inventar mapas de salud. |
| MAP-A12 | Media | El CI comprueba lint, compilación, contratos, helpers y PostGIS, pero no demuestra accesibilidad visual en móviles, Google Maps real o uso en una sesión de productor. | `frontend/tests`, `.github/workflows`. | **Pendiente**: pruebas de navegador con cuenta cliente y ambiente controlado. |
| MAP-A13 | Información | El commit en GitHub y CI verde no prueban un deploy a Render. No se ha encontrado/consultado un despliegue autenticado en esta auditoría. | GitHub Actions `main` (CI, migraciones, scans), configuración del frontend. | **Despliegue no verificado**. No realizarlo sin autorización expresa. |

## Protección del alcance

Este PR no altera YOLO, Sigatoka, COPA_UP, densidad, fuentes científicas, endpoints, JWT, roles, PostGIS ni migraciones. Mantiene el `campaign_id` exacto para la trazabilidad. El servidor sigue validando READ/MANAGE.

No confundir imágenes de diseño generativas con capturas renderizadas del navegador. Toda maqueta que muestre mapa de calor NDVI, «cultivo sano», porcentaje de plantas, tratamiento o rendimientos debe identificarse como conceptual, no como salida implementada.

## Siguiente orden sugerido

1. **A05**: descargas GIS independientes y errores visibles, con test de fallo parcial y reintento.
2. **A06 + A09**: tolerancia a fallos de mapa y separación mapa base Google vs ortofoto del vuelo, con navegador real.
3. **A07 + A08**: paginación por fecha/Campaign con identidad exacta, sin saltos o truncamiento oculto.
4. **A10 + A12**: pruebas de usabilidad móvil y ventanas cartográficas comprensibles.
5. **A11**: solo después de contar con mapas de índices científicos autorizados y comparables.

**Verificación posterior requerida:** CI 100% aprobado para SHA de PR y luego para `main`. Aprobación del CI no es una prueba de despliegue.
