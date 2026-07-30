# DBI-INFRA-001 — PostgreSQL/PostGIS y roles por ambiente

## Estado

Implementación declarativa completada y auditada. No se aprovisionó infraestructura real, no se usaron credenciales reales y no se ejecutaron migraciones remotas.

## Alcance implementado

- Matriz declarativa para local, CI, staging y producción.
- Bases autorizadas: `dbi_development`, `dbi_test`, `dbi_staging` y `dbi_production`.
- Roles separados: owner, migrator, api, worker y observer.
- Plantilla SQL idempotente sin secretos ni operaciones destructivas.
- Creación condicional de base, PostGIS y esquema `dbi`.
- Revocación de privilegios públicos.
- Privilegios mínimos sobre tablas, secuencias y objetos futuros.
- `search_path` explícito para migrator, api, worker y observer.
- Procedimientos de aprovisionamiento, verificación, reversión y rotación.
- Validación CI completamente offline integrada en la barrera de aislamiento DBI.

## Controles de seguridad

- `DATABASE_URL` permanece prohibida para componentes DBI.
- La matriz obliga a usar `DBI_ENVIRONMENT` y `DBI_DATABASE_URL`.
- Los roles operativos son `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE` y `NOREPLICATION`.
- El rol owner es `NOLOGIN`.
- El migrator no hereda ni puede asumir el rol owner.
- API, worker y observer no reciben privilegios DDL.
- Worker no recibe `DELETE`.
- Observer permanece en solo lectura.
- No existen contraseñas, hosts reales, tokens ni URL de conexión versionadas.
- No existen `DROP DATABASE`, `DROP ROLE`, `DROP SCHEMA`, `TRUNCATE`, `REASSIGN OWNED` ni `DROP OWNED` automáticos.

## Incidencias detectadas y corregidas

1. **CI #250:** la prueba documental dependía de capitalización editorial. Se sustituyó por validación de identificadores canónicos y nombres exactos de base.
2. **Auditoría de Alembic:** se añadió `search_path = dbi, pg_catalog` al migrator para evitar creación accidental de objetos en `public`.
3. **Auditoría de mínimo privilegio:** se eliminó la membresía owner → migrator, porque permitía al migrador asumir privilegios de propietario de la base.
4. La barrera CI ahora impide que esa herencia de privilegios reaparezca.

## Evidencia CI

- CI modular #252: 6/6 trabajos aprobados después de corregir la validación documental.
- CI modular #258: 6/6 trabajos aprobados después de eliminar la herencia owner → migrator.
- En #258 se ejecutaron y aprobaron todas las pruebas posteriores del backend, incluida la barrera de aislamiento DBI, consultas, escrituras, persistencia y healthcheck.
- Gitleaks aprobó sin secretos detectados.
- Frontend, WhatsApp, densidad geoespacial e higiene del repositorio aprobaron.

## Exclusiones preservadas

- No se creó infraestructura real.
- No se usaron credenciales reales.
- No se ejecutaron migraciones remotas.
- No se modificó `DATABASE_URL` ni la base heredada.
- No se implementaron geometrías operativas, índices espaciales de negocio o tiles.
- No se ejecutaron despliegues en Render ni en proveedores cloud.

## Criterios de cierre

- [x] Matriz para local, CI, staging y producción.
- [x] Roles separados y privilegios mínimos.
- [x] PostgreSQL/PostGIS declarativos e idempotentes.
- [x] Base y esquema DBI aislados.
- [x] Sin secretos reales.
- [x] Sin operaciones destructivas automáticas.
- [x] Procedimientos de verificación, reversión y rotación.
- [x] Sin infraestructura ni migraciones remotas.
- [x] CI modular completa en verde.
- [x] Diff y logs auditados.

## Puerta final

El PR permanece en borrador hasta que la ejecución CI posterior a este commit documental termine completamente en verde y se verifiquen las conversaciones de revisión.