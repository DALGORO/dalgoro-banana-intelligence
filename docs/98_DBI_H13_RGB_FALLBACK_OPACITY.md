# H13 — Transparencia RGB y carga móvil coherentes sin Google Satélite

## Auditoría puntual sobre main@1eb7b49

El visor usa el SDK oficial de Google Maps en modo `satellite` cuando está
disponible. Cuando no lo está, MapLibre muestra exclusivamente una base neutra
y los productos de DALGORO autorizados. En la rama base, la vista alternativa
recreaba fuentes RGB con opacidad 1 independientemente del control del productor
y no exponía ese control fuera de Google.

## Corrección limitada al cliente

- El control RGB 0–100 % permanece accesible con Google o con fondo neutro.
- MapLibre no monta ni descarga fuentes RGB cuando la opacidad es 0 %.
- Con RGB visible, el desplazamiento del control únicamente cambia
  `raster-opacity`: no desmonta ni vuelve a crear fuentes ni solicita de nuevo
  tiles privados por cada movimiento.
- El rótulo informa qué fondo se está mostrando. Ningún dato o imagen base
  simulado se usa como sustituto de Google.
- Las fuentes en MapLibre siguen derivándose de los productos autorizados
  por lote/campaña. Este PR no cambia permisos, endpoint ni publicación.

## Límites científicos, legales y de rendimiento

El GeoTIFF científico y sus CRS, valores, nodata, checksum y cadena de custodia
quedan intactos. El renderer de productos propios transforma `EPSG:32717`
(u otro CRS original real) a `EPSG:3857` para los tiles XYZ. No se afirma
alineación métrica certificada: faltan ortofotos/GCP/RTK de control y una prueba
real en navegador/celular bajo conexiones representativas.

La documentación previa recupera referencias históricas a estilos QGIS
`RGB_2_98.qml`, `NDVI_DIAGNOSTICO_2_98.qml` y
`NDRE_DIAGNOSTICO_2_98.qml`, pero no sus QML originales versionados.
Los seis índices se consultan hoy como evidencia estadística; **no** se
habilitan seis mapas ráster por inferencia visual. Para activar esas capas
faltan rásteres georreferenciados reales, estilos originales verificables,
QA y aprobación `PUBLISHED` de cada Campaign.

Google Maps únicamente se carga mediante Maps JavaScript API, con
atribución oficial. No se descarga, cachea, digitaliza ni redistribuye
imaginería de Google fuera de su servicio.

## Verificaciones

- Prueba de regresión estática del control en ambos fondos, del montaje
  condicionado y de la separación entre actualización de opacidad y fuentes.
- El gate final exige todos los checks CI aplicables en el SHA final y comprobar `main`
  posterior al merge.
- Sin Render, sin migraciones productivas, sin cambio de API, perfiles COG,
  seguridad, cálculo de índices o fuente científica.
