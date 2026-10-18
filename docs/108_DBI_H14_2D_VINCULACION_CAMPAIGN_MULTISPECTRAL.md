# H14 / Etapa 2D — Vinculación de dos carpetas con Campaign MULTI real (solo lectura)

## Problema que resuelve
El borrador local H14 de 1 RGB + 6 COG + 6 QML (`PR #254`) identifica campaña, finca y lote solo mediante datos declarados por el navegador. La comprobación offline de archivos reales (`PR #255`) verifica estructura científica, SHA-256 y solape, **pero tampoco consulta la Campaign persistida**.

Esta etapa incorpora una verificación **privada y autorizada por backend** de la identidad de Campaign sin subir originales ni habilitar publicación.

## Uso administrativo
En el visor de una finca/lote que tenga `MANAGE`, dentro de «Gestionar y publicar capas GIS», se seleccionan las dos carpetas y una Campaign real de tipo **multispectral**. Si existen exactamente los 13 candidatos sin ambigüedades, aparece **«Comprobar campaña en servidor (sin subir archivos)»**.

La acción envía **solo metadatos del borrador local** (carpetas, nombres relativos, tamaños, roles, y campos obligatorios siempre `sha256=null`, `file_content_verified=false`). No utiliza `FileReader`, `arrayBuffer`, `FormData` ni la API de almacenamiento.

La respuesta visible distingue:
- «Campaña multiespectral vinculada al lote»: identidad de Campaign real y permiso MANAGE corroborados por el servidor.
- «Los archivos aún no están validados ni subidos»: ningún contenido científico comprobado en ese servidor.

La marca de vinculación se asocia al borrador exacto en memoria: al cambiar una carpeta o Campaign no se muestra como válida la comprobación anterior.

## Contrato del servidor
Endpoint (POST, JSON, solo MANAGE):
`/api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/scientific-intake/scope-preflight`

El servidor exige:
- scope de autorización completo tenant/organización/finca/lote y permiso `MANAGE`, antes de consultar Campaign;
- Campaign existente por consulta *scope exacta* (no basta un UUID bien formado), tipo `multispectral`;
- fase `DRAFT`, `PROCESSING`, `ANALYZED` o `TECHNICAL_REVIEW`; deniega `SAMPLING_READY`, fases de campo, `APPROVED` y `PUBLISHED`, así como cualquier `approved_at` o `published_at` no nulo;
- formato exacto `dbi-h14-scientific-reception-draft.v1`, 13 elementos, uno RGB y 6 pares COG/QML, carpetas coherentes, rutas canónicas, sin `..`, duplicados, archivos vacíos ni campos imprevistos;
- `scientific_validated=false`, `server_received=false`, `institutional_approved=false`, `published=false`; ninguna huella suministrada puede pretender validación.

Respuestas no autorizadas, de Campaign ajena o no disponible: **404**, sin revelar la existencia del recurso. Contratos inválidos: **422**. No se escribe en DB, no se concede acceso temporal a S3, no se modifica el estado de Campaign.

En caso de éxito, el servidor puede declarar `campaign_link_verified=true` **solo para identidad de Campaign**, manteniendo obligatoriamente `hashes_verified=false`, `file_content_verified=false`, `scientific_validated=false`, `server_received=false`, `institutional_approved=false`, `published=false`, con disposición `campaign_scope_verified_only_no_upload`.

## Seguridad y límites
Este resultado **no acredita** que los contenidos RGB/COG/QML realmente pertenecen a esa Campaign. Se necesita un cotejo inmutable por hashes y fuentes verificadas una vez que exista recepción privada. El endpoint no almacena una aprobación: si se usara para un paso posterior, ese paso **deberá consultar nuevamente la DB y estado, sin confiar en una respuesta anterior**.

El diseño visible del cliente continúa mejorándose sobre capas realmente publicadas; no se muestran seis índices si aún no existen COG aprobados.

## Próxima etapa
Preparar el almacenamiento privado y esquema de manifestación por índice/COG/QML con controles de cuotas, hashes de servidor, idempotencia y auditoría; revisar la migración requerida antes de ejecutarla y conectar después el worker scientific preflight con objetos privados ya recibidos. Finalmente: previsualización institucional, aprobación por cada producto, publicación atomic/scoped y controles de índices en portal cliente.

Sin despliegue Render, sin migraciones DB, sin generación de estilos QML ficticios. Pruebas: `.github/scripts/ci_dbi_scientific_scope_preflight.py` y `frontend/tests/scientificScopePreflightUI.test.mjs`.
