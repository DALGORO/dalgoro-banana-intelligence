# DBI-PORTAL-MAP-003 — Capas GIS históricas sin ortofoto RGB

El catálogo del cliente no debe confundir **ortofoto disponible para teselas** con **campaña técnica que existe**.

## Contrato del visor
- Nuevo `GET /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/vector-campaigns`.
- Se exige sesión DBI válida y permiso `read` sobre el **tenant, organización, finca y lote exactos**. La respuesta contiene únicamente ID de Campaign, nombre, tipo de análisis, estado y fecha `captured_at` registrada. No contiene rutas de fuentes privadas, SHA, credenciales ni datos de otros lotes.
- El frontend une fechas de **Campaigns técnicas del lote** y fechas con RGB realmente disponible. La capa RGB solo se dibuja si existe su raster `ready`; no se finge un levantamiento RGB para poder visualizar datos vectoriales.
- Un gestor `manage` debe elegir la Campaign técnica correcta explícitamente en «Añadir resultado cartográfico». La validación y autorización se vuelven a aplicar en el POST.
- Capas GIS publicadas para una Campaign sin RGB se pueden activar y consultar sobre la base satelital Google si está configurada o sobre el visor neutral MapLibre. Si no existe un viewport raster, la extensión real de las geometrías proporciona el encuadre.
- El aviso de «sin datos cartográficos» no debe cubrir el mapa cuando existen capas GIS publicadas.

## Límites
- La fecha `captured_at` es la que tiene registrada la Campaign; **no afirmar que se verificó contra el vuelo** cuando fue adoptada de un legado mediante metadatos de importación. Eso exige revisión de procedencia aparte.
- Se limitan las campañas listadas a 100 entradas para evitar retornos masivos; paginación será posterior.
- Sin comparación espacial calculada, sin índices NDVI inventados, sin reclasificación ni recomputación de Density/GOLD.
- No habilita importación directa en navegador de GPKG/SHP: se usa el conversor geoespacial aislado existente en main y la carga GeoJSON autorizada.

## Verificación
- CI backend prueba el filtro por tenant, organización, finca, lote y análisis técnico, y deniega consultas de otros lotes.
- CI frontend verifica la compilación del selector de campañas y los encuadres vectoriales.
- UAT de capas reales, usuarios revocados, Campaigns antiguas y Google Maps requiere el despliegue y los datos comerciales.
