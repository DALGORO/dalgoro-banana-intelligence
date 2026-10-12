# DBI-H12-AUTH-003 — Padrón DALGORO de cargos institucionales (migración 28)

## Qué se agregó

Se incorpora una **autoridad persistente INDEPENDIENTE de los roles de clientes**.

- `dbi_inspect_staff_roles`: cargos laborales globales `technician`
  y `administrator`. Dos registros del **mismo UUID** permiten que el
  administrador también sea técnico. No se limita el número de técnicos.
- `active_administrator_slot` es una columna calculada en PostgreSQL:
  vale `1` únicamente para administradores activos y `NULL` para
  técnicos y revocados. Su `UNIQUE` impide dos administradores activos
  incluso ante solicitudes concurrentes de alta.
- El directorio `DBIInspectionInstitutionalStaffDirectory` consulta roles
  institucionales activos y cumple `DBIInspectionStaffDirectoryPort`.
  Cuando se le inyecte explícitamente a `StaffWorkflow`, este seguirá
  comprobando permiso DBI `WRITE`/`APPROVE_AGRONOMIC`/`MANAGE`,
  membresía vigente y tenant/org/finca/lote exactos. NO se infiere
  personal DALGORO a partir de un administrador de cliente.
- `dbi_inspect_staff_audit_events` registra automáticamente por trigger
  PostgreSQL cada alta o revocación. El trigger bloquea eliminación,
  suplantación del UUID, cambio de cargo, reactivación y cambios
  posteriores en la acreditación. La API **no** recibe permisos de
  escritura sobre esas tablas.

## Estado real, sin afirmaciones de producción

**No se crean usuarios ni cargos automáticamente** en migración 28.
La lectura continúa fail-closed cuando falta el único administrador.
Un nombre, encabezado HTTP, JWT con rol `ADMIN` o una membresía DBI no
son prueba de relación laboral.

La acreditación de personas reales exige verificación humana desde una
autoridad DALGORO separada, con operador identificable y proceso controlado
de alta/revocación, fuera de la interfaz de cuentas de clientes. En este
PR **no se implementa un endpoint ni un aprovisionador de altas**: el
migrador tampoco se ejecuta contra staging o producción.

El adaptador queda disponible para conexión futura desde el servidor,
pero no se inyecta automáticamente en rutas; no basta la existencia
de la tabla para activar firmas. Antes de habilitar endpoints falta:
validación de identidad de operadores y personal real, control de acceso
de la base de producción, bloqueo transaccional entre revocación y firma,
pruebas de autorización HTTP y UAT de privacidad. El test CI no sustituye
la emisión legítima de una acreditación laboral.

## Prueba real en CI

`.github/scripts/ci_dbi_inspection_institutional_staff.py` usa exclusivamente
un PostgreSQL/PostGIS desechable llamado `dbi_test`, con guard estricto
`GITHUB_ACTIONS=true`, `DBI_ENVIRONMENT=test`, rol/host/DB exactos y
bandera de prueba. Verifica tabla inicialmente vacía, rechazo de dos
administradores, múltiples técnicos, dos cargos del mismo principal,
eventos de alta/revocación, no reactivación, no borrado, inmutabilidad de los eventos y adaptador real
operando con un rol que sólo tiene SELECT.

No se alteran INSPECT clínico, Campaign, GIS, IA, portal cliente,
endpoints HTTP ni despliegues.

## Brecha de activación conocida

El campo `accredited_by_ref` es una anotación de auditoría y **no demuestra
por sí mismo** que el acreditador sea un funcionario autorizado. El alta real
sigue pendiente de control institucional fuera de la API de clientes.
Además, las consultas `SELECT` ordinarias de la fachada todavía no
serializan firmas frente a revocaciones concurrentes; antes de activar
operaciones HTTP debe ensayarse un protocolo de bloqueo común o equivalente.
