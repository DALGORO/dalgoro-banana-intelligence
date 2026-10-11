# DBI-PORTAL-GIS-004B · Revisión visual y publicación explícita de GIS

## Qué cambia para DALGORO

Para un archivo SHP ZIP o GPKG ya `prepared` por el worker separado:

1. Gestor con permiso `MANAGE` abre **Mis fincas → Lote → Campaign**.
2. En **Archivos GIS y estado de revisión** selecciona **Revisar vista previa en el mapa**. El portal consulta la vista previa privada y sitúa la fecha de captura tomada de la Campaign DBI correspondiente, no del nombre del archivo. Dibuja la vista previa sin incorporarla al catálogo público de capas.
3. El gestor verifica geometría, ubicación y atributos reales. Solo para esa importación revisada se habilita **Aprobar y publicar esta capa**.
4. El servidor vuelve a exigir tenant, organización, finca, lote, permiso MANAGE y Campaign de origen. Comprueba SHA-256, número de entidades, geometrías y GeoJSON WGS84 del derivado. Entonces guarda `DBIPortalVectorLayer` y registra quién aprobó y cuándo.
5. Después de confirmar la transacción, el visor incluye la capa en el catálogo publicado; usuarios con permiso READ de ese lote pueden visualizarla y consultar atributos. Reintentos exactos no duplican capas.

Una importación en `received`, `processing` o `failed` **no puede publicarse** por este endpoint. La vista previa privada tampoco puede solicitarse como usuario READ.

## Persistencia / migración

`dbi_0024_gis_approval` amplía `dbi_portal_gis_imports` con:
- `status='published'`, distinto de `prepared`
- `published_layer_id`: referencia FK a la capa efectivamente publicada
- `approved_by_ref` y `approved_at` para trazabilidad

Se conserva el GPKG o ZIP original en almacenamiento privado. `DBIPortalVectorLayer.source_bytes` recibe únicamente el **GeoJSON derivado validado**, nunca el archivo original. El estado publicado, la identidad de aprobación y el registro de capa se confirman en la misma transacción.

## API

`POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/gis-imports/{import_id}/publish`.

Respuesta: metadata de la capa publicada. Se exige MANAGE y scoping completo al publicar. La aprobación no puede ser forzada por un navegador que omita el paso de conversión: el backend solo admite importaciones `prepared` con preview íntegra.

## Límites pendientes antes del uso comercial

No existen en este incremento un daemon productivo GIS, un scheduler persistente, configuración y supervisión S3 compartido en Render, ni pruebas E2E con los archivos reales de los clientes. El worker `portal_gis_prepare_local.py` sigue reservado para desarrollo/local, y las migraciones hasta `dbi_0024_gis_approval` deben aplicarse mediante el proceso de control DBI.

La aprobación requiere comprobación humana de la pertinencia científica/agronómica de la capa y de su correspondencia con la Campaign correcta; la plataforma **no afirma validar semánticamente** si las geometrías representan la misma finca solo por sus coordenadas.

## Pruebas

`ci_dbi_gis_approval.py`: bloqueo de READ y plot ajeno, rechazo de hash adulterado, bloqueo de original no convertido, persistencia de aprobación y reintento idempotente. El resto de CI incluye compilación web, conversión GIS sintética real, migración PostGIS y almacenamiento privado.

No se modifican Density, GOLD, YOLO ni sus productos técnicos originales.
