# DBI-H12-AUTH-001 — Frontera institucional de personal INSPECT (sin API)

> **Actualización de política:** [doc. 85](85_DBI_INSPECT_SINGLE_ADMIN_DUAL_ROLE_H12.md)
> permite una sola persona con doble cargo explícito y exige un único
> administrador DALGORO, sin limitar la cantidad de técnicos.

## Antecedente verificado
`main` ya contiene #217 (migración 27), #218 (vínculos), #221 (doble firma),
#223 (persistencia del vínculo), #224 (lectura doblemente aprobada sin endpoint)
y #225 (dos firmas probadas en PostGIS real). No se modifica ningún contrato
científico, algoritmo o migración en esta etapa.

Las tablas `dbi_principals`, `dbi_memberships`,
`dbi_membership_permissions` y `dbi_membership_scopes` determinan
**acceso DBI activo y acotado al lote**, pero **no acreditan vínculo laboral**
con DALGORO. Permiso `WRITE` o `MANAGE` concedido a un productor no puede
transformarlo en revisor técnico o autorizador institucional.

## Implementación

Se incorpora `inspection/staff_workflow.py` como fachada interna prevista
para las futuras rutas seguras de vínculo y firmas. Por cada operación:

1. Rechaza si falta permiso DBI preciso en tenant/organización/finca/lote.
2. Relee el principal y su membresía DBI persistidos por medio de
   `DBIAdminActorResolver`; exige estado activo y coincidencia **exacta**
   de permisos y ámbitos respecto al contexto obtenido de autenticación.
3. Consulta una fuente **independiente y confiable** de cargos laborales DALGORO,
   delimitada por UUID canónico del principal, tenant y organización.
   El contrato `DBIInspectionStaffDirectoryPort` NO admite un booleano del
   navegador ni reutiliza permisos generales como prueba de pertenencia.
4. Exige de una a dos acreditaciones `active`, como máximo una por cargo,
   todas del mismo principal/tenant/organización. El cargo `technician`
   revisa; el `administrator` autoriza, y el titular de ambos cargos
   puede aprobar con una única acción. El directorio debe acreditar que
   hay **exactamente un administrador DALGORO global**. El vínculo puede
   proponerlo cualquiera de ambos cargos si además dispone de `WRITE`.
5. Delega en los servicios de #218 y #221, que conservan los locks,
   versiones exactas, firma por actor, orden técnico→administrativo,
   separación de principales cuando son dos personas, o identidad común
   explícita en modo unipersonal; procedencia ráster→artefacto→job→Campaign.

El workflow usa la misma sesión DBI y **no hace commit/rollback**.
La frontera no reemplaza `DBIInspectionCampaignApprovalService` ni cambia
su API; los futuros endpoints deben invocar solo este workflow.

## Estado real y límites de activación

**No existe aún un repositorio concreto de cargos institucionales
DALGORO**. Ni el portal, ni el usuario autenticado, ni
`DBIMembershipPermission` suministran ese dato. La fachada recibe un
directorio confiable únicamente mediante inyección del servidor.
Si no se configura, **deniega toda operación**: no se introduce una
suposición favorable ni una lista `ADMIN` hardcodeada.

La batería `ci_dbi_inspection_staff_workflow.py` usa un directorio sintético
solo para probar la política. **No prueba que las personas de producción sean
empleados acreditados**. Antes de activar endpoints se necesita una autoridad
de personal (tabla con alta/revocación auditables o conector de RR. HH.),
aprobación separada del alta laboral, control transaccional de revocación
y ensayo con usuarios reales. No se han agregado cuentas ni nuevos roles.

Pruebas de denegación: sin directorio, cliente solo READ o incluso con WRITE
sin cargo, otro tenant/lote, principal revocado o incoherente, cargo errado,
acreditación inactiva, duplicada, cruzada de tenant/organización e intento de
autorización administrativa sin ambos privilegios. Se valida delegación exacta
solo con cargo y membresía activos simulados.

## No se modifica
- `app/api/v1/dbi_inspection.py` ni se exponen endpoints nuevos.
- La lectura privada READ-only de INSPECT continúa bloqueada.
- Ninguna migración/tabla/endpoint de administración de personal.
- Portal cliente, modelos de Sigatoka, extracción multiespectral,
  control de Campaign, staging, producción o almacenamiento externo.

## Próximo PR independiente
Implementar la **autoridad persistente y revocable de cargos** con un
procedimiento de acreditación propio de DALGORO, sin permitir que
administradores de cuentas de clientes se autoacrediten. Vincular el
`DBIInspectionStaffDirectoryPort` únicamente a dicha autoridad, probarlo
con identidades y transacciones DBI reales antes de abrir endpoints.
