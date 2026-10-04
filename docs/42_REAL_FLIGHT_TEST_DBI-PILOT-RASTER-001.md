# 42 — Primera prueba real RGB DBI-PILOT-RASTER-001

## Objetivo

Validar en una estación Windows real el flujo completo:

    GeoTIFF real verificado
            ↓
    COG RGB validado
            ↓
    Storage privado DBI
            ↓
    DBIRasterProduct ready
            ↓
    Campaign técnica real
            ↓
    MAP-002
            ↓
    tiles XYZ privados
            ↓
    MapLibre

La prueba no declara el sistema listo para producción cloud. Demuestra que una ortofoto real atraviesa las fronteras DBI sin rutas simuladas, sin acceso público al COG y sin cargar Rasterio/GDAL dentro de FastAPI.

## Dependencias integradas

- DBI-RASTER-001: COG/BigTIFF, metadata, Storage privado y HTTP Range.
- DBI-RASTER-TILE-001: renderer aislado, caché privada y endpoint XYZ autorizado.
- DBI-MAP-002: timeline Campaign → Raster y visor MapLibre real.
- DBI-PILOT: empresa, finca, lote, GeoJSON, ortofoto privada y Campaign Density.

## Preparación Windows

Después de actualizar el repositorio:

1. Abrir DALGORO DBI Control Center.
2. Pulsar Reiniciar sistema.
3. El Control Center compara la revisión Git registrada con el checkout actual; si cambió, no reutiliza el stack viejo.
4. El runtime busca un Python Density que pueda ejecutar import rasterio.
5. Ese intérprete se propaga como DBI_DENSITY_PYTHON y DBI_RASTER_RENDERER_PYTHON.
6. En Agricultura DBI, la tarjeta Raster / COG debe indicar Listo.

Si Raster / COG indica No disponible, no continuar con la generación del COG. Primero debe existir un venv del motor Density con Rasterio.

## Prueba operativa

### 1. Preparar autoridad y territorio

En una empresa real del piloto local:

- reconciliar DBI;
- crear o seleccionar finca;
- crear o seleccionar lote;
- usar el límite GeoJSON EPSG:4326 real.

### 2. Cargar ortofoto maestra

Desde la laptop seleccionar finca, lote, CRS real y cargar el GeoTIFF. La carga debe terminar como verified. DBI conserva SHA-256, tamaño, scope, CRS y objeto privado.

### 3. Preparar mapa RGB

Sobre la última ortofoto verificada, pulsar Preparar mapa RGB.

El backend vuelve a verificar tenant/finca/lote/asset, resuelve la ruta física sólo server-side, ejecuta flight_test_cog.py mediante subprocess con el Python Raster, valida el manifiesto, comprueba source SHA e identidad determinista, publica el COG en RASTER_PRODUCT, registra el producto ready y elimina el staging temporal.

Un replay exacto debe devolver el mismo product_id y no volver a generar el COG.

### 4. Vincular una Campaign real

El mapa no crea Campaigns artificiales. Si la ortofoto todavía no está vinculada a una Campaign técnica, usar Densidad de siembra con esa misma ortofoto. La creación del job Density registra la Campaign y el artefacto orthophoto_source.

La capa RGB es evidencia observada; MAP-002 puede mostrarla durante DRAFT o PROCESSING y no necesita esperar a que terminen las inferencias de densidad.

### 5. Abrir mapa

Volver a Agricultura DBI y pulsar Abrir mapa.

Resultado esperado:

- MapLibre se ajusta al boundary real del lote;
- aparece la ortofoto RGB;
- el navegador solicita tiles z/x/y PNG;
- cada tile vuelve a pasar autorización DBI;
- el COG completo nunca se entrega al navegador;
- el primer tile puede producir cache MISS y una repetición exacta HIT.

## Gate de aceptación

La prueba real se considera aprobada únicamente si el COG termina ready, el product ID es estable en replay, la Campaign real aparece en el timeline, MapLibre muestra tiles válidos, un scope no autorizado no obtiene el producto, no aparece object_key/bucket/ruta local/credencial en respuestas web y el GeoTIFF maestro no es reemplazado por el COG.

## Diagnóstico local

Logs del Control Center:

    %LOCALAPPDATA%\DALGORO\DBI\logs\backend.out.log
    %LOCALAPPDATA%\DALGORO\DBI\logs\backend.err.log
    %LOCALAPPDATA%\DALGORO\DBI\logs\frontend.out.log
    %LOCALAPPDATA%\DALGORO\DBI\logs\frontend.err.log

Estado:

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\infra\windows-local\DBI-ControlCenter.ps1 -Action Status

## Exclusiones

Esta prueba no habilita CDN pública, Storage cloud definitivo, diagnóstico de Sigatoka, NDVI/NDRE sin producto real, dashboard comercial completo, modelos COPA_UP todavía en desarrollo ni entrenamiento/modificación de GOLD.
