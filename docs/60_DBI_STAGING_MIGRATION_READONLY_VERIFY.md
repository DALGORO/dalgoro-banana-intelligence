# DBI-INFRA-002 · Auditoría READ ONLY de migraciones staging (microhito E2)

## Alcance

Este microhito **no autoriza ni aplica migraciones en staging**. Introduce
una **herramienta separada** de lectura para determinar si una base DBI
staging ya provisionada está en la cabeza Alembic del repositorio.
El controlador original `app.dbi.migration_cli` y su operación `apply`
permanecen limitados a CI `test` con PostgreSQL local; no se modifica
esa política ni se proporciona un atajo `alembic upgrade head`.

## Requisitos previos, que NO se realizan desde el repositorio

1. Staging segregado de producción, base de datos `dbi_staging`,
   PostGIS y esquema `dbi` presentes. Certificado TLS válido para el
   hostname DNS conocido y conectividad de operador permitida.
2. Aprovisionar por un administrador responsable el rol
   `dbi_staging_migration_auditor`, con **CONNECT, USAGE de esquema y SELECT
   exclusivamente sobre `dbi.alembic_version_dbi`**, sin SUPERUSER,
   CREATEROLE, CREATEDB, BYPASSRLS, membresías, privilegios DML ni DDL,
   propiedad de base/esquema o permisos para modificar datos. Separado
   del rol `dbi_staging_migrator`; no reutilizar identidades de producción.
   Revisar permisos efectivos antes de permitir la conexión.
3. Certificado CA confiable para `sslmode=verify-full`. Usar gestores de
   secretos del entorno y restringir red/IAM. No cargar credenciales al
   repositorio ni a archivos de diagnóstico.
4. Identificar políticas de respaldo y de aprobación de cambios en staging.
   Esa aprobación aún **no** forma parte del software implementado.

## Entrada autorizada al operador

Desde el backend aislado, con los secretos definidos fuera de GitHub:

- `DBI_ENVIRONMENT=staging`
- `DBI_DATABASE_URL`: conexión PostgreSQL a base `dbi_staging`, usuario
  `dbi_staging_migration_auditor`, DNS aprobado, puerto 5432 y
  `sslmode=verify-full`.
- `DBI_STAGING_VERIFY_HOST`: hostname DNS exacto esperado; se contrasta
  con el destino de la URL. No se admiten localhost, IP literales,
  `.local` ni `.invalid`.
- `DBI_STAGING_VERIFY_CONFIRM=VERIFY dbi_staging READ ONLY`: confirmación
  textual de la consulta, **no** una autorización de escritura.
- No ejecutar conectado desde GitHub Actions o CI.

```bash
cd apps/platform-web/backend
python -m app.dbi.staging_migration_verify --verify-readonly
```

El programa valida **antes de conectar** entorno, base, identidad de
auditor, hostname y TLS. Abre una conexión nueva con
`default_transaction_read_only=on`, `SET TRANSACTION READ ONLY`,
`statement_timeout=8000`, `lock_timeout=2000` y
`connect_timeout=5`; reutiliza el preflight de consultas `SELECT`
de DBI y concluye con rollback y cierre de conexión.

La salida JSON revela solo base `dbi_staging`, nombre del rol
estandarizado, revisión de código, revisión de base y si coinciden.
**Nunca** imprime host, DNS, URL, contraseña, token ni errores de proveedor.
Aunque ambas revisiones coincidan emite siempre
`deployment_readiness=NOT_VERIFIED` y `migration_apply=BLOCKED`.
Cualquier error devuelve un código distinto de cero y salida redactada.
Esta operación no accede a S3 ni a archivos GIS.

## Pruebas y aislamiento

`.github/scripts/ci_dbi_staging_migration_readonly.py` comprueba mediante
dobles de conexión **sin red**: prevalidación fail-closed, rol auditor
exacto, protección TLS, aislamiento por hostname, bloqueo de CI y
producción, comprobación de migraciones DBI conocidas, transacción
de solo lectura previa a cualquier SELECT, timeout corto, limpieza,
diferencia entre revisión presente y cabeza del código, errores sin
filtración y continuidad del bloqueo del `migration_cli` anterior.
Se ejecuta en `CI modular`.

## Próximo bloqueo

Para **aplicar** migraciones staging hace falta otro diseño y otra
autorización expresa: respaldo restaurable, ventana de cambio,
migrador con mínimos privilegios, destino ligado a identidad comprobada,
aprobación independiente, lock, dry-run revisado, evidencia y postflight;
sin producción, sin `stamp`, downgrade ni bypass manual del orquestador.
No provisionamos base, roles, Render, S3, certificados, accesos ni ejecutamos
ninguna operación contra infraestructuras reales en este microhito E2.
