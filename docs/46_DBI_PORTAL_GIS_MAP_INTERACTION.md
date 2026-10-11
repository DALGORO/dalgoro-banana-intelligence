# DBI-PORTAL-UX-002 — Consultar resultados sobre el mapa

Esta mejora facilita la lectura de capas de datos agrícolas existentes y previamente autorizadas:

- Desde «Mis fincas», abrir finca → lote → fecha.
- El panel «Resultados GIS del levantamiento» muestra capas con un punto de color, categoría agrícola y conteo de elementos. Las casillas permiten activar y desactivar cada capa.
- Al pulsar en cualquier elemento visible de una capa publicada, Google Maps o MapLibre muestra un cuadro con el nombre de la capa y los atributos del elemento.
- Los cuadros se construyen exclusivamente mediante `createElement` y `textContent`, nunca `innerHTML`. Campos técnicos internos, objetos y atributos excesivos no se muestran.
- Las capas siguen procediendo del endpoint DBI protegido por sesión, tenant y lote; la mejora no concede permisos nuevos ni exporta datos originales.
- Cuando no existe `VITE_GOOGLE_MAPS_API_KEY`, se utiliza MapLibre sin requerir Google. El visor no simula valores de densidad, salud o producción.

**No sustituye el UAT #155** con ortofotos reales ni incorpora aún carga binaria directa de SHP/GeoPackage. Ésta se realizará con un adaptador GDAL/OGR aislado de FastAPI, manteniendo la conservación de archivos originales.
