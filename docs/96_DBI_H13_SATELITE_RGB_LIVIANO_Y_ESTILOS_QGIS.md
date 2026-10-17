# DBI H13 — Google Satélite, visualización ligera y recuperación de estilos

**Fuente inspeccionada:** código `main@76c235f2d9897f8a732232b85b7bbee3a8e806e8`; historial de trabajo QGIS proporcionado previamente. Esta nota no prueba conexión a una cuenta Google, cobertura real ni precisión posicional sin datos de campo.

## Fondo y sistema de referencia

- La vista de productor usa el mapa base **Google Maps JavaScript API** con `mapTypeId: "satellite"`, no una descarga de Google Earth. Necesita clave válida, servicio disponible y condiciones comerciales vigentes. No existe derecho a almacenar libremente las imágenes de Google ni a servirlas desde nuestro servidor. Se mantienen logos/atribuciones del SDK.
- La cartografía de vuelos en WGS 84 / **UTM zona 17 sur EPSG:32717** no se etiquetará como si estuviera en WGS84 latitud/longitud `EPSG:4326`. Para la superposición, `raster_tile_renderer.py` genera los mosaicos XYZ en **EPSG:3857** mediante `WarpedVRT` de Rasterio. Google trabaja con WGS84 geográfico para ubicaciones y Mercator para sus mosaicos. GeoJSON se entrega en latitud/longitud.
- Revisar datum, transformaciones, CRS, tamaño de píxel, límites, puntos de control y error de registro al comparar fuentes. Tener un EPSG correcto **no garantiza** coincidencia submétrica entre vuelo y Google, cuya fecha y ortorrectificación pueden diferir.

## Ráster ligero ya existente

1. Maestro GeoTIFF privado **intacto**, sin cambiar reflectancia/valores científicos.
2. COG RGB original `cog_v1`: compresión **DEFLATE** sin pérdida; bloques 512 y overviews. El pipeline principal sigue utilizando este perfil por defecto.
3. COG de **presentación opcional** `cog_rgb_preview_jpeg_v1`: compresión **JPEG calidad 80** y YCbCr, limitado a fuentes con tres bandas `uint8` sin nodata; conserva geometría/CRS. La herramienta `flight_test_cog.py` ya acepta esta versión, pero **todavía no es el perfil activo por defecto** en `DBIPilotRasterBuilder`. No usarlo en índices ni como evidencia científica.
4. El navegador solicita mosaicos **PNG de 256 × 256** autorizados y cacheados privadamente, no el GeoTIFF completo. El piloto ya conserva integridad, SHA-256, perfiles separados y trazabilidad.
5. Este PR evita solicitudes de mosaicos RGB ocultos: **opacidad = 0** desmonta y cancela superposiciones privadas, dejando Google Satélite y el GIS visibles. En opacidad positiva los mismos mosaicos se reutilizan al mover el control, cambiando solo CSS. Al reactivar desde 0 se solicitan los tiles necesarios.

**Importante:** JPEG en el COG puede reducir almacenamiento y acceso a disco, pero la respuesta pública del tile continúa siendo PNG; no se ha demostrado una reducción exacta de bytes de red sin pruebas reales. No cambiar los formatos de transporte ni calidad por supuestos sin benchmark.

## Estilos QGIS anteriores recuperables

El repositorio contiene **QML para densidad y población** en `services/banana-density/resources/qgis/styles/`, pero **no contiene QML de los seis índices ni del RGB**. La búsqueda del árbol completo no encontró archivos `NDVI*.qml`, `NDRE*.qml`, `GNDVI*.qml`, `EVI2*.qml` ni de clorofila. No debe inventarse una paleta propia atribuyéndola a DALGORO.

| Capa | Estilo recuperado | Fuente / estado |
|---|---|---|
| NDRE diagnóstico | QGIS pseudocolor de banda única; **corte visual acumulativo 2–98 %**, **7 clases**, rampa **RdYlGn (rojo para valores menores, amarillo intermedio, verde para mayores)**; rango visual **0.0281963–0.4056004** | Datos *específicos del vuelo/lote previo* recordados del trabajo QGIS de septiembre; **no** son umbrales agronómicos universales y no figuran en archivo QML versionado |
| NDVI | Índice científico calculado; archivo QML/escala cromática específica no localizado | **Pendiente de recuperar el QML o parámetros originales** |
| GNDVI | Índice científico calculado; QML/escala no localizado | Pendiente |
| EVI2 | Índice científico calculado; QML/escala no localizado | Pendiente |
| CI Red Edge | Índice científico calculado; QML/escala no localizado | Pendiente |
| CI Green | Índice científico calculado; QML/escala no localizado | Pendiente |
| RGB | **Color natural**, canales visuales RGB. No hay comprobación de un estilo de corrección radiométrica/percentil visual propio del vuelo en QML | El portal emplea `rgb-natural-v1` con bandas 1–3 sin stretch científico |

**Propuesta para índices raster livianos, aún no implementada:** guardar derivados científicos Float32 georreferenciados, con `nodata` y fuente/calibración intactos; producir mosaicos solo de presentación usando estilos QGIS **confirmados**, su leyenda y rango por vuelo, en tiles independientes bajo la misma aprobación institucional `PUBLISHED`. Las comparaciones interfecha exigen comparabilidad científica comprobada.

## Límites de esta mejora

No se modifica `raster_cog.py`, no se genera otro COG ni se cambia el perfil activo de pilot, los seis índices, la física de las bandas, los límites geoespaciales o el gate institucional de publicación. No se activan cuentas Google ni se despliega a producción. El paso siguiente para activar `cog_rgb_preview_jpeg_v1` es implementar selección segura de producto visual con el mismo control de aprobación del vuelo y verificar en un dataset real tamaño, latencia y alineación.
