# H12-SAFE-004 — Revocación institucional vs. firma INSPECT en la misma transacción

## Problema real

La migración 28 introdujo cargos DALGORO separados de los permisos de clientes,
pero una consulta `SELECT` podía leer un cargo activo y, mientras se
registraba una firma, otro proceso revocarlo. Una validación previa no basta
para garantizar vigencia **hasta COMMIT**.

## Contrato cerrado implementado

- **Migración 29, aditiva**: trigger PostgreSQL `BEFORE INSERT OR UPDATE OR
  DELETE` sobre `dbi_inspect_staff_roles`. Adquiere un **advisory lock
  transaccional exclusivo** antes de cualquier cambio del padrón. Los triggers
  previos de auditoría y prohibición de borrado continúan intactos.
- `DBIInspectionInstitutionalStaffDirectory.acquire_approval_snapshot()`
  adquiere el **mismo advisory lock en modo compartido**, mediante
  `pg_try_advisory_xact_lock_shared`. No requiere privilegios `UPDATE`
  sobre el padrón. Si otro proceso lo mantiene exclusivo, **deniega**
  en vez de esperar indefinidamente.
- Solo se admite el aislamiento PostgreSQL `READ COMMITTED`; se rechazan
  snapshots `REPEATABLE READ` o `SERIALIZABLE` que podrían haber leído
  privilegios anteriores a la adquisición del lock.
- `DBIInspectionStaffWorkflow._require_staff()` exige obtener el guard
  institucional **antes de consultar principal DBI, membresía, cargos y
  administrador único**. El lock queda asociado a la misma transacción SQL
  de la sesión que persiste los eventos INSPECT hasta que el llamador
  efectúa COMMIT/ROLLBACK.
- El directorio sigue verificando que exista exactamente **un administrador
  global** y cargos `technician`/`administrator` activos independientes
  para la misma persona cuando corresponde. No se admite autoacreditación
  desde navegador ni desde permisos de un cliente.

## Prueba CI real y controles de salida

En `.github/scripts/ci_dbi_inspection_institutional_staff.py`, sobre
PostGIS efímero y rol runtime sólo `SELECT`:

1. Si el lector posee lock compartido, una revocación externa llega a
   `lock_timeout` y no modifica el cargo; después del COMMIT del lector,
   puede revocarse legítimamente.
2. Si el emisor mantiene una revocación transaccional pendiente, el lector
   **no** obtiene el guard y se deniega.
3. Una sesión en `REPEATABLE READ` se deniega aunque no haya revocación.
4. Las pruebas anteriores mantienen unicidad global de administrador,
   técnicos múltiples, cargos dobles, auditoría inmutable, no reactivación
   y aislamiento de datos entre clientes.

## Restricciones importantes antes de habilitar rutas

El bloqueo protege cambios **al padrón institucional que pasan por el
motor PostgreSQL**, pero no prueba la vigencia de la membresía DBI durante
mutaciones independientes de permisos de cliente. La futura ruta HTTP debe
usar la misma `Session`, inyectar exclusivamente
`DBIInspectionInstitutionalStaffDirectory(session)`, no realizar un
COMMIT intermedio ni aceptar la variable privada
`_staff_dual_role_verified` desde HTTP.

Aún falta la acreditación real del propietario por autoridad DALGORO,
prueba integral de autenticación/ACL de las rutas y UI, y la publicación
READ verificada por Campaign. **Ningún usuario ni cargo es creado, ninguna
migración se aplica en producción y no se abre ninguna ruta** en este PR.
