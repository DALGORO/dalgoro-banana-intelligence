# DBI-MIG-001 — Aplicación controlada de migraciones DBI

## Estado

Implementación completa en el PR #48, pendiente de auditoría final y autorización de integración.

Incluye:

- interfaz operativa `plan`, `verify` y `apply`;
- plan Alembic offline con huella SHA-256;
- preflight conectado mediante consultas de solo lectura;
- validación del privilegio efectivo del rol migrador;
- advisory lock PostgreSQL de sesión;
- `upgrade head` sobre la misma conexión;
- postflight obligatorio e idempotencia;
- pruebas offline y PostgreSQL/PostGIS efímero en GitHub Actions.

No admite producción, staging conectado, hosts remotos, `downgrade`, `stamp`, reparación automática ni borrado de bases.

## Entrada operativa

```bash
python -m app.dbi.migration_cli [plan|verify|apply]
```

Al omitir la operación se ejecuta `plan`, que no abre conexiones.

La herramienta lee únicamente:

```text
DBI_ENVIRONMENT
DBI_DATABASE_URL
```

`DATABASE_URL` no se usa.

## Matriz autorizada

| Operación | Fuera de CI | GitHub Actions | Conexión |
|---|---|---|---|
| `plan` | Ambiente no productivo válido | Solo `test` | Ninguna |
| `verify` | Solo `development` local | Solo `test` efímero | Local o loopback |
| `apply` | Bloqueado | Solo `test` efímero | Local o loopback |

Reglas:

- `production` se rechaza siempre;
- staging conectado está bloqueado;
- CI solo admite `dbi_test`;
- el usuario debe ser exactamente `<database_name>_migrator`;
- los hosts conectados permitidos son `localhost`, `127.0.0.1` y `::1`;
- ningún error imprime URL, contraseña o detalle sensible.

## Plan

Ejemplo local sin contraseña incrustada:

```bash
export DBI_ENVIRONMENT=development
export DBI_DATABASE_URL='postgresql+psycopg://dbi_development_migrator@127.0.0.1:5432/dbi_development'
python -m app.dbi.migration_cli
```

Para guardar el SQL offline en un archivo nuevo:

```bash
python -m app.dbi.migration_cli plan --sql-output dbi-plan.sql
```

El archivo se crea en modo exclusivo y nunca se sobrescribe.

`plan` ejecuta conceptualmente `upgrade head --sql`, sin motor, socket ni SQL online. La evidencia JSON contiene ambiente, base, rol esperado, cabeza, SHA-256 y ruta opcional. El SQL se rechaza si contiene la URL o contraseña.

## Verify

```bash
python -m app.dbi.migration_cli verify
```

El preflight ejecuta únicamente `SELECT` y comprueba:

1. base actual;
2. usuario actual;
3. `search_path` comenzando por `dbi, public`;
4. ausencia de `SUPERUSER`, `CREATEDB`, `CREATEROLE`, replicación y `BYPASSRLS`;
5. ausencia de membresías en otros roles, incluso cuando no se hereden automáticamente;
6. que el migrador no sea propietario de la base;
7. que el migrador no sea propietario del esquema `dbi`;
8. PostGIS instalado;
9. esquema `dbi` existente;
10. tabla de versión y revisión actual cuando existan;
11. una sola revisión perteneciente al linaje reconocido;
12. una sola cabeza Alembic.

Se permite una base vacía sin tabla de versión cuando infraestructura, PostGIS, esquema y rol ya fueron aprovisionados correctamente.

## Apply

`apply` está bloqueado fuera de GitHub Actions. En CI exige simultáneamente:

- `GITHUB_ACTIONS=true`;
- `DBI_ENVIRONMENT=test`;
- base `dbi_test`;
- rol `dbi_test_migrator` sin privilegios efectivos adicionales;
- host local o loopback;
- confirmación exacta `APPLY dbi_test`.

Orden de operación:

1. valida ambiente, base, rol y host;
2. valida confirmación;
3. genera plan offline y SHA-256;
4. ejecuta preflight;
5. adquiere `pg_try_advisory_lock` sin espera;
6. repite el preflight bajo lock;
7. omite Alembic si ya está en `head`;
8. ejecuta una sola llamada a `upgrade head`;
9. ejecuta postflight;
10. exige la cabeza autorizada;
11. libera el lock en `finally`.

No existen `--yes`, confirmaciones genéricas ni una operación predeterminada destructiva.

## Misma sesión PostgreSQL

El advisory lock es de sesión. Preflight, lock, Alembic y postflight usan la misma conexión SQLAlchemy.

`dbi_alembic/env.py` no crea un motor online. Exige:

```python
Config.attributes["connection"]
```

`migration_runner.py` entrega esa conexión a Alembic y ejecuta exclusivamente `upgrade head`. Las barreras estáticas impiden `engine_from_config`, una segunda conexión, `downgrade` o `stamp`.

## Concurrencia

La clave estable deriva de:

```text
dalgoro-dbi-migrations-v1
```

`pg_try_advisory_lock` falla inmediatamente cuando otra sesión posee el bloqueo. La prueba real abre dos conexiones y confirma que la segunda no puede adquirirlo. La liberación siempre se intenta; una excepción de la operación original no se oculta.

## PostgreSQL/PostGIS efímero

Workflow:

```text
.github/workflows/dbi-migration-integration.yml
```

Características:

- runner aislado;
- PostgreSQL 16/PostGIS 3.5 fijado por digest;
- autenticación `trust` limitada al contenedor desechable;
- base `dbi_test`;
- propietario separado del migrador;
- migrador sin privilegios administrativos, `BYPASSRLS`, membresías ni propiedad;
- URL loopback sin contraseña;
- destrucción del contenedor al terminar.

El fixture aprovisiona base, roles, PostGIS y esquema por separado. La herramienta de migración no crea ni elimina infraestructura.

La prueba verifica:

- plan y preflight sin cambios de esquema;
- barreras de privilegios efectivos;
- exclusión concurrente real;
- aplicación desde base vacía hasta `dbi_0006_plot_boundaries`;
- segunda ejecución idempotente;
- conjunto exacto de tablas DBI;
- ausencia de tablas heredadas;
- `boundary` como `MULTIPOLYGON` SRID 4326;
- índice GiST `ix_dbi_plots_boundary_gist`;
- restricciones de geometría vacía y válida;
- funciones PostGIS operativas.

## Evidencia no sensible

Las operaciones exitosas escriben JSON en `stdout`. Los errores usan `stderr` y códigos distintos de cero.

Ejemplo conceptual:

```json
{
  "after_revision": "dbi_0006_plot_boundaries",
  "applied": true,
  "before_revision": null,
  "database": "dbi_test",
  "environment": "test",
  "expected_migrator_role": "dbi_test_migrator",
  "head_revision": "dbi_0006_plot_boundaries",
  "operation": "apply",
  "plan_sha256": "<sha256>"
}
```

Nunca se registra contraseña, URL completa, certificado, host remoto o cadena heredada.

## Recuperación

Ante un fallo:

1. se devuelve código distinto de cero;
2. el lock se libera en `finally`;
3. no se ejecuta `stamp`, `downgrade` ni reparación;
4. debe revisarse la evidencia del plan y la revisión actual;
5. una revisión desconocida o múltiples filas bloquean nuevos intentos;
6. el contenedor efímero se destruye;
7. cualquier corrección requiere una migración revisada, no editar manualmente la tabla de versión.

Alembic delega cada revisión transaccional a PostgreSQL. El postflight impide declarar éxito cuando la cabeza no quedó confirmada.

## Responsabilidades

### Infraestructura

- crear base, roles, esquema y extensión;
- mantener propietario y migrador separados;
- asignar secretos fuera del repositorio;
- impedir `CREATE` en `public` a roles operativos;
- conceder solo `USAGE` sobre `public` para PostGIS;
- establecer `search_path = dbi, public`;
- mantener el migrador sin atributos elevados ni membresías.

### Operador

- revisar ambiente, base, rol y SHA-256;
- no reutilizar evidencia de otro commit;
- no ejecutar `apply` fuera del workflow autorizado;
- detenerse ante revisión, propiedad o membresía divergente.

### Herramienta

- fallar cerrado;
- no aprovisionar infraestructura;
- no tocar la base heredada;
- no exponer secretos;
- no admitir producción;
- aplicar únicamente `upgrade head`.

## Evidencia de CI

Cada modificación exige dos controles verdes:

- `DBI migrations integration`: privilegios, CLI y migración PostGIS real;
- `CI modular`: seis trabajos y backend completo hasta healthcheck.

Los números de ejecución se registran en la descripción y auditoría del PR para evitar que este documento quede ligado permanentemente a una ejecución antigua.

## Exclusiones

- producción;
- staging conectado;
- hosts remotos;
- Render o proveedores cloud;
- aprovisionamiento por la herramienta;
- `downgrade`, `stamp` o reparación automática;
- borrado de datos;
- cambios en `DATABASE_URL` o dominio heredado;
- frontend, WhatsApp, Green API y Google Sheets.
