# UX Productor · Fase 2 — orientación del visor cartográfico

## Objetivo

Mejorar la legibilidad del mapa del lote y la selección de campañas sin modificar la cronología existente, su alcance privado o los requisitos de publicación. Rama independiente de la fase UX #280, sobre `main`.

## Alcance

- `FarmMapTimeline.tsx`: navegación contextual «Mis fincas / Mapa del lote» solo si el mapa tiene localizador exacto.
- Tarjeta de lectura del **levantamiento seleccionado**, alimentada exclusivamente por `selectedVisit` (identidad exacta Campaign+fecha a través de `selectedMapCampaignId`). No mostrar un vuelo arbitrario si la fecha es ambigua.
- Accesos anclados «Ver mapa» y «Cambiar vuelo» reutilizando las regiones existentes.
- Indicador visible «Seleccionado» únicamente en el botón del levantamiento activo; se conserva `aria-pressed` y `chooseMapVisit`.
- Hoja visual aislada `farm-map-ux.css`, tamaños táctiles >=44px, foco de teclado, modo oscuro y diseño móvil; no modifica la CSS compartida con el PR #280.
- Regresión dentro de `dbiClientVisualLayout.test.mjs`, ejecutado por el job de frontend existente.

## Barreras preservadas

La UI no afirma que existan mapas multiespectrales temáticos pendientes, no introduce indicadores agronómicos ni fusiona distintas Campaign de la misma fecha. No cambia `getPlotMapTimeline`, solicitudes HTTP, fechas/capa GIS, permisos MANAGE/READ, S3, SQL, carga de TIFF, grants, publicación ni Render.

## Criterios

1. Sin Campaign exacta activa, la tarjeta invita a elegir y no identifica un vuelo falso.
2. Con Campaign exacta, solo se muestran nombre, fecha y disponibilidad de cartografía asociada a esa misma Campaign.
3. Navegación teclado y móvil clara; mapas mantienen prioridad visual existente. Inspección visual real y UAT requieren revisión manual.
4. Pasan TypeScript/Vite, lint base y pruebas del layout DBI. Gitleaks analiza historial completo y puede señalar commits exploratorios H14 no pertenecientes a este PR: investigar el hallazgo sin desactivar el escáner.
5. PR en borrador: ninguna fusión, migración o despliegue sin aprobación.

## Separación

La revisión de H14 permanece congelada en #279, con #271 alternativo a #270 y el SHA actualizado de seguridad #269 pendiente de CI propia. Este incremento visual no desbloquea recepción científica operativa.
