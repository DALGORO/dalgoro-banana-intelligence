# DBI · UAT Fase 6 — integración de recorrido productor (sin deploy)

## Estado y alcance

La rama `ux/producer-full-journey-preview-phase6` integra **los incrementos UX #280–#284 en una sola base de revisión**, sin fusionar ninguno a `main`. Parte de #284, que contiene la Fase 4 de #283, y aplica los cambios de #280, #281 y #282 con una resolución controlada de importación CSS en `FarmMapTimeline.tsx`. No modifica APIs, permisos, SQL, S3, científicos ni producción.

**Importante:** esta rama es una vista previa **compilable** y un contrato de recorrido por pruebas de código. No es todavía una URL de pruebas navegable ni una prueba funcional de navegador con usuario y datos reales. Solo una UAT de navegador puede validar capturas y usabilidad real.

## Flujo que debe funcionar para un productor autenticado

1. Entrar a `/portal`; el catálogo READ consulta `/api/v1/dbi/portal/accounts` por los permisos de su cuenta. Buscar finca/lote, comprobar resultados y ausencia de contactos ajenos.
2. Abrir un lote mediante `mapLink(tenant, farm, plot)`. La URL incluye organización/finca/lote específicos y `tenant` codificado; el router de lotes tiene protección de autenticación.
3. Confirmar breadcrumb «Mis fincas» → visor, vuelo exacto cuando se haya elegido uno, fecha y mensaje explícito si la fecha corresponde a varias Campaign.
4. Navegar el mapa y su cronología. La cartografía RGB/GIS se muestra sólo cuando el servidor la autoriza; no asumir que la disponibilidad implica descarga, visualización ni aprobación científica.
5. Abrir la guía de fuentes del mapa: RGB, GIS y seis índices como **estadísticas, no mapas temáticos**. Desde la guía acceder a la pestaña MULTI.
6. Consultar los seis índices de la extracción autorizada seleccionada: mediana, P10–P90, píxeles válidos, descripciones sin diagnóstico ni tratamientos.
7. En el teléfono, deslizar las fichas MULTI, elegir «Ver todos», regresar a «Vista compacta» y comprobar foco y lecturas completas.

## Dos referencias visuales de la conversación: interpretación vinculante

- **Imagen de escritorio:** guía de identidad visual (verde petróleo, acentos cobre, disposición clara, fotografía/mapa prioritario, tarjetas legibles). La simulación **combina catálogo y mapa en una sola pantalla**, pero la app usa **rutas separadas** `/portal` y `/.../mapa`; no presentar la simulación como captura real.
- **Imagen móvil:** guía del orden de lectura (contexto de lote → levantamiento → mapa → historial → fuentes → índices). El carrusel móvil y botón «Ver todos» se implementaron en #284.
- Las fechas, nombres, hectáreas, fotos, límites de lote y todos los números multiespectrales de las imágenes **son ficticios con finalidad visual**; deben sustituirse por información real autorizada o por un estado de «sin datos».
- El soporte COPA_UP o ventana sustituta **no equivale a la superficie total del lote**. No convertir datos científicos de muestra a salud general, rendimiento, diagnóstico de Sigatoka o recomendación de tratamiento.
- La URL que aparece en la simulación es ilustrativa; no constata que exista un portal publicado en ese dominio.

## Criterios de salida y evidencia exigida

| Puerta | Criterio | Estado actual |
| --- | --- | --- |
| Integración del código | Una sola rama con UX Fases 1–5; sin alterar backends | Rama de preview, pendiente CI |
| Prueba de contrato | `dbiClientVisualLayout.test.mjs` valida portal → ruta mapa → Campaign → GIS → MULTI, más pruebas individuales | Pendiente CI sobre SHA final |
| Build | Node tests, lint y TypeScript/Vite pasan | Pendiente CI |
| Seguridad | Gitleaks/historial y revisión de dependencias resueltos sin desactivar reglas | Hallazgo histórico H14 pendiente |
| UAT visual escritorio | Capturas en 1280 y 1440 px frente a imagen de referencia | No realizada |
| UAT visual móvil | Capturas en 320, 375 y 390 px frente a imagen de referencia | No realizada |
| UAT funcional | Login real, búsqueda de finca, selección de lote, Campaign, capa y lectura MULTI, incluidos estados vacíos/errors | No realizada |
| Liberación | Revisión humana y autorización explícita previa a fusiones/despliegues | No autorizada |

## Restricciones técnicas

Los PRs #280–#284 y la rama Fase 6 **siguen independientes de `main`**; no hacer merges, migraciones ni Render automático. Ninguna subida TIFF, concesión multipart S3, `abort`/cleanup ni publicación científica. No se simula que las pruebas Node de cadenas de texto sean pruebas E2E reales; son contratos preventivos complementarios.

## Próximo paso en entorno controlado, bajo autorización

Resolver la incidencia histórica de seguridad, revisar el paquete combinado de cambios, habilitar una URL de **staging** con datos de prueba explícitos y permisos acotados, ejecutar un navegador (desktop y mobile), capturar pantallas reales y documentar discrepancias respecto a las dos imágenes. Eliminar cualquier credencial/dato sensible de capturas antes de compartirlas.
