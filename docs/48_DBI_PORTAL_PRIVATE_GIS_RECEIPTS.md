# DBI-PORTAL-GIS-003 · Recepción privada de SHP ZIP y GeoPackage desde el portal

## Para el gestor DALGORO

Desde **Mis fincas → Lote → Fecha → Añadir resultado cartográfico**:

1. Elegir una Campaign técnica ya registrada. Si no existe, primero registrar el levantamiento correcto.
2. Elegir tipo de capa y seleccionar el archivo original.
3. **GeoJSON WGS84** hasta 2 MiB: se valida y publica inmediatamente usando el endpoint de capas existente.
4. **GeoPackage (.gpkg) o Shapefile completo comprimido (.zip)** hasta 30 MiB: se carga desde el navegador al almacén privado DBI y queda como **Recibido · pendiente de conversión**. No aparece en la cuenta lectora ni en el mapa.

El mensaje **«recibido» no significa que se convirtió o publicó el archivo**. La conversión en worker geoespacial, la comprobación de CRS/geométricas completas y la promoción del derivado a capa visible siguen pendientes. No se simula ese trabajo.

## Frontera de seguridad

- Token de sesión DBI y permisos `MANAGE` para el **tenant, organización, finca y lote exactos**, más Campaign scoped con fecha real declarada.
- Se reciben cuerpos binarios HTTP por streaming; hasta 30 MiB de origen con temporal efímero acotado. FastAPI no importa GDAL, no ejecuta Pyogrio y no descomprime Shapefiles.
- Archivos ZIP con una única capa SHP plana y .shp/.shx/.dbf/.prj; se rechazan entradas cifradas, symlinks, traversal, duplicados, tipos extraños y expansión ZIP sospechosa. La validación GIS real del contenido será exclusiva del worker.
- Para GPKG se comprueba la firma SQLite, no se presupone que el GeoPackage es válido solo por la extensión.
- El original se guarda en el **objeto privado** `DBIStoragePurpose.TECHNICAL_SOURCE` usando dirección derivada del tenant + UUID opaco. No se guarda contenido ZIP/GPKG en PostgreSQL. Tamaño y SHA-256 se verifican al guardar y se registran internamente.
- Tabla `dbi_portal_gis_imports`, migración `dbi_0022_portal_gis_imports`: asociación a Campaign y lote, nombre de origen, MIME/formato, usuario, estado y huella interna. Las respuestas públicas no exponen object_key, hash, rutas ni credenciales.
- El endpoint de listados de archivos recibidos exige también permiso MANAGE: un usuario solo de lectura no puede enumerar originales.
- En fallo de DB tras la escritura, se intenta retirar inmediatamente el objeto del almacén privado. Para incidentes de infraestructura se requiere limpieza operativa posterior.

## Estado real y despliegue

La fase actual solo admite **recepción y custodia**. No existe en esta mejora una cola de workers activa ni conversión automática. Las entradas permanecen en `received` hasta un incremento posterior que programe una conversión profesional auditable.

Para activar esta pantalla en un entorno real:
- Ejecutar **migraciones DBI hasta `dbi_0022_portal_gis_imports`** mediante el procedimiento de aplicación controlado.
- Configurar almacenamiento privado DBI persistente (preferentemente S3 compatible) con permisos de escritura y retiro; el almacenamiento local efímero de Render no sirve como depósito duradero.
- Verificar cuentas de gestor y lector con lotes de prueba y campaña real, además de los límites de tamaño/HTTPS/proxy del despliegue.
- No habilitar comercialmente esta función sin el workflow worker y una prueba de extremo a extremo con archivos QGIS reales.

Este módulo no modifica GOLD, YOLO, segmentación, Density ni cálculos multiespectrales.
