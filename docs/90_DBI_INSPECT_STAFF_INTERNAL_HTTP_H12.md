# DBI · INSPECT: entrada HTTP institucional controlada (H12)

## Alcance

Tres operaciones **internas** reutilizan `DBIInspectionStaffWorkflow` sin
alterar sus políticas de identidad, cargos ni la persistencia INSPECT:

- `POST /api/v1/dbi/organizations/{org}/farms/{farm}/plots/{plot}/campaigns/{campaign}/inspection-links`
  con `{"observation_id":"<UUID>","observation_version_id":"<UUID>"}`
  responde `{"link_id":"<UUID>","created":true|false}`.
- `POST /api/v1/dbi/organizations/{org}/farms/{farm}/plots/{plot}/inspection-links/{link_id}/technical-validation`
  con cuerpo `{}` responde `{"stage":"technical_validated"}`.
- `POST /api/v1/dbi/organizations/{org}/farms/{farm}/plots/{plot}/inspection-links/{link_id}/administrative-authorization`
  con cuerpo `{}` responde `{"stage":"dual_approved"|"self_approved"}`.

`X-DBI-Tenant` y autenticación siguen siendo procesados por el resolvedor
DBI existente. Los UUID de fincas/lotes/campañas/vínculos pertenecen a
rutas **internas**, no a la UX del productor. No se agrega ninguna ruta
para autoacreditación, nombramiento de administrador o publicación ficticia.

## Activación deliberadamente cerrada

Por defecto `DBI_INSPECT_STAFF_HTTP_ENABLED` está AUSENTE: el servidor
**no registra** estas rutas. Solo el operador del proceso backend puede
montarlas con el valor exacto `1` y reinicio del servicio.

**No activar en producción** hasta:
1. migraciones DBI 28 y 29 aplicadas con autorización y prueba de rollback;
2. identidad de la persona DALGORO verificada contra el principal real,
   sin UUID inventados, y cargo(s) acreditados fuera de la API de clientes;
3. rol DBI runtime con `SELECT` pero sin `INSERT/UPDATE/DELETE` sobre
   registros institucionales y auditoría;
4. revisión de permisos, aislamiento entre tenants y prueba HTTP/PostGIS
   de extremo a extremo; confirmar que el despliegue no se activa
   automáticamente al fusionar `main`.

## Seguridad y persistencia

Cada POST usa la misma `Session` del contexto autenticado, crea el
directorio SQL de solo lectura, adquiere el guard compartido de cargos
(revisión 29) a través de `StaffWorkflow`, y completa exactamente un
`COMMIT` después de generar el vínculo/evento. Cualquier excepción revierte
la transacción. No se acepta `_staff_dual_role_verified`, `actor_ref`,
tenant o cargo desde el cuerpo HTTP. Los cuerpos de firma son vacíos y
estrictos (`422` para campos extraños).

Errores de identidad/cargo o recursos fuera de scope se expresan como
`404` genérico, conflictos como `409`. La autoría de firmas se obtiene
exclusivamente de `context.principal_ref` y del padrón DALGORO vigente.

La autorización del administrador con **ambos cargos activos** emite el
evento técnico y administrativo en un solo POST, ya implementado en
`campaign_approval_service.py`; técnicos diferentes conservan revisión
técnica previa. Se conserva el guard de publicación READ de Campaign e
INSPECT vigente, sin otra interfaz de publicación.

## Pruebas

`.github/scripts/ci_dbi_inspection_staff_http.py` revisa registro de rutas,
rechazo sin sesión autenticada, inyección correcta del directorio, DTO
mínimo, payloads falsificados, commit único y rollback ante denegaciones.
Las suites H12 ya existentes verifican política de aprobación y locks reales
en PostgreSQL/PostGIS efímero.

Este cambio no despliega la API, no acredita funcionarios, no aplica
migraciones y no modifica GIS, COPA_UP, Sigatoka, modelos ni UI del cliente.
