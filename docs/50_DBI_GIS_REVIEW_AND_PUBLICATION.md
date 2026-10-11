# DBI-PORTAL-GIS-005 · Aprobación explícita antes de publicar un GIS

## Flujo operativo verificado a nivel de código

1. Un gestor con permiso `MANAGE` selecciona el lote y su Campaign; sube el SHP ZIP o GeoPackage. Queda `received`, privado.
2. El proceso geoespacial **aislado**, invocado independientemente, prepara un GeoJSON validado que queda `prepared`, solo consultable por el gestor. La preparación no publica.
3. En el portal, **Revisar geometrías y atributos** muestra esa vista previa en el mapa del gestor y permite consultar propiedades de las entidades.
4. Solo la acción separada **Aprobar y publicar en el lote** ejecuta `POST .../map/gis-imports/{import_id}/publish`; el servidor vuelve a comprobar tenant, organización, finca, lote, Campaign, `MANAGE`, SHA-256, cantidad de entidades, validez y normalización del GeoJSON.
5. Una transacción crea (o reutiliza de forma idempotente) la capa `DBIPortalVectorLayer` y deja en el recibo `status='published'`, `published_layer_id` y fecha de aprobación. Solo entonces los clientes con `READ` pueden consultar esa capa por los endpoints ya existentes.

### Protección de permisos e integridad

- Un usuario `READ`, otro tenant, otra finca u otro lote no pueden acceder a la preview ni aprobar.
- Un recibo `received`, `processing` o `failed` nunca se publica.
- La vista previa no se ofrece al cliente mientras siga `prepared`. La visualización temporal se incorpora al visor solo en sesión `MANAGE` y desaparece al cerrar.
- Un replay del botón tras una aprobación devuelve la capa asociada, sin crear una nueva.
- Si el GeoJSON derivado cambió desde su validación, la publicación se rechaza.
- Restricciones de PostgreSQL impiden `published` sin capa y marca temporal; migración `dbi_0024_gis_publication`.
- Mantiene originales privados para auditoría. No toca el motor científico, máscaras GOLD ni inferencia.

## Alcance real y activación

El código web/backend agrega revisión y aprobación **solo para una preview ya preparada**. No incorpora scheduler de producción ni configura S3 duradero; el proceso GIS aislado anterior está limitado al escenario local/development hasta configurar un worker y storage seguros. No confundir integración en `main` con despliegue en Render.

Antes de ponerlo en manos de un cliente: migraciones DBI hasta `dbi_0024_gis_publication`, almacenamiento durable compartido, worker gestionado con límites de recursos, HTTPS, UAT con SHP/GPKG verdaderos y verificación de perfiles READ/MANAGE desde dos sesiones diferentes.
