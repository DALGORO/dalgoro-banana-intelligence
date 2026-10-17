# DBI · Hito 13 — Auditoría de uso para el productor bananero

**Revisión de código:** `main` @ `a821727613decab2a969fd91ae44698c8bf95c22` (16 oct 2026).  
**Tipo:** auditoría heurística y técnica de UX, contratos READ y navegación, **no** una sesión observada con productores ni un test visual en dispositivos reales. No se accedió a datos privados ni a un despliegue productivo. Las prioridades son juicios de diseño, no estadísticas de uso medidas.

## Resultado ejecutivo

DBI ya tiene catálogo autorizado de fincas/lotes, visor con ortofotos RGB reales, capas GIS, selector de fecha, extracción MULTI con procedencia verificable e INSPECT publicado por Campaign. **La interfaz no es todavía plenamente «mapa primero» ni «fecha primero» para un productor con alfabetización digital básica.**

Recorrido deseado: **Mis fincas → lote → mapa inmediatamente visible → levantamiento exacto con fecha, nombre y tipo → capa y leyenda → explicación y evidencia del sector → siguiente comprobación en campo**. Nunca inferir correspondencia entre datos por cercanía de fecha ni mostrar «sano/enfermo» desde NDVI.

## Hallazgos y prioridades (evidencia inspeccionada)

| ID | Prioridad | Hallazgo comprobado en código | Consecuencia de UX | Evidencia |
|---|---|---|---|---|
| UX-01 | **P0** | A menos de 1120 px, `dbi-visual-grid` tiene una columna y el extenso `aside.dbi-map-controls` precede al mapa en el DOM; `max-height: none` permite crecer a la lista completa. | En móvil/tablet el productor debe desplazarse por controles y capas antes de ver su finca. | `FarmMapTimeline.tsx` líneas 792, 1051; `dbi-client-view.css` líneas 190–197, 312–345. |
| UX-02 | **P0** | El primer `selectedDate` procede exclusivamente de `response.timeline` (raster), aunque las fechas de `vectorCampaigns` se agregan después. El selector «Todas las fechas» puede mezclar la última ortofoto RGB con vectores de distintas campañas. | Puede ver información geográficamente superpuesta sin una única fecha de levantamiento claramente establecida; un lote solo vectorial no inicia necesariamente en su levantamiento más reciente. | `FarmMapTimeline.tsx` líneas 278–328, 336–359, 562–572. |
| UX-03 | **P0** | El fallback MapLibre arranca con `EMPTY_MAP_STYLE` de fondo neutro. La vista satelital de Google solo se instancia si hay clave configurada; si esa carga falla, Google muestra error técnico sin cambiar de motor. | El producto «cartográfico» puede abrir en un fondo neutro o sin contexto visual cuando no hay ortofoto/capa lista. | `FarmMapTimeline.tsx` líneas 38–49, 157, 225–245, 1052–1070; `GoogleSatelliteViewer.tsx` líneas 59–79, 140–166, 246–258. |
| UX-04 | **P0 objetivo cartográfico** | La ruta `plot/map/timeline` incluye **solo** ráster `rgb_visual` como `RasterTileTimelineEntry`. NDVI/NDRE figuran en el catálogo previsto, pero sus valores se muestran en tarjetas estadísticas MULTI, no como una capa temática cartográfica habilitada por esa ruta. | El productor ve números de índices sin saber **en qué zona** del lote investigar. | `dbi/map_timeline.py` líneas 19–29, 195–260; `schemas/dbi_map.py` tipo `RasterTileTimelineEntry`; `MultispectralEvidencePanel.tsx` sección `dbi-index-grid`. |
| UX-05 | **P1 confianza** | Una ortofoto RGB puede entrar en timeline desde `DRAFT` o `PROCESSING`. El backend envía `professional_review_status`, pero el visor actual no lo muestra junto a la imagen. | El usuario puede interpretar «imagen visible» como «resultado validado». | `dbi/map_timeline.py` líneas 30–53, `_review_status`; `FarmMapTimeline.tsx` render del mapa. |
| UX-06 | **P1** | El control «Comparar con» permite elegir segunda fecha, pero solo muestra un texto de funcionalidad futura; no dibuja un antes/después real. | Expectativa comercial incumplida y pérdida de confianza. | `FarmMapTimeline.tsx` líneas 706–712, 1026–1048. |
| UX-07 | **P1** | Las opciones muestran solo `toLocaleDateString("es-EC")`. Campañas en un mismo día con horas diferentes pueden aparecer con rótulos iguales aunque sus UUID sean distintos. La selección exacta vive en otro panel. | Confusión entre fecha, vuelo y producto; dificulta seguir visitas consecutivas. | `FarmMapTimeline.tsx` líneas 54–59, 753–823; `MultispectralEvidencePanel.tsx` historial verificado. |
| UX-08 | **P1** | El popup GIS imprime hasta 15 nombres de campos técnicos crudos; no hay una leyenda universal compacta incrustada en el mapa con significado, fecha, fuente y estado. Las etiquetas por capa se presentan en la barra lateral. | El productor debe traducir códigos GIS y colores, y no recibe una lectura guiada del sector pulsado. | `gisPresentation.ts` `createGISFeatureDetails`; `FarmMapTimeline.tsx` líneas 856–885, 617–680. |
| UX-09 | **P1** | El historial MULTI deriva de una lista READ limitada a **20 extracciones recientes**, no 20 vuelos; un vuelo con muchas muestras desplaza campañas anteriores. El selector enumera «Vuelo 1/2» según el resultado actual. | Historial incompleto y numeración inestable cuando llegan muestras nuevas; no sirve como archivo temporal duradero. | `dbi_multispectral.py` función `list_multispectral_extractions`; `multispectralCampaignHistory.ts` `items.slice(0,20)`; `MultispectralEvidencePanel.tsx` `verifiedHistory.map`. |
| UX-10 | **P1** | Las capas GIS se solicitan en `Promise.all`; una excepción se descarta silenciosamente. Los contadores de GIS se calculan desde metadatos, aunque la capa no esté activada o no se haya descargado. | El usuario puede creer que una capa está visible cuando falló o se desactivó. | `FarmMapTimeline.tsx` líneas 366–390, 746–749; `FarmTrackingPanel.tsx` cifras desde `associatedGISLayers`. |
| UX-11 | **P1** | Pestañas «Evidencia MULTI», conceptos Fouré/YLS/NDRE, «soporte», píxeles, fecha de observación/registro y múltiples bloques técnicos siguen dominando el detalle. | Es una ficha de evidencia rigurosa, pero no responde con prioridad «qué cambió, dónde y qué debo verificar». | `AppShell.tsx`, `MultispectralEvidencePanel.tsx`, `FarmTrackingPanel.tsx`, `ApprovedInspectionCampaignPanel.tsx`. |
| UX-12 | **P2** | Inicio muestra tarjetas textuales y botón «Ver mapa» por lote, sin miniatura cartográfica, fecha del último levantamiento ni resumen de material disponible. | Para varias fincas el productor debe abrir una por una para descubrir qué hay de nuevo. | `ClientPortal.tsx` tarjetas de fincas/lotes. |
| UX-13 | **P1 verificación** | Tests frontend inspeccionados validan contratos, coincidencias de texto y helpers, más lint/build. No equivalen a recorrido real táctil ni test con productor; no se encontró evidencia de UAT del perfil objetivo en esos tests. | El CI en verde **no valida comprensibilidad, tamaño táctil ni facilidad para llegar al mapa**. | `frontend/tests/dbiClientVisualLayout.test.mjs`, `frontend/package.json`. |

**Distinciones obligatorias:** un `viewport_bounds` no equivale a un polígono visible; no prometer límites de la finca sin geometría explícita. Un índice estadístico no equivale a un mapa de ese índice ni a una enfermedad diagnosticada. `comparison.enabled` solo informa que hay dos fechas, no que una comparación gráfica funcione.

## Diseño funcional recomendado: una sola pantalla principal

1. **Cabecera compacta:** «Finca [nombre] · Lote [nombre]», acceso «Volver a mis fincas» y fecha del levantamiento. Mostrar siempre origen: vuelo RGB, GIS de densidad, INSPECT publicado, derivación MULTI.
2. **Mapa como protagonista:** visible antes del panel de filtros incluso en móvil, con límites del lote solo si su geometría se obtuvo de fuente autorizada. Sobre el mapa: nombre del levantamiento, fecha y estado *imagen capturada / revisión técnica / resultado publicado*. Fallback cartográfico explícito, sin fondo satelital ficticio.
3. **Barra de tiempo inmediata:** botones «Anterior», «Siguiente» y «Elegir levantamiento» con fecha **y hora/tipo/nombre** para desambiguar; selección por Campaign ID legítimo, no correlación temporal. No superponer fechas distintas sin modo deliberado y leyenda clara.
4. **Capas comprensibles y leyenda:** «Fotografía del vuelo», «Límites», «Plantas», «Densidad por sector», «Observaciones verificadas» y, **solo cuando exista infraestructura cartográfica real y validada**, «Mapa NDVI/NDRE». Estados *Disponible / Aún sin publicar / No cargado*.
5. **Ficha del punto o sector seleccionado:** «Dónde», «Qué capa y fecha», «Qué valor observado/derivado», «Qué significa con cautela», «Qué falta verificar en campo». Opciones de ampliar detalles técnicos, no mostrarlos primero.
6. **INSPECT separado pero conectado:** resultados únicamente aprobados/publicados por Campaign y dentro del lote autenticado; faltantes como *No medido* o *No publicado*, jamás normalidad.
7. **Decisión asistida, no diagnóstico automático:** destacar áreas para **comprobación técnica** solo con evidencia georreferenciada y criterios validados; no sugerir fungicidas, dosis, rendimientos o diagnósticos a partir de NDVI, colores o estadística aislada.

### Reglas de trazabilidad entre levantamientos

- Usar la identidad exacta `(tenant, organization, farm, plot, campaign_id)` y `captured_at` con zona horaria; preservar clase de evidencia, procedencia y revisión.
- Dos Campaign con misma fecha no pueden fusionarse en una; la UI debe permitir distinguirlas.
- «Último levantamiento» debe ser el último **autorizado y con información pertinente al mapa**, no simplemente la última extracción creada ni la última fecha disponible de un solo servicio.
- El modo «Todas las fechas» debe ser un **listado de historia**, no superponer sin aviso productos de distintos momentos.
- Una evolución de NDVI/NDRE solo podrá presentarse como cambio cuantitativo cuando esté verificada la comparabilidad de productos/calibración, unidades espaciales y fórmulas. Sin esa validación, mostrar fechas una a una, no flechas de «mejoró/empeoró».

## PR incrementales sugeridos

| PR propuesto | Alcance conservador | Criterio de aceptación |
|---|---|---|
| **H13-A: mapa primero responsive** | Reordenar solo layout de `FarmMapTimeline.tsx` y `dbi-client-view.css`: fecha breve → mapa → controles plegables → evidencias. Mantener roles y componentes. | A 360/390/768 px, el mapa llega sin atravesar el listado completo de capas; controles accesibles por teclado y táctil. |
| **H13-B: cronología unificada por Campaign** | Presentación read-only que reúna fechas verificadas de RGB/vector/MULTI según contrato; IDs exactos; selección sin mezclas. Sin tocar GIS científico. | Día con dos vuelos es distinguible; vector-only elige fecha real; anterior/siguiente actualizan mapa y ficha juntos; «Todas las fechas» no mezcla capas. |
| **H13-C: leyenda y confiabilidad** | Identificar procedencia, estado profesional, carga de capas, errores y detalle GIS legible; opciones tecnológicas de base cartográfica sin inventar cartografía. | El cliente distingue «dato capturado» frente a «publicado», sabe por qué falta una capa y puede reintentar. |
| **H13-D: información para decisiones** | Tarjeta contextual «qué estoy viendo / qué puede significar / qué verificar» a partir de hechos publicados, con detalle técnico plegable. | No se crean semáforos de salud ni recomendaciones terapéuticas automáticas. |
| **H13-E: mapas temáticos y comparación auténtica** | Solo con fuentes raster NDVI/NDRE verificadas y autorizadas, implementar capas reales, leyenda/unidades y comparación temporal científicamente comparable; mientras tanto ocultar la promesa de comparar. | Pruebas reales del raster por Campaign, sin mock, falsos mapas de calor ni correlación por fecha. |
| **H13-F: histórico paginado y UAT** | Navegación segura por Campaign más allá del tope de 20 extracciones; pruebas con datos reales autorizados y usuarios con baja familiaridad digital. | Historial completo paginado y métricas observables de tareas en móvil, tableta y escritorio. |

## Aceptación de experiencia (objetivos futuros, NO mediciones)

En sesión de usuario con productor, pedir sin instrucciones previas:
- Abrir su lote y localizar su mapa; confirmar que reconoce la fecha y la fuente.
- Pasar al levantamiento anterior, regresar al más reciente y explicar qué producto está viendo.
- Identificar una capa disponible, consultar un sector en el mapa y decir qué significa y qué **no** se puede concluir de ella.
- Localizar una observación INSPECT publicada; interpretar correctamente «No medido» o «Sin resultados publicados».
- Recuperarse de un fallo de conexión y encontrar el mapa nuevamente.

Criterios meta sugeridos: al menos 4/5 tareas completadas sin ayuda por el 80% de participantes; ningún usuario deduce un diagnóstico de ausencia de evidencias; ninguna mezcla de Campaign entre tenant/lote/fecha; verificación visual en 360, 390, 768 y 1280 px, lectores de pantalla/teclado y carga de capas lenta/fallida. **No atribuir estos resultados al producto hasta medirlos.**

## Límites de esta auditoría

No se utilizaron credenciales reales de productores ni se abrió el despliegue productivo, no se inspeccionaron pantallas renderizadas ni se hizo un estudio presencial. Conclusiones formuladas como problemas de implementación se basan en el código inspeccionado; impacto sobre personas y metas requieren validación de usabilidad. **No realizar despliegues, migraciones, cambios en ML/GIS científico ni cambios de seguridad en este documento.**
