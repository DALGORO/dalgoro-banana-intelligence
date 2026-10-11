# DBI-PORTAL-GIS-007C · Elección MANAGE de capa GeoPackage (microhito B)

## Objetivo
Un gestor de DALGORO puede seleccionar **una sola capa geométrica** entre los nombres
detectados y persistidos por el worker S3 en el microhito A (#192).
Este cambio **no convierte, no crea preview y no publica** ningún resultado.

## Flujo
1. El GPKG privado ya verificado tiene estado `needs_selection` y
   `available_layers` (de 2 a 20 nombres exactos).
2. Solo el gestor con permiso `MANAGE` del tenant/organización/finca/lote ve
   el selector dentro de **Archivos GIS y estado de revisión**.
3. Al confirmar, el navegador envía únicamente el nombre exacto:
   `POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/gis-imports/{import_id}/select-layer`
   con body JSON `{"layer":"plantas"}`.
4. FastAPI **no usa GDAL/Pyogrio**. Revalida MANAGE, identidad completa del
   recibo, Campaign asociada, estado `needs_selection`, tipo `gpkg` y
   pertenencia exacta del nombre al arreglo **guardado por el worker**.
5. Bajo `SELECT ... FOR UPDATE` guarda `selected_layer`. Repetir exactamente
   la misma opción retorna el recibo sin escrituras. Una elección distinta
   posteriormente responde HTTP 409; no se permite cambiar la capa de
   un recibo ya elegido en este microhito.
6. La importación permanece en `needs_selection` con etiqueta
   **Capa elegida · pendiente de conversión**. El claim del worker todavía
   ignora este estado, incluso cuando la elección ya está presente.
   La revisión/publicación sigue requiriendo una preview `prepared`.

## Persistencia / despliegue
Migración **`dbi_0026_gpkg_layer_choice`** agrega
`dbi_portal_gis_imports.selected_layer` (`VARCHAR(100)`, nulo inicialmente)
y un CHECK que exige GPKG, `available_layers` existente y coincidencia
del nombre dentro del JSONB; no introduce una tabla ni un almacenamiento
nuevo. Sigue vigente `dbi_0025_gpkg_layer_options`.

Para habilitarlo en un ambiente real se debe aplicar la migración mediante
el flujo DBI autorizado. No implica configuración de Render, worker continuo,
credenciales, aplicación de migración productiva ni prueba UAT con archivos
reales de productores.

## Validación
El test offline de importaciones comprueba permisos MANAGE/READ, tenant,
organización, finca/lote/Campaign, `FOR UPDATE`, formato/estado, payload
estricto (sin campos extra), nombre inexistente, idempotencia, inmutabilidad,
rollback ante falla de DB y que no existe preview publicable.
Además, el CI normal valida migraciones PostgreSQL/PostGIS, backend,
frontend, secretos y GIS sin alterar los componentes científicos.

## Próximo microhito
Microhito C: extender exclusivamente el **worker aislado** para reclamar
una importación `needs_selection` con `selected_layer` válido y convertir
solo esa capa. Mantener límites, fencing, integridad de fuente, SHA, validación
de manifiesto e idempotencia antes de generar la preview privada. Ninguna
aprobación/publicación automática.
