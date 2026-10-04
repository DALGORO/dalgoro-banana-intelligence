# 43 — Estado READY para primera prueba RGB real

## Estado que representa este documento

Este hito no declara producción cloud. Declara que el repositorio contiene y
prueba conjuntamente las piezas necesarias para ejecutar una **prueba local
controlada con una ortofoto real**.

Cadena objetivo:

```text
GeoTIFF real verificado
        ↓
COG RGB privado validado
        ↓
DBIRasterProduct ready
        ↓
Campaign Density real + orthophoto_source
        ↓
timeline MAP
        ↓
endpoint XYZ autorizado
        ↓
MapLibre
```

## Antes de usar una ortofoto real

1. Actualizar el checkout local al `main` aprobado.
2. Abrir **DALGORO DBI Control Center**.
3. Ejecutar **Reiniciar sistema**.
4. Entrar a **Densidad de siembra**.
5. Confirmar:
   - Motor de densidad: listo.
   - Raster / COG: listo.

Si Raster / COG no está listo, detener la prueba. El Control Center debe haber
detectado un Python Density capaz de ejecutar `import rasterio`.

## Flujo de una sola pantalla

En Densidad:

1. Crear o seleccionar finca.
2. Crear o seleccionar lote.
3. Seleccionar o cargar una ortofoto GeoTIFF real.
4. Esperar estado `verified`. Si la UI usa `AUTO_FROM_GEOTIFF`, el activo
   conserva CRS sin resolver hasta que el COG validado lea el CRS real; el
   sentinel nunca se trata como CRS científico.
5. Pulsar **Preparar mapa RGB**. El CRS real del manifest COG se reconcilia con
   el activo fuente; un CRS explícito divergente falla cerrado.
6. Confirmar que el COG queda listo.
7. Cargar el Excel real del límite de análisis y los demás parámetros de Density.
8. Pulsar **Ejecutar análisis completo**.
9. La creación del job registra inmediatamente una Campaign real y su
   `orthophoto_source`; no es necesario esperar las 17 etapas para visualizar
   la evidencia RGB observada.
10. Pulsar **Preparar / verificar mapa RGB**.
11. Pulsar **Abrir mapa RGB**.

## Resultado esperado

- La ortofoto aparece en MapLibre.
- Si el lote tiene `Plot.boundary`, ese límite controla el viewport.
- Si el lote se creó sin GeoJSON, el visor usa únicamente como fallback de
  visualización los bounds georreferenciados del Raster y los transforma a
  WGS84 mediante PostGIS.
- El navegador solicita tiles PNG, no el GeoTIFF completo.
- Cada tile vuelve a pasar autorización tenant/finca/lote.
- La ruta física, object key, bucket y credenciales nunca se publican.
- El primer pedido de un tile puede registrar MISS y su replay HIT.
- Repetir **Preparar mapa RGB** devuelve la misma identidad Raster y no crea un
  segundo producto para la misma fuente/perfil.

## Gate técnico del repositorio

`.github/scripts/ci_dbi_real_flight_readiness.py` valida que existan
simultáneamente:

- builder COG aislado;
- producto Raster privado;
- Campaign Density con `orthophoto_source`;
- join Campaign → Artifact → Raster;
- fallback de viewport;
- endpoint XYZ autorizado;
- contrato RGB uint8;
- MapLibre con headers DBI;
- Control Center con Python Rasterio explícito;
- ausencia de Rasterio/GDAL dentro del proceso FastAPI.

Los workflows dinámicos especializados continúan validando PostGIS, Raster,
Campaign, Sampling, Inspection, Multispectral, PWA, frontend y backend.

## Criterio de aceptación de la prueba real

El repositorio puede declararse **READY_FOR_REAL_RGB_FLIGHT_TEST** cuando el PR
de este gate está completamente verde y fusionado.

La prueba con datos reales se considera aprobada sólo después de comprobar en la
estación Windows:

- COG `ready`;
- product ID estable en replay;
- Campaign visible en timeline;
- ortofoto visible en MapLibre;
- scope no autorizado rechazado;
- sin exposición de dirección privada;
- GeoTIFF maestro intacto.

Hasta completar esa ejecución local no debe afirmarse que una ortofoto real ya
fue probada de extremo a extremo.

## Fuera de alcance

Este estado no declara:

- despliegue cloud productivo;
- CDN;
- dashboard comercial final;
- Sigatoka validada;
- NDVI/NDRE sin evidencia real;
- modelo COPA_UP final;
- producción agrícola completa.
