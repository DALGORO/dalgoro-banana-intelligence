# Hito 13 · Lectura comprensible de campañas para productores

## Objetivo comercial

La interfaz del productor debe hablar de **vuelos, muestras y seguimiento del lote**, no exigir
conocer UUID de Campaign, versiones INSPECT o productos ráster.

## Cambio de presentación

- Encabezado del visor: "Vuelo multiespectral elegido", sin prefijos de UUID ni tooltip de ID.
- Historial multiespectral: "Vuelo 1", "Vuelo 2", etc. **solo como orden de lista**
  de la consulta actual (no identificador permanente), junto a fecha real y número de muestras.
- Selector de análisis: "Muestra N", fecha de campo, fecha de registro y tipo de soporte;
  el `value` mantiene el ID real de extracción para la selección exacta.
- Resumen MULTI: procedencia científica verificada o no verificada, sin mostrar las
  claves `campaign_id`, `observation_version_id` ni `source_raster_product_id`.
- Ficha de seguimiento: distingue fecha del mapa de un vuelo específico; elimina
  la impresión del UUID y conserva la selección interna `selectedCampaignId`.
- Pequeña señal visual petróleo/cobre de **selección**, sin semáforo agronómico.

**Reglas preservadas:** la fecha no se usa para inferir identidad de una Campaign;
`onChooseVerifiedCampaign(entry.campaignId, entry.capturedAt)` y las rutas
servidor mantienen los UUID auténticos y scope por tenant/finca/lote. No se
fabrican vuelos, métricas, valores INSPECT, diagnósticos ni recomendaciones de tratamiento.

## Validación

`node --test tests/dbiClientVisualLayout.test.mjs` incluye regresiones de las
etiquetas visibles y verifica que los identificadores sigan utilizándose
internamente para elegir exactamente la Campaign y la extracción.
Conservar lint, build y los restantes GitHub Actions del commit definitivo.

No hay cambios en endpoints, consultas científicas, GIS, roles, ML,
migraciones ni producción. Esta es una mejora UX acotada; el siguiente
microhito puede mejorar jerarquía visual, diseño móvil y explicaciones de índices
sin mezclarlo con seguridad institucional INSPECT.
