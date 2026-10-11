# DBI-PORTAL-GIS-001 — Primer corte de carga GIS GeoJSON

## Flujo implementado
1. El usuario inicia sesión en `/portal` y entra a una finca/lote con acceso DBI.
2. El visor carga la Campaign RGB real por fecha. Un usuario con permiso DBI **manage** sobre el lote encuentra «Añadir resultado cartográfico». Un usuario con permiso **read** sólo consulta capas publicadas.
3. El administrador elige una fecha ya presente en el timeline RGB, tipo de información y archivo `.geojson` WGS84 RFC 7946 hasta 2 MiB. El backend valida entidades, coordenadas WGS84, geometría, tamaño y atributos.
4. Tras publicación en PostgreSQL DBI, el visor lista la nueva capa para cualquier usuario **read** autorizado por el mismo tenant/finca/lote. Los puntos, líneas y polígonos se dibujan sobre la ortofoto y el mapa satelital.
5. Cada carga se ancla a una **Campaign técnica real** del tenant/lote, registra SHA-256 del archivo de origen y almacena una representación normalizada para visualización; no modifica la fuente científica ni recalcula Density.

## Datos admitidos inicialmente
GeoJSON `FeatureCollection` WGS84, geometrías Point/MultiPoint, LineString/MultiLineString, Polygon/MultiPolygon, 1 a 2500 entidades y máximo 50.000 vértices. Atributos visibles escalares (texto corto/número/bool) con campos sensibles excluidos. El archivo de fuente original debe conservarse fuera de la capa derivada, para reprocesamiento trazable.

**No subir** directamente SHP/GeoPackage a este endpoint. Primero habrá que validar y convertirlos en un worker GDAL/OGR independiente, con fuente privada e índice/paginación para capas extensas; issue #160 continúa activo.

## Migración y pruebas
- Alembic DBI añade `dbi_portal_vector_layers`, separado del esquema legacy.
- No se ejecuta ninguna migración online desde GitHub/CI. Aplicar solamente mediante el flujo controlado DBI de administración, **después de revisar la migración y respaldar la base**.
- CI offline comprueba validación GeoJSON, denegación a rol lector y lote ajeno; no sustituye E2E real de una finca.
- Upload y GET siempre llevan token autenticado + `X-DBI-Tenant`, revalidado por el backend. UI no expone rutas privadas de archivos.

## Límites de este corte
La opción de carga aparece únicamente si el timeline RGB del lote ya contiene una Campaign técnica para la fecha seleccionada. La importación de resultados históricos cuyos Campaign/ortofoto aún no están adoptados es trabajo pendiente. No hay aún vector tiles, comparación geométrica ni procesamiento masivo. El diseño continúa siendo un primer incremento, no una promesa de soporte completo SHP/GPKG.
