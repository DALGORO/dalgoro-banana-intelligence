# UX Productor · Fase 1 — entrada clara a fincas y lotes

## Objetivo

Iniciar la evolución visual comercial del portal DBI sin bloquearla por las pruebas H14 de conciliación SQL/S3. Este PR es independiente de H14 y tiene base `main`; no habilita carga TIFF ni cambia permisos.

## Cambios de alcance mínimo

- Portal `/portal`: enlace principal `Explorar mis fincas` que desplaza a la lista ya autorizada (sin navegación externa).
- Búsqueda de finca/lote con etiqueta explícita, iconografía decorativa, botón de limpieza existente, mejor distribución móvil y recuento vivo de resultados.
- Visualización de códigos **reales** de fincas y lotes cuando el backend los proporciona, sin datos ficticios, inferidos ni nuevos endpoints.
- Respetar la fuente existente `/api/v1/dbi/portal/accounts`, el filtro `filterClientPortalFarms`, los controles READ y la ruta `mapLink`.
- Sin cambios a `FarmMapTimeline.tsx`, capas, Campaign, S3, SQL, control de fechas, autorización ni publicación.

## Criterios de revisión

1. Conserva enlaces al mapa exacto del lote/tenant autorizado y ningún lote adicional.
2. Los recuentos solo utilizan `farms` y `visiblePlots` filtrados; errores y carga muestran mensajes existentes, nunca cifras inventadas.
3. El acceso principal, la búsqueda y el botón de limpiar ofrecen foco de teclado, dimensiones táctiles y adaptación móvil, también en modo oscuro.
4. La documentación y los tests Node siguen prohibiendo archivos, grants, capas inventadas y publicación desde el cliente.
5. Ejecutar CI frontend (Node + lint con línea base existente + build). Validación visual real en móviles/productores requiere revisión manual; ningún test de texto la sustituye.

## Separación del cierre H14

El cierre técnico H14 y la habilitación operativa de cargas son independientes de esta mejora UX. La cadena de PR apilados hasta #279 sigue pendiente de revisión/merge autorizado; #270 y #271 ofrecen implementaciones postaprobación que se solapan. Para el SHA de seguridad `9607e8bb4d9ebf25bb6c634a527545bc16609dce` de #269 aún no se ha confirmado CI propia. H14 conserva los bloqueos de TIFF/grants, los ensayos PostgreSQL + MinIO concurrentes y la recuperación de fallos pendientes de demostración operativa.

**No merge, migración, Render, API nueva ni habilitación de archivos científicos.**
