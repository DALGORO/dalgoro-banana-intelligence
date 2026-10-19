# UX productor · Fase 3 — guía de fuentes del vuelo en el mapa

## Propósito

Ayudar al productor bananero a distinguir **fotografía RGB**, **capas GIS** y **estadísticas de seis índices** usando exclusivamente datos de la Campaign consultada. El panel es desplegable para no desplazar el mapa en teléfonos.

## Cambios acotados

- `FarmMapTimeline.tsx`: panel `<details>` dentro de `dbi-map-view`, condicionado por `realLocator`.
- **Sin vuelo exacto** (`selectedVisit` ausente) no se muestra ninguna disponibilidad; en fechas con múltiples Campaign se pide elegir una concreta.
- **RGB**: usa `selectedVisit.hasRgb` y los controles `displayEntries`/`rgbOverlayVisible` existentes; distingue disponibilidad de activación y no asegura que los mosaicos se hayan descargado.
- **GIS**: `visibleVectorMeta` se origina en `activeCampaignIds` del vuelo y catálogo ya autorizado; cuenta solo elementos seleccionados, no asegura descarga o representación gráfica. Si falla el catálogo, no se reporta ausencia.
- **MULTI**: enlace a la pestaña existente; recuerda que los seis mapas temáticos individuales permanecen sin habilitar y que las estadísticas pueden consultarse únicamente cuando haya resultados autorizados.
- CSS en `farm-map-layer-guide.css` aislada, estilos accesibles, foco de teclado, mínimo 44 px, oscuro y móvil.
- Test de contrato dentro de `tests/clientMapQuickActions.test.mjs`, que el CI ya ejecuta.

## Barreras

No cambian `getPlotMapTimeline`, `producerMapVisits`, `chooseMapVisit`, fechas, permisos READ/MANAGE, endpoin⁠ts, servicios GIS, publicación, PostGIS, S3, TIFF, grants ni cálculos científicos. No se incluyen diagnósticos de salud vegetal ni capas ficticias.

## Criterios

1. Pruebas de contrato Node, lint y TypeScript/Vite sin regresión.
2. Ninguna salida positiva si `loading`, `error` o `selectedVisit` ausente.
3. El visor original y sus controles siguen montados; el panel permanece cerrado inicialmente.
4. Revisión visual manual posterior en teléfono y escritorio.
5. PR en borrador contra `main`, separado de los PR UX #280/#281 y de H14 hasta #279. No fusionar ni desplegar sin autorización.

**Incidencia ajena al diff:** Gitleaks puede señalar el mismo commit histórico exploratorio H14/3H señalado en #280/#281; mantener el bloqueo y no eliminar el escaneo.
