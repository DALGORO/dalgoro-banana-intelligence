# DBI-PORTAL-GIS-007E · Revisión y publicación de GeoPackage seleccionado (microhito D)

## Objetivo y resultado esperado
Cerrar el circuito **multicapa** ya desarrollado sin duplicar servicios: una
selección exacta autorizada (`selected_layer`) inicia la preparación en el
worker GIS aislado; el derivado permanece privado bajo `prepared` hasta
que un gestor con `MANAGE` abra la vista previa y apruebe explícitamente
su publicación. Solo entonces se crea una capa vectorial consultable por
usuarios con `READ` del mismo tenant, finca, lote y Campaign.

## Cambio funcional mínimo
El endpoint de vista previa `GET .../gis-imports/{import_id}/preview`
revalida con `_campaign(...)` la pertenencia actual de la Campaign al
tenant, organización, finca y lote, **antes** de entregar el GeoJSON privado.
Se reutiliza el mismo método de verificación ya usado por la selección y
la publicación. No se requiere modificación de esquema ni de UI.

## Gate de integración en CI
El nuevo script `.github/scripts/ci_dbi_gis_selected_layer_lifecycle.py`
se ejecuta en el backend del `CI modular` de GitHub. Verifica de extremo a
extremo la composición de las funciones reales de API y worker utilizando
fuente sintética, almacenamiento privado en memoria y sesiones simuladas.
Prueba:
- GeoPackage multicapa sin selección: no se reclama ni publica.
- Selección exacta exclusiva de `MANAGE`, tenant y Campaign; repetición
  idempotente y rechazo de cambiar la elección.
- Preparación en el worker con huella del original, capa elegida y manifest;
  transición `needs_selection -> processing -> prepared`, sin capa pública.
- Vista previa privada con geometrías/atributos, visible solo a `MANAGE`;
  denegación por otro recibo, otro lote, Campaign ajena y cliente `READ`.
- Rechazo de publicación con derivado no preparado, Campaign fuera de ámbito
  o huella de vista previa alterada.
- Publicación explícita única (atributos, autor y fecha de aprobación),
  conservando identidad tenant/organización/finca/lote/Campaign.
- Idempotencia de publicación; lectura de capa vectorial exclusivamente
  por usuario autorizado del lote; aislamiento de campañas en el listado.
- Ausencia de artefactos temporales residuales del worker.

La prueba **no** sustituye UAT real ni confirma funcionamiento productivo:
no ejecuta GDAL/pyogrio ni S3 remoto, PostgreSQL productivo, Render o un
GeoPackage de cliente. Permanecen las CI independientes existentes para
conversiones geoespaciales reales con fixtures, seguridad, PostGIS, lint y
motor científico. No se activa el servicio por fusionar este código.

## Microhito siguiente (no incluido)
Planificar validación controlada de despliegue, migraciones en staging y
un recorrido de aceptación con un GeoPackage multicapa real autorizado,
con registro de evidencia; nunca asumir que servicios/credenciales existen.
