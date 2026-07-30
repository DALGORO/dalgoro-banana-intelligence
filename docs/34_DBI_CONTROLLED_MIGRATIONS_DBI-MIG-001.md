# DBI-MIG-001 — Aplicación controlada de migraciones DBI

## Estado

Implementación completa en el PR #48, pendiente únicamente de auditoría final y autorización de integración.

La solución incluye:

- interfaz operativa explícita `plan`, `verify` y `apply`;
- plan Alembic estrictamente offline con huella SHA-256;
- preflight conectado mediante consultas de solo lectura;
- bloqueo PostgreSQL de sesión contra migraciones concurrentes;
- aplicación exclusiva de `upgrade head` sobre la misma conexión;
- postflight obligatorio;
- pruebas offline;
- prueba real sobre PostgreSQL 16/PostGIS 3.5 efímero en GitHub Actions.

No existe soporte para producción, staging remoto, `downgrade`, `stamp`, reparación automática ni borrado de bases.

## Entrada operativa

La interfaz canónica es:

```bash
python -m app.dbi.migration_cli [plan|verify|apply]
```

Cuando se omite la operación, se ejecuta `plan`. Por tanto, invocar el módulo sin argumentos no modifica ninguna base.

La herramienta lee únicamente:

```text
DBI_ENVIRONMENT
DBI_DATABASE_URL
```

`DATABASE_URL` no se usa y permanece prohibida para DBI.

## Matriz autorizada

| Operación | Fuera de CI | GitHub Actions | Conexión |
|---|---|---|---|
| `plan` | Ambientes no productivos válidos | Solo `test` | No abre conexiones |
| `verify` | Solo `development` local | Solo `test` efímero | Solo host local o loopback |
| `apply` | Bloqueado | Solo `test` efímero | Solo host local o loopback |

Reglas adicionales:

- `production` se rechaza siempre.
- `staging` no puede verificarse ni aplicarse mediante esta interfaz.
- CI no puede usar una base distinta de `dbi_test`.
- El usuario debe coincidir exactamente con `<database_name>_migrator`.
- Los hosts conectados permitidos son `localhost`, `127.0.0.1` y `::1`.
- Ningún error imprime la URL, contraseña o detalle sensible de conexión.

## Plan

Ejemplo local sin contraseña incrustada:

```bash
export DBI_ENVIRONMENT=development
export DBI_DATABASE_URL='postgresql+psycopg://dbi_development_migrator@127.0.0.1:5432/dbi_development'
python -m app.dbi.migration_cli
```

También puede escribirse el SQL offline en un archivo nuevo:

```bash
python -m app.dbi.migration_cli plan --sql-output dbi-plan.sql
```

El archivo se crea en modo exclusivo. La herramienta se niega a sobrescribir un archivo existente.

`plan` ejecuta conceptualmente:

```text
upgrade head --sql
```

No crea motores, no abre sockets y no ejecuta SQL contra PostgreSQL. La evidencia JSON incluye:

- operación;
- ambiente;
- nombre de base;
- rol migrador esperado;
- cabeza Alembic;
- huella SHA-256 normalizada;
- ruta del SQL cuando fue solicitada.

El SQL y la evidencia se validan para impedir la aparición de contraseña, host o URL completa.

## Verify

Ejemplo para una instancia local de desarrollo ya aprovisionada:

```bash
python -m app.dbi.migration_cli verify
```

El preflight ejecuta únicamente consultas `SELECT` y comprueba:

1. base actual;
2. usuario actual;
3. `search_path` comenzando por `dbi, public`;
4. ausencia de `SUPERUSER`, `CREATEDB`, `CREATEROLE` y replicación;
5. PostGIS instalado;
6. esquema `dbi` existente;
7. existencia de `dbi.alembic_version_dbi`;
8. una sola revisión actual;
9. revisión perteneciente al linaje reconocido;
10. una sola cabeza Alembic.

Se permite una base vacía sin tabla de versión, siempre que infraestructura, PostGIS, esquema y rol ya hayan sido aprovisionados correctamente.

## Apply

`apply` está deliberadamente bloqueado fuera de GitHub Actions. En CI exige simultáneamente:

- `GITHUB_ACTIONS=true`;
- `DBI_ENVIRONMENT=test`;
- base `dbi_test`;
- rol `dbi_test_migrator`;
- host local o loopback;
- confirmación exacta:

```text
APPLY dbi_test
```

La operación controlada sigue este orden:

1. valida ambiente, base, rol y host;
2. valida la confirmación exacta;
3. genera el plan offline y su SHA-256;
4. ejecuta preflight de solo lectura;
5. adquiere `pg_try_advisory_lock` sin espera;
6. repite el preflight bajo el bloqueo;
7. omite la operación si la base ya está en `head`;
8. ejecuta una única llamada a `upgrade head`;
9. ejecuta postflight;
10. exige que la revisión final sea la cabeza autorizada;
11. libera el lock dentro de `finally`.

No se aceptan `--yes`, confirmaciones genéricas ni una operación predeterminada destructiva.

## Misma sesión PostgreSQL

El advisory lock es de sesión. Por eso, preflight, lock, Alembic y postflight usan la misma conexión SQLAlchemy.

`dbi_alembic/env.py` no crea un motor online. Exige una conexión externa en:

```python
Config.attributes["connection"]
```

`migration_runner.py` entrega esa misma conexión a Alembic y ejecuta exclusivamente:

```text
upgrade head
```

Las barreras estáticas impiden reintroducir `engine_from_config`, una segunda conexión oculta, `downgrade` o `stamp`.

## Bloqueo de concurrencia

La clave de bloqueo se deriva de forma estable de:

```text
dalgoro-dbi-migrations-v1
```

Se usa `pg_try_advisory_lock`, que falla inmediatamente cuando otra sesión posee el bloqueo. La prueba real abre dos conexiones y confirma que la segunda no puede adquirirlo.

La liberación se intenta siempre. Cuando la operación protegida falla, se conserva la excepción original y no se declara éxito.

## Integración PostgreSQL/PostGIS efímera

El workflow dedicado es:

```text
.github/workflows/dbi-migration-integration.yml
```

Características:

- runner aislado de GitHub Actions;
- PostgreSQL 16/PostGIS 3.5 en contenedor efímero;
- imagen fijada por digest;
- autenticación `trust` limitada al contenedor desechable del runner;
- base `dbi_test`;
- rol migrador sin privilegios administrativos;
- URL local sin contraseña;
- apagado del contenedor al finalizar.

El fixture de CI aprovisiona base, roles, PostGIS y esquema por separado. La herramienta de migración no crea ni elimina esos recursos.

La prueba real verifica:

- `plan` y preflight no cambian las tablas;
- dos sesiones no migran simultáneamente;
- aplicación desde base vacía hasta `dbi_0006_plot_boundaries`;
- segunda ejecución idempotente;
- conjunto exacto de tablas DBI y tabla de versión;
- ausencia de tablas heredadas;
- columna `boundary` como `MULTIPOLYGON` SRID 4326;
- índice GiST `ix_dbi_plots_boundary_gist`;
- restricciones `ck_dbi_plots_boundary_not_empty` y `ck_dbi_plots_boundary_valid`;
- funciones PostGIS operativas.

## Evidencia no sensible

Las operaciones exitosas escriben JSON en `stdout`. Los errores usan `stderr` y códigos distintos de cero.

Ejemplo conceptual de evidencia de `apply`:

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

Nunca se registra:

- contraseña;
- URL completa;
- certificado;
- host remoto;
- cadena de conexión heredada.

## Recuperación ante fallos

Ante cualquier fallo:

1. la herramienta devuelve código distinto de cero;
2. el lock se libera mediante `finally`;
3. no se ejecuta `stamp`, `downgrade` ni reparación automática;
4. el operador debe conservar la evidencia del plan y revisar la revisión actual;
5. una revisión desconocida o múltiples filas de versión bloquean nuevos intentos;
6. el contenedor efímero de CI se destruye al terminar;
7. cualquier corrección requiere una nueva migración revisada, no manipular la tabla de versión manualmente.

Si Alembic falla dentro de una revisión transaccional, PostgreSQL revierte esa transacción. El postflight evita declarar éxito si la cabeza no quedó confirmada.

## Responsabilidades

### Infraestructura

- crear base, roles, esquema y extensión;
- asignar credenciales fuera del repositorio;
- conservar `public` sin privilegio `CREATE` para roles operativos;
- conceder solo `USAGE` sobre `public` para PostGIS;
- establecer `search_path = dbi, public`.

### Operador

- revisar ambiente, base y rol en la evidencia;
- comparar la huella SHA-256 del plan;
- no reutilizar evidencia de otro commit;
- no intentar ejecutar `apply` fuera del workflow autorizado;
- detenerse ante una revisión desconocida o un esquema divergente.

### Herramienta

- fallar cerrado;
- no aprovisionar infraestructura;
- no tocar la base heredada;
- no exponer secretos;
- no admitir producción;
- aplicar únicamente `upgrade head`.

## CI auditada

En el commit que completó la interfaz operativa:

- `DBI migrations integration #10`: interfaz offline y migración PostGIS real aprobadas;
- `CI modular #324`: seis trabajos aprobados;
- backend: todas las validaciones ejecutadas hasta el healthcheck, sin pasos omitidos.

Estas referencias sirven como evidencia del PR. Una modificación posterior exige repetir ambas ejecuciones antes del cierre.

## Exclusiones permanentes de DBI-MIG-001

- producción;
- staging conectado;
- hosts remotos desde CI;
- despliegues en Render o proveedores cloud;
- creación o eliminación de infraestructura por la herramienta;
- `downgrade` automático;
- `stamp` automático;
- reparación automática;
- limpieza o borrado de datos;
- cambios en `DATABASE_URL` o modelos heredados;
- frontend, WhatsApp, Green API y Google Sheets.
