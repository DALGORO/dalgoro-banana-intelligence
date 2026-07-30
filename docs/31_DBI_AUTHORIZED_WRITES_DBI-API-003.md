# DBI-API-003 — Escrituras DBI autorizadas

## Objetivo

Incorporar operaciones HTTP de escritura controlada para finca, lote y campaña usando exclusivamente la sesión DBI, `DBIAccessContext` y transacciones explícitas, sin mezclar la base heredada.

## Superficie implementada

- `POST /api/v1/dbi/organizations/{organization_ref}/farms`
- `PATCH /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}`
- `POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots`
- `PATCH /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}`
- `POST /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/campaigns`
- `PATCH /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/campaigns/{campaign_id}`

## Autorización

Toda operación exige `DBIPermission.WRITE` y valida el ámbito exacto antes de consultar o modificar:

- organización para crear fincas;
- finca para crear lotes y campañas;
- finca o lote exactos para actualizaciones.

Una identidad con permiso únicamente `READ` no puede ejecutar escrituras. Los recursos inexistentes y los recursos fuera de ámbito producen la misma respuesta pública `404`, evitando enumeración entre organizaciones.

## Contratos

Los modelos de entrada usan `extra="forbid"`, límites de longitud, estados explícitos y validación temporal. Las actualizaciones vacías se rechazan y los campos obligatorios no admiten `null`.

Los campos actualizables se controlan con listas explícitas:

- finca: `name`, `status`;
- lote: `name`, `area_hectares`, `status`;
- campaña: `name`, `starts_at`, `ends_at`, `status`.

No se permite actualizar códigos, claves foráneas, identificadores internos ni referencias de tenant mediante asignación masiva.

## Transacciones

Cada operación usa una única sesión DBI y ejecuta:

1. autorización;
2. validación de relaciones y existencia;
3. creación o aplicación explícita de cambios;
4. un único `commit`;
5. `refresh` de la entidad antes de responder.

Los conflictos de integridad ejecutan `rollback` y se traducen a una respuesta uniforme `409`. La dependencia `get_dbi_session` mantiene además rollback ante excepciones no gestionadas y cierre garantizado de la sesión.

## Aislamiento preservado

- Sin `SessionLocal`, `get_db` ni sesión heredada.
- Sin modelos `User` o `Company` en la superficie DBI.
- Sin uso de `DATABASE_URL` para DBI.
- Sin eliminaciones físicas.
- Sin escrituras de identidades, membresías o permisos.
- Sin activos, binarios, URLs firmadas o ejecución geoespacial.
- Sin PostGIS, migraciones online, frontend, WhatsApp ni despliegues.

## Validación automática

La barrera `.github/scripts/ci_dbi_authorized_writes.py` comprueba de forma offline:

- presencia de las seis operaciones;
- rechazo de campos desconocidos y actualizaciones vacías;
- rechazo de valores nulos en campos obligatorios;
- rechazo de áreas no positivas y fechas inconsistentes;
- denegación de escrituras con permiso solo `READ`;
- commit y refresh una sola vez en éxito;
- rollback y respuesta `409` ante conflicto;
- actualización exclusiva de campos permitidos;
- ausencia de sesión y modelos heredados.

La barrera aparece como paso independiente `Validar escrituras DBI autorizadas offline` dentro del trabajo de backend.

## Incidencias detectadas y corregidas

### Regresión en prueba de lecturas

Al compartir rutas `GET` y `PATCH`, la prueba de lecturas reemplazaba los métodos registrados para una misma ruta. Se corrigió para acumular todos los métodos sin relajar la exigencia de `GET`.

### Valores nulos en actualizaciones

La auditoría detectó que algunos campos obligatorios podían recibir `null`. Se añadieron validaciones de contrato para rechazarlos antes de llegar a la base de datos.

### Trazabilidad CI

La validación de escrituras inicialmente se ejecutaba dentro del smoke general. Se separó como paso CI independiente para identificar fallos con precisión.

## Evidencia

- CI modular #226: fallo auditado en la prueba heredada de rutas compartidas.
- CI modular #228: 6/6 trabajos aprobados después de corregir la acumulación de métodos.
- CI modular #236: 6/6 trabajos aprobados tras reforzar nulos y separar la barrera de escrituras.
- En #236 se ejecutaron y aprobaron todas las pruebas posteriores del backend, incluido healthcheck.

## Resultado

La API dispone de escrituras agrícolas DBI mínimas, autorizadas, transaccionales y no enumerables. El incremento no introduce conexiones productivas ni amplía el alcance hacia archivos, procesamiento o infraestructura espacial.
