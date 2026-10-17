# H13 — Gate geoespacial UTM 17S → XYZ para el visor DBI

**Base:** `main@2f9a67b`. PR exclusivo de pruebas y documentación; no modifica producción.

## Brecha detectada

El CI ya crea COG sintéticos con `EPSG:32717` y prueba tiles
con `EPSG:4326`, pero no comprobaba de extremo a extremo la **posición
de píxeles** de una ortofoto UTM 17S al superponerla en la cuadrícula XYZ.

## Prueba nueva: `ci_dbi_raster_utm17s_xyz.py`

1. Fabrica **dos fuentes sintéticas temporales**, inequívocamente etiquetadas
   como prueba; no representan finca, vuelo ni observación científica.
2. RGB: cuatro cuadrantes de color conocido bajo affine métrico, CRS
   `EPSG:32717`. Genera un COG `DEFLATE` sin pérdida, reproyecta a XYZ
   `EPSG:3857` y verifica la ubicación y color del centro de cada cuadrante
   según su proyección geográfica. Comprueba rechazo de tile fuera de huella.
3. Científico: Float32 con `NoData=-9999`, renderizado monocromático
   **solo como prueba técnica**, confirma alpha=0 en la zona sin datos,
   alpha=255 y gris correspondiente a 0.5 en zona válida.
4. Comprueba SHA-256 sin cambios de los dos archivos maestros y sus COG,
   y que CRS/NoData de la fuente se mantuvieron. Todo vive en un directorio
   efímero de GitHub Actions.

La prueba se integra a `DBI · COG sintético RGB y científico`, por lo
que una regresión de georreferenciación o máscara bloquea el PR.

## Límites

- **No demuestra coincidencia con Google Satélite ni precisión centimétrica.**
  La comprobación es sintética e interna, no valida puntos RTK/GCP, datum local,
  aerotriangulación, residual RMS o fecha/resolución de imagen Google.
- Los QML históricos NDVI/NDRE/GNDVI/EVI2/CI Red Edge/CI Green aún no están
  verificados como archivos originales. No hay creación, activación o
  publicación ficticia de mapas espectrales.
- No modifica cálculo de índices, rutas API, perfiles COG, seguridad,
  autorización `PUBLISHED`, almacenamiento, migraciones ni Render.

**Siguiente gate para cartografía real:** verificar ortofoto RGB y al menos
tres puntos independientes bien distribuidos por lote, error planimétrico y
residuos reportados, y comprobar en navegador móvil con clave Google válida.
Conservar resultados por Campaign y no afirmar una tolerancia que no esté
definida por protocolo e instrumentación.
