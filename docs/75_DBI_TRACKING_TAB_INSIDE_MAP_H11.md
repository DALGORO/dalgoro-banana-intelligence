# DBI-CLIENT-VIEW-007 · Ficha de seguimiento como pestaña dentro del visor (Hito 11)

## Decisión del cliente
El cliente eligió explícitamente **la segunda opción**: la ficha de seguimiento
agrícola será una **pestaña interna del visor cartográfico existente**,
no una página de inicio independiente. El mapa permanece como área principal
siempre montada y la selección de finca, lote, fecha, capas y Campaign se conserva
al alternar entre `Evidencia MULTI` y `Seguimiento del lote`.

## Integración mínima
- `FarmMapTimeline.tsx`: pestañas a la derecha del mapa en escritorio ancho
  y debajo del mapa en resoluciones intermedias/móvil. Primera vista:
  `Evidencia MULTI`; segunda: `Seguimiento del lote`.
  Los dos paneles permanecen en DOM con atributo `hidden` para evitar que
  alternar pestañas descarte el estado de extracción seleccionada. El mapa
  está **fuera de ambos paneles**: nunca se desmonta por cambiar de pestaña.
- ARIA `tablist`, `tab`, `tabpanel`, selección, foco y flechas
  izquierda/derecha para teclado; acceso móvil `Ficha del lote`.
- `FarmTrackingPanel.tsx` presenta solamente información ya disponible
  y autorizada de la cronología activa (finca, lote, fecha, Campaign exacta
  cuando existe, registros visibles, GIS asociada al filtro y referencias
  de inspecciones cartográficas disponibles). El botón «Consultar evidencia
  multiespectral» regresa a la pestaña de extracción, sin llamadas nuevas.
- La ficha **no** consulta un endpoint nuevo de INSPECT: los contadores de
  inspecciones cartográficas y capas GIS representan **registros/capas**
  del visor, no visitas de campo ni observaciones individuales validadas.
- Un cero es ausencia **en la selección y filtros actuales**, nunca ausencia
  en la finca completa, y errores de consulta se muestran sin inventar datos.
- Mantiene la lógica scoped de `MultispectralEvidencePanel`, la
  asociación exacta Campaign, roles READ/MANAGE y la trazabilidad de
  `docs/69` a `docs/74`.

## Exclusiones
Sin mutaciones de datos, nuevas llamadas API, escritura en base de datos,
despliegues, migraciones, contratos backend, productos NDVI de mapa, umbrales
agronómicos, algoritmos GOLD/YOLO/COPA_UP/Density ni recomendaciones
automáticas de tratamiento.

## Pruebas automáticas y visuales
El contrato de Node24 `dbiClientVisualLayout.test.mjs` exige que
las pestañas existan con semántica accesible, que mapa y MULTI sigan
montados y que la ficha no haga nuevas consultas ni clasifique plantas.
Se mantienen lint, Vite/TypeScript, seguridad y CI especializado.

Queda pendiente UAT en navegador real con datos autorizados y roles READ/MANAGE:
375/390/430/768/1280/1600 px, navegación de teclado, fondo Google y MapLibre,
sin capas, múltiples Campaign de la misma fecha, fallos de carga, cambios
de lote/tenant, selector MULTI y accesos rápidos móviles.

Las pruebas CI exitosas **no sustituyen** la comprobación visual o agronómica.
