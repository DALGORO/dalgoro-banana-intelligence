# H14 · Progreso paralelo de interfaz cliente: controles rápidos GIS junto al mapa

## Objetivo

Continuar simplificando la visualización del productor mientras la administración incorpora la recepción privada de originales GIS (PR #252).

El visor `FarmMapTimeline.tsx` muestra, **solo si existen metadatos GIS publicados y autorizados en la Campaign exacta**, una barra compacta junto al mapa:

- número de capas GIS seleccionadas versus disponibles;
- **Mostrar todas** y **Ocultar capas**, enlazados a `setVisibleGISLayers(show)` existente, sin añadir peticiones HTTP ni permisos;
- aclaración explícita de que los controles **no alteran ni ocultan la ortofoto RGB** (se conserva el control de opacidad independiente).

Los botones tienen un tamaño táctil mínimo de 44 px, indicador de enfoque visible y disposición responsiva. Las capas no disponibles no muestran una barra falsa de acciones. Cuando el conjunto publicado es vacío, el mensaje de estado vacío existente continúa siendo el contenido principal.

## Aislamiento

Las acciones se alimentan de `visibleVectorMeta` previamente filtrado por fecha/Campaign. No acceden a `managementCampaigns`, al directorio local, a los recibos GIS privados ni a índices aún no publicados. No activan NDVI/NDRE/GNDVI/EVI2/CI Red Edge/CI Green temáticos de forma ficticia. No cambian Google Maps, cálculo, almacenamiento ni aprobación.

## Prueba

`tests/clientMapQuickActions.test.mjs` comprueba controles de solo lectura, condicionamiento a GIS disponible, reutilización de selección existente, tamaño táctil y ausencia de publicación. No sustituye un test visual táctil real con productor.

No hay despliegue Render, migración ni cambio de backend.
