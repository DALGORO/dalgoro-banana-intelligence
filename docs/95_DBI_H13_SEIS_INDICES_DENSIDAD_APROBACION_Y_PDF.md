# H13 · Seis índices, capas de población, aprobación y PDF

## Auditoría de capacidad real (GitHub main @ 9a3661f)

### Los seis índices calculados y persistidos

`app/dbi/multispectral/contracts.py` define: `ndvi`, `ndre`, `gndvi`,
`evi2`, `ci_red_edge`, `ci_green`. Cada extracción conserva fórmulas,
versión, mediana, promedio, P10/P90, píxeles válidos y procedencia al ráster
científico + observación de campo. Son estadísticas **de una muestra**:
no identifican automáticamente un sector completo ni diagnostican sanidad.

### Lo que puede activarse geográficamente hoy

El portal ya admite GeoJSON de las siguientes clases GIS:
`plants` (puntos de plantas), `density_hexagons` (zonas de densidad),
`planting_candidates` (candidatos), `boundaries` (límites),
`observations` (observaciones) y `other`. La interfaz ofrece switches
independientes por capa y muestra la leyenda de capas reales visibles.
El servicio limita la cantidad/tamaño de geometrías; los registros geográficos
no deben contarse automáticamente como plantas vivas o hectáreas.

**No existen aún seis productos ráster temáticos validados/publicados como
capas NDVI, NDRE, GNDVI, EVI2, CI Red Edge y CI Green.** El motor privado
sirve `rgb_visual` natural y `scientific` en bandas individuales grises,
que no equivalen a mapas de cada índice. Queda **prohibido** calcular falsos
mapas combinando PNG de bandas ya normalizadas; perderían reflectancia,
calibración y manejo correcto de NoData.

En esta entrega: la pestaña MULTI muestra los seis índices por nombre
y permite ocultar/mostrar independientemente sus **fichas estadísticas**.
La sección de capas cartográficas enumera los seis mapas como **no disponibles**
hasta que exista un ráster real, validado, enlazado a Campaign y publicado.
Los switches cartográficos pendientes quedan inactivos.

### Gate de publicación

1. Trabajo/archivo cargado, validación de fuente y calidad técnica.
2. Gestión previa, revisión de GeoJSON/GPKG o de producto de vuelo en servidor.
3. Campaign avanza secuencialmente hasta `APPROVED`.
4. **PUBLISHED exige** permisos MANAGE del scope, DBI principal/membresía
   vigentes, acreditación institucional DALGORO como administrador y guard
   transaccional de revocación de cargos vigente (migración 29).
5. Cronología RGB, lectura GIS, estadísticas MULTI y reporte PDF del productor
   consultan **solo** Campaign en `PUBLISHED` con `approved_at` y
   `published_at` registrados. Ninguna fecha infiere publicación.
6. Datos aún no publicados permanecen fuera de esas rutas del cliente.
   Las vistas administrativas de revisión y staging requieren MANAGE y
   no constituyen publicación final al productor.

No se ha dado de alta a ninguna persona como personal institucional,
ni se ha activado el flag de endpoints privados de INSPECT.

### Informe PDF consultable

`GET /api/v1/dbi/organizations/{org}/farms/{farm}/plots/{plot}/campaigns/{campaign}/published-evidence.pdf`

La respuesta PDF está autorizada en servidor para lote exacto, requiere
Campaign `PUBLISHED`, `approved_at` y `published_at`, y emite
`Cache-Control: private, no-store`. La pantalla del cliente abre la ficha
con token HTTP legítimo como Blob y permite verla o descargarla. Contenido:

- identidad interna de Campaign, fecha de vuelo, fecha de aprobación y publicación;
- los seis índices: valor de mediana + conteo de píxeles válidos de **la última
  extracción verificable del mismo Campaign dentro de las últimas 20 del lote**,
  o «No disponible»;
- capas GIS existentes de la misma Campaign: cantidad de capas y elementos;
- advertencias de comparabilidad, límites de muestras y ausencia de diagnóstico.

**No es el informe técnico íntegro del módulo legacy Density**, que está
en `dbi_density_local.py` y usa rutas/archivos locales por ejecución.
Para publicar ese documento exacto a un cliente deberá implementarse
una entrega de artefactos PDF verificada en almacenamiento privado DBI,
asociada a Campaign y aprobación de administración. No se comparten
rutas locales ni archivos sin un nuevo contrato de publicación.

### Pendientes prioritarios para completar la petición

- Pipeline validado para **seis rásteres georreferenciados**, cada uno con
  fórmula, escalas, calibración, soporte espacial, NoData, checksum, hash
  de origen y estilo/leyenda. Persistencia y enlace exacto Campaign/artefacto.
- Publicación explícita de cada producto con revisión institucional, y endpoints
  de lectura/scoped tiles que apliquen el mismo gate; solo entonces habilitar
  los seis toggles sobre el mapa.
- Entrega protegida del **PDF técnico completo de población** generado
  por el motor Density (no solo la ficha resumida disponible aquí).
- Paginación histórica por Campaign; UAT con productor y comprobación del
  despliegue Render. La UI y CI local no prueban el estado de producción.

No realizar despliegue, migración, acreditación de personal ni cambios en
YOLO, Sigatoka, COPA_UP, modelos, fórmulas o cálculo de densidad.
