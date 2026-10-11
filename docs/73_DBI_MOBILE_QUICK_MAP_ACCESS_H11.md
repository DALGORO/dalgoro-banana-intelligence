# DBI-CLIENT-VIEW-005 · Fecha y navegación inmediata en móvil (Hito 11)

## Decisión UX

La visual DALGORO aprobada se aplica progresivamente sin sustituir los datos.
Con la maqueta corporativa del PR #209, en un teléfono el panel de campañas/GIS
puede desplazar el mapa fuera de la primera pantalla. Este microhito ofrece
**fecha principal rápida** y dos enlaces reales de salto dentro del visor
(«Ir al mapa», «Ver evidencia MULTI») sin duplicar una fuente de datos.

La implementación usa las mismas `dates` originales, una función común
`selectPrimaryMapDate` en `FarmMapTimeline.tsx` y la selección actual
`selectedDate`. Una selección nueva elimina `specificMapCampaign` estricta,
igual que hacía el selector lateral. No infiere ni une campañas distintas de
igual fecha; seleccionar una Campaign exacta se sigue realizando desde el
historial MULTI verificado.

## Cambios y verificación

- La barra `dbi-mobile-toolbar` solo se muestra a 767 px o menos.
  A 768 px o más permanece oculta por `display: none`, sin control duplicado
  visible o tabulable.
- El selector queda deshabilitado si faltan fechas reales. Los enlaces HTML
  solo navegan a IDs existentes en el documento; el enlace MULTI se ofrece
  exclusivamente cuando existe `realLocator`.
- Las fechas no se almacenan en otro caché ni dependen de dispositivos,
  geolocalización o estado local. Se mantienen fechas completas del backend
  (instantes con zona horaria), no fechas demostrativas.
- Los enlaces, el selector y su foco de teclado conservan tamaño táctil
  y contraste con la marca DALGORO.
- `dbiClientVisualLayout.test.mjs`, que ya forma parte de CI Node 24,
  incorpora contratos de ambos selectores y destinos de navegación.
- En móvil, sin modificar el DOM o la jerarquía de permisos, los controles
  completos permanecen accesibles para configuración GIS. No se esconde
  ninguna función crítica detrás de pantallas ficticias.

## Exclusiones y pruebas visuales pendientes

No se cambian roles READ/MANAGE, endpoints, fuente científica, migraciones,
productos RGB, interpretaciones NDVI/NDRE, comparación temporal ni producción.

CI valida invariantes estáticas, lint y build. **No acredita** capturas de
pantallas reales o una prueba táctil en Safari/Chrome. En la revisión visual
pendiente se requieren 375/390/430 px y modo paisaje: foco, paneles sin
desbordamiento, selección de fechas con vuelos coincidentes, navegación al
mapa y MULTI, estados vacíos y autorización.
