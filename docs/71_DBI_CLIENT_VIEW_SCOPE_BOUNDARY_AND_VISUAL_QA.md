# DBI-CLIENT-VIEW-003 · Límite de ámbito y regresión visual pendiente (Hito 11)

## Referencias y objetivo

Las referencias oficiales siguen siendo `docs/69_DBI_CLIENT_VISUAL_TARGET_AND_MULTI_HISTORY.md` y
`docs/70_DBI_CLIENT_MAP_MULTI_CAMPAIGN_SYNC.md`. Este microhito evita que el visor
conserve temporalmente el mapa, cachés de geometrías o controles de un tenant/lote
anterior cuando React reutiliza la página al navegar entre rutas privadas.

El componente `FarmMapTimeline` ahora entrega una **key React** estable por
`tenantRef`, `organizationRef`, `farmId`, `plotId` y la alternativa legacy
`fincaId`. Al variar cualquiera, se desmonta toda la instancia
`FarmMapTimelineView`: se descartan selección temporal, `data`, catálogos GIS,
vista previa, capas de MapLibre y estados de permisos previos, y el panel MULTI
se monta de nuevo en el ámbito actual. El valor no es una credencial ni modifica
la autorización READ/MANAGE vigente en el backend.

Se evita una regresión de presentación/aislamiento al cambiar de lote mientras
se reciben respuestas de red. No se cambian consultas, contratos HTTP,
permisos, cálculos científicos ni despliegues.

## Regresión automatizada

`tests/multispectralCampaignHistory.test.mjs` incorpora una prueba de la
identidad de vista: una ruta idéntica conserva su key; variaciones en tenant,
organización, finca, lote o ruta legacy exigen key distinta. Continúan las
pruebas del PR #207 para fechas equivalentes con husos, Campaign coincidentes,
evidencia no verificada, permisos por scope y ausencia de asociaciones arbitrarias.

La prueba de key verifica la condición de remonte, **no sustituye** una
prueba E2E con navegador. Los controles frontend de Node 24, lint, TypeScript
y Vite, más el resto de GitHub Actions, son el gate de fusión.

## Matriz de aceptación visual en navegador — pendiente

Probar con datos **autorizados**, nunca sintéticos presentados como vuelos reales:

| Escenario | Observación requerida |
| --- | --- |
| Escritorio 1440 y 1280 px | Mapa principal, historial MULTI y tabla de cuatro bandas/seis índices legibles |
| Móvil 390 y 768 px | Sin solapamientos, panel desplazable y controles de fecha accesibles |
| Cambio tenant, organización, finca o lote durante carga | No aparece mapa, etiqueta, capa, estadística ni botón MANAGE del ámbito anterior |
| Dos Campaign con instante de captura idéntico | Exige ID exacto para mostrar estadísticas MULTI; no mezcla RGB/GIS |
| Campaign verificada sin RGB/GIS | Estado vacío cartográfico explícito; índices derivados preservan atribución correcta |
| Fecha de mapa sin Campaign MULTI única | Ninguna estadística se asigna a otra Campaign |
| Extracción sin cadena verificable | Consultable solo sin asociación cartográfica ni fecha de vuelo inventada |
| Respuestas 401/403/404/409 y usuario solo READ | Mensajes adecuados; ningún control de publicación |
| INSPECT, fecha de captura y fecha de extracción | Etiquetas distintas, sin cálculo de tendencia o diagnóstico |
| Interacción teclado, foco y lector de pantalla | Controles y estados accesibles sin pérdida de contexto |

Se requieren capturas del navegador y revisión de roles para declarar
equivalencia visual con la imagen aprobada. Esta tarea **no acredita UAT
real ni despliegue a producción** y mantiene pendiente la validación
científica de comparaciones multifecha.

## Alcance excluido

Sin Render, S3, PostGIS persistente, migraciones, cambios backend,
algoritmos GOLD/YOLO/COPA_UP/Density, fórmulas espectrales,
interpolaciones, diagnósticos ni inferencia de vuelo.
