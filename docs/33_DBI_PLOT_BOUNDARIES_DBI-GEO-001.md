# DBI-GEO-001 — Geometrías operativas y esquema espacial

## Estado

Implementación espacial preparada y sometida a una primera CI completa. No se ejecutaron migraciones online, no se abrió ninguna conexión remota y no se modificó la base heredada. La auditoría posterior a CI #264 detectó y corrigió una incompatibilidad entre la ubicación predeterminada de PostGIS y el `search_path` de los roles DBI; la corrección requiere una nueva CI completa antes del cierre.

## Decisión espacial canónica

| Decisión | Valor |
|---|---|
| Entidad espacial | `Plot` |
| Columna | `boundary` |
| Tipo persistido | `Geometry(MULTIPOLYGON, 4326)` |
| Nulabilidad inicial | Opcional |
| Intercambio HTTP | GeoJSON `MultiPolygon` 2D |
| Reparación automática | Prohibida |
| Complejidad máxima | 10.000 posiciones por geometría |
| Índice espacial | GiST explícito |
| Resultados espaciales | Máximo 20 lotes |

El lote es la unidad espacial operativa mínima ya usada por autorización, trabajos geoespaciales y activos DBI. `MultiPolygon` permite representar límites continuos o fragmentados sin cambiar el contrato cuando un lote contiene más de una parte.

## SRID y métricas

EPSG:4326 es el sistema canónico de persistencia e intercambio porque ofrece interoperabilidad directa con GeoJSON y clientes web. No se utiliza para calcular áreas, distancias o densidades métricas.

Cualquier cálculo métrico debe transformar deliberadamente la geometría a un CRS proyectado adecuado para la ubicación y registrar el CRS utilizado. `area_hectares` continúa siendo un dato funcional independiente; este incremento no lo recalcula ni intenta derivarlo automáticamente desde el límite.

## Validación de entrada

El contrato rechaza:

- objetos diferentes de GeoJSON `MultiPolygon`;
- campos desconocidos;
- coordenadas tridimensionales;
- geometrías vacías;
- polígonos sin anillos;
- anillos con menos de cuatro posiciones;
- anillos abiertos;
- coordenadas no finitas;
- longitudes fuera de `[-180, 180]`;
- latitudes fuera de `[-90, 90]`;
- geometrías topológicamente inválidas;
- geometrías con más de 10.000 posiciones.

No se usa `make_valid`, `buffer(0)` ni otra reparación implícita. El productor debe corregir y volver a presentar una geometría inválida.

## Persistencia defensiva

La revisión `dbi_0006_plot_boundaries`:

1. continúa exclusivamente desde `dbi_0005_identity_memberships`;
2. añade `boundary` como `MULTIPOLYGON` con SRID 4326;
3. impide geometrías vacías mediante `ST_IsEmpty`;
4. impide geometrías inválidas mediante `ST_IsValid`;
5. crea el índice `ix_dbi_plots_boundary_gist`;
6. no instala PostGIS ni ejecuta operaciones sobre tablas heredadas;
7. ofrece un downgrade limitado a índice, restricciones y columna espacial.

PostGIS debe estar aprovisionado previamente conforme a `DBI-INFRA-001`. La instalación predeterminada conserva sus tipos y funciones en `public`; por ello los roles DBI usan `search_path = dbi, public`, reciben solo `USAGE` sobre `public` y no reciben `CREATE` en ese esquema. `dbi` permanece primero para que Alembic cree allí los objetos no cualificados.

## Contratos HTTP

Los listados agrícolas normales conservan `PlotRead` sin geometría completa. `PlotRepository.list_by_farm` difiere la columna `boundary` para evitar transferir datos espaciales innecesarios.

Las operaciones de creación y actualización de lotes usan `PlotSpatialRead`, por lo que una escritura espacial devuelve GeoJSON y nunca WKB/EWKB.

La consulta operativa inicial es:

```text
GET /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/spatial/intersections
```

Parámetros:

```text
min_lon
min_lat
max_lon
max_lat
limit (1..20)
```

La consulta usa `ST_MakeEnvelope` y `ST_Intersects`, requiere permiso `READ`, conserva los ámbitos de organización, finca y lote y devuelve como máximo 20 resultados.

Una envolvente con mínimo mayor o igual al máximo se rechaza. El cruce del antimeridiano no se normaliza automáticamente y queda fuera de este incremento.

## Autorización y no enumeración

- Las escrituras continúan exigiendo `DBIPermission.WRITE`.
- La consulta espacial exige `DBIPermission.READ`.
- Solo se consultan los `plot_id` presentes en los ámbitos autorizados del contexto.
- Una finca fuera de ámbito responde igual que un recurso inexistente.
- Un usuario con ámbito de finca pero sin ámbitos explícitos de lote obtiene una lista vacía, manteniendo la política cerrada existente.

## Dependencias

Se añaden únicamente:

```text
GeoAlchemy2==0.20.0
shapely==2.1.2
```

Las demás versiones del backend permanecen iguales al commit base.

## Incidencias detectadas durante la auditoría

1. Los listados normales no deben transferir geometrías completas; se separaron `PlotRead` y `PlotSpatialRead` y se difiere `boundary` en listados.
2. La consulta espacial quedó limitada a 20 resultados y el contrato a 10.000 posiciones por geometría.
3. Las barreras históricas fijaban revisiones antiguas como cabeza o prohibían geometría en todo el historial; se ajustaron para preservar sus migraciones originales dentro de un único linaje.
4. La primera infraestructura usaba `search_path = dbi, pg_catalog`, que ocultaba PostGIS instalado en `public`. Se corrigió a `dbi, public`, se concedió únicamente `USAGE` sobre `public` y se mantuvo revocado `CREATE`.
5. La prueba de infraestructura ahora bloquea cualquier regreso a `pg_catalog` explícito, ausencia de `public` o concesión de `CREATE` sobre `public`.

## Exclusiones preservadas

- Sin migraciones remotas o productivas.
- Sin creación de infraestructura o secretos.
- Sin raster, mosaicos, ortofotos o NDVI.
- Sin tiles, servidor de mapas o publicación pública.
- Sin topología avanzada, geocodificación o rutas.
- Sin cálculo automático de superficie.
- Sin cambios en `DATABASE_URL`, `User`, `Company`, frontend, WhatsApp o Google Sheets.

## Evidencia

- CI modular #264: 6/6 trabajos aprobados y todos los pasos posteriores del backend ejecutados, incluida la barrera espacial y el healthcheck.
- La auditoría posterior a #264 detectó la incompatibilidad de `search_path` antes de cualquier migración o despliegue real.
- Falta una nueva CI modular completa sobre la corrección de visibilidad PostGIS.
- Falta revisar conversaciones y estado fusionable del PR después de esa ejecución.
