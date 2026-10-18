# H14 / Etapa 2E — recepción privada experimental de QML

## Qué incorpora

Esta etapa añade un endpoint privado para recibir **un original QML** (estilo de uno de los seis índices). Es una capacidad limitada para pruebas locales; no recibe RGB, COG ni el paquete de 13 archivos, no certifica análisis científico, no aprueba ni publica.

Por defecto el endpoint responde 503. Solo puede habilitarse con DBI_SCIENTIFIC_QML_INTAKE_ENABLED=1 cuando DBI_ENVIRONMENT es test, development o local. Está bloqueado expresamente en staging y production, incluso si se configura el flag. No se ha modificado Render, esquema de base de datos, migraciones ni la interfaz del cliente.

## API

POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/scientific-intake/qml/{index}

Requiere autenticación DBI, X-DBI-Tenant y permiso MANAGE sobre lote; comprueba Campaign de tipo multispectral con ámbito y estado permitidos mediante consulta a base de datos. Responde 404 ante falta de autoridad, campañas ajenas, estados aprobados o publicados.

El cuerpo es el archivo QML **sin cambios byte a byte**, enviado como text/plain, sin compresión. Cabeceras obligatorias: X-DBI-Original-Relative-Path (ruta canónica .qml), X-DBI-Original-Size (1..262144) y X-DBI-Original-SHA256 (hexadecimal SHA-256 minúsculo). El servidor compara Content-Length si existe, cuenta bytes realmente recibidos y calcula el SHA-256 de nuevo antes de escribir.

Se usa el puerto privado DBIPrivateObjectStore con propósito technical-sources. La identidad UUIDv5 es determinista a partir de tenant, organización, finca, lote, Campaign, índice, ruta, tamaño y hash; nunca se sobrescribe un original diferente. Reintentos idénticos devuelven HTTP 200 (en vez de 201 nuevo) con el mismo object_id. El recibo no contiene URL ni grant público. Declara transport_hash_verified=true pero bundle_complete=false, scientific_validated=false, institutional_approved=false y published=false.

## Límites de seguridad y producción

- No existe un manifiesto duradero consultable por Campaign, ni auditoría institucional transaccional de los 13 elementos; los recibos QML individuales son provisionales.
- Se guardan bytes originales, sin interpretar XML ni validar rampas QGIS o atribución científica. Un worker aislado deberá validar después.
- El almacenamiento simple S3 limita objetos a 64 MiB: los COG y RGB grandes requieren integración multipartes, cuotas y persistencia propia.
- La UI administrativa sigue utilizando únicamente borradores locales y validación de Campaign; todavía no hay botón de subida QML.
- La recepción productiva continúa **prohibida** hasta completar migración revisada, auditabilidad, recuperación de reintentos, pruebas con datos reales, aprobación institucional y revisión de seguridad.

## Prueba

La suite offline .github/scripts/ci_dbi_scientific_qml_intake.py ejecuta almacenamiento in-memory, denegación READ, falta de flag, producción bloqueada, estados de Campaign, rutas maliciosas, tamaños/hashes inválidos, preservación byte a byte, idempotencia y aislamiento entre tenants. Se ejecuta en CI modular. No usa credenciales, S3 real, base de datos remota ni despliegue.
