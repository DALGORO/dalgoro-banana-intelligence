# DBI-CLIENT-VIEW-004 · Diseño DALGORO aprobado, integración visual fase 1 (Hito 11)

## Decisión de diseño

El cliente aprobó la composición conceptual inspirada en su CRM DALGORO,
con identidad corporativa petróleo/cobre, logotipo PNG, mapa geoespacial
protagonista, evidencia multiespectral, controles de campaña y diseño adaptable.
La imagen generada es **objetivo visual**, no captura de una aplicación
real, ni demostración de datos científicos. Se mantiene como antecedente
`docs/69_DBI_CLIENT_VISUAL_TARGET_AND_MULTI_HISTORY.md`, junto a la
sincronización `docs/70_DBI_CLIENT_MAP_MULTI_CAMPAIGN_SYNC.md` y el
aislamiento por ámbito `docs/71_DBI_CLIENT_VIEW_SCOPE_BOUNDARY_AND_VISUAL_QA.md`.

## Implementación acotada, sin tocar dominio

- `AppShell.tsx` utiliza los PNG existentes
  `public/logo-white.png` y un aspecto corporativo solo en vistas cliente
  `/portal` y mapas DBI; no crea opciones de menú sin rutas válidas.
- `dbi-client-view.css` determina el aspecto petróleo/cobre, tarjetas y
  distribución: columnas de controles y mapa en pantallas intermedias;
  controles, mapa y MULTI juntos en escritorio ancho (≥1560 px);
  una columna adaptable en móvil (≤767 px).
- `FarmMapTimeline.tsx` mantiene los controles de fechas/capas,
  la cartografía real y las restricciones por Campaign y scope; muestra
  el número de capas **de la selección actual**, no estadísticas
  simuladas. La gestión de publicaciones se presenta en `details`
  plegable, **solo cuando `canPublish` es verdadero**. No cambia
  autorización del backend.
- `MultispectralEvidencePanel.tsx` conserva el historial acreditado,
  los selectores y las tablas con fuente y soporte, y suma tarjetas
  de **medianas de índices derivados persistidos**. Sin valor válido,
  el componente muestra la ausencia real. No hay tendencias, barras
  multifecha, mapas NDVI artificiales ni diagnósticos automáticos.
- `tests/dbiClientVisualLayout.test.mjs` verifica invariantes
  estructurales; CI Node 24 también ejecuta las pruebas científicas
  existentes, TypeScript, lint, Vite y demás workflows aplicables.

## Diferencias deliberadas frente al mockup aprobado

| Elemento del mockup | Resultado de esta fase |
| --- | --- |
| Menú lateral corporativo | Estilo DALGORO sobre rutas reales accesibles |
| Controles, mapa y panel a la derecha | Tres columnas solo en pantallas anchas |
| Mapas coloreados NDVI/NDRE/GNDVI | **No añadidos**: requerirían producto georreferenciado aprobado |
| Tarjetas de índices | Mediana real de cada resumen derivado, sin minigráficos |
| Histórico en línea temporal con miniaturas | Franja desplazable de Campaign verificadas, sin fotos fabricadas |
| KPIs de campañas, lotes, superficie o extracción global | **No añadidos**: no hay contrato READ que acredite esas cifras |
| Comparación de vuelos y recomendación agronómica | **No implementadas**, pendientes de validación científica |
| Marca DALGORO | Se reutilizan PNG versionados; revisión final de fidelidad a manual de marca, pendiente |

## Aceptación y límites

Comprobar en navegador con permisos reales o entorno UAT autorizado:
1440/1280 px (dos columnas), 1600/1920 px (tres columnas),
390/768 px (móvil), cambios de lote y tenant, 0/1/muchas campañas,
fecha con varias Campaign, ausencia de raster RGB,
401/403/404/409, extracción no verificada, teclado/foco,
modo claro/oscuro y roles READ vs MANAGE.

El test Node y la compilación demuestran integridad de código,
**no prueban el aspecto exacto ni la experiencia de un navegador**.
Se requieren capturas reales y revisión de diseño para declararlo
equivalente al mockup. No se ha realizado despliegue ni UAT.
No se modifican Python, PostGIS, migraciones, S3/Render,
endpoints ni GOLD/YOLO/COPA_UP/Density o fórmulas espectrales.
