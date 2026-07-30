# DBI-MIG-001 — Aplicación controlada de migraciones DBI

## Estado

Diseño inicial y barreras puras implementadas. Todavía no existe comando que abra conexiones o ejecute migraciones online.

## Interfaz prevista

La herramienta tendrá tres operaciones separadas:

- `plan`: genera `upgrade head --sql`, calcula SHA-256 y no modifica la base.
- `verify`: abre una conexión de solo verificación, comprueba destino, rol, PostGIS, esquema, `search_path`, revisión y cabeza; no ejecuta Alembic.
- `apply`: exige preflight satisfactorio, confirmación exacta, advisory lock y aplica únicamente `upgrade head`.

`apply` no será el comportamiento predeterminado.

## Barreras implementadas

- `DBI_ENVIRONMENT=production` se rechaza siempre.
- GitHub Actions solo puede operar con `DBI_ENVIRONMENT=test`.
- La base debe haber sido validada previamente por `load_dbi_database_config`.
- El usuario de la URL debe coincidir exactamente con `<database_name>_migrator`.
- `apply` exigirá la frase exacta `APPLY <database_name>`.
- La huella del plan usa SHA-256 sobre saltos de línea normalizados.
- El bloqueo de concurrencia usa una clave advisory lock estable derivada de `dalgoro-dbi-migrations-v1`.
- Ninguna barrera renderiza contraseñas o URL completas.

## Decisiones conservadoras

### Ambientes

- CI: solo `test` y únicamente sobre PostgreSQL/PostGIS efímero.
- Local: `development`, sujeto a confirmación explícita.
- Staging: no se habilitará hasta incorporar una autorización adicional inequívoca y evidencia previa.
- Producción: bloqueada sin excepción dentro de esta herramienta.

### Confirmación

No se aceptan banderas genéricas como `--yes`. La confirmación debe incluir el nombre exacto de la base para reducir el riesgo de apuntar al destino equivocado.

### Concurrencia

Se usará `pg_try_advisory_lock` con una clave estable de 64 bits. Si el bloqueo está ocupado, la operación termina sin ejecutar migraciones. El desbloqueo debe ocurrir en `finally` usando la misma conexión.

### Historial divergente

Se rechazará:

- más de una cabeza Alembic;
- revisión actual desconocida;
- revisión que no pertenezca al linaje de la cabeza;
- tabla de versión con más de una fila;
- base parcialmente preparada que incumpla PostGIS, esquema o rol.

No se realizará `stamp`, reparación o downgrade automático.

### Transacciones y recuperación

La herramienta delegará la transacción de cada revisión a Alembic/PostgreSQL. Ante cualquier excepción devolverá código no cero y ejecutará verificación posterior; nunca declarará éxito únicamente porque el comando terminó sin excepción.

## Evidencia mínima

Cada `plan` debe mostrar sin secretos:

- ambiente;
- nombre de base;
- rol esperado;
- cabeza Alembic;
- revisión actual cuando exista;
- SHA-256 del SQL offline;
- clave lógica del bloqueo, sin credenciales.

## Exclusiones actuales

- Sin ejecución remota.
- Sin producción.
- Sin creación de bases, roles, esquema o extensión.
- Sin downgrade, stamp o limpieza.
- Sin secretos reales.
- Sin cambios en `DATABASE_URL` o base heredada.

## Próximas fases obligatorias

1. Integrar la prueba offline como paso CI explícito.
2. Implementar generación de plan Alembic y evidencia redactada.
3. Implementar preflight de conexión con consultas de solo lectura.
4. Implementar advisory lock y `apply` confirmado.
5. Añadir PostgreSQL/PostGIS efímero en CI y verificación de `dbi_0006_plot_boundaries`.
6. Auditar diff, logs y recuperación antes del cierre.
