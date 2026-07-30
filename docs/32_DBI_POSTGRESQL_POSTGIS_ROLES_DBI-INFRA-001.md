# DBI-INFRA-001 — PostgreSQL/PostGIS y roles por ambiente

## Estado

Implementación declarativa completada y auditada. No se aprovisionó infraestructura real, no se usaron credenciales reales y no se ejecutaron migraciones remotas.

## Alcance implementado

- Matriz declarativa para local, CI, staging y producción.
- Bases autorizadas: `dbi_development`, `dbi_test`, `dbi_staging` y `dbi_production`.
- Roles separados: owner, migrator, api, worker y observer.
- Plantilla SQL idempotente sin secretos ni operaciones destructivas.
- Creación condicional de base, PostGIS y esquema `dbi`.
- Revocación de privilegios públicos de creación.
- Privilegios mínimos sobre tablas, secuencias y objetos futuros.
- `search_path = dbi, public` para migrator, api, worker y observer.
- `USAGE` explícito y sin `CREATE` sobre `public` para resolver PostGIS.
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
- `public` no conserva privilegio `CREATE` para roles no confiables.
- Los roles DBI reciben únicamente `USAGE` sobre `public` para tipos y funciones PostGIS.
- `dbi` permanece primero en el `search_path`, por lo que los objetos no cualificados se crean dentro del esquema DBI.
- `pg_catalog` se omite del valor explícito para conservar su búsqueda implícita prioritaria.
- No existen contraseñas, hosts reales, tokens ni URL de conexión versionadas.
- No existen `DROP DATABASE`, `DROP ROLE`, `DROP SCHEMA`, `TRUNCATE`, `REASSIGN OWNED` ni `DROP OWNED` automáticos.

## Incidencias detectadas y corregidas

1. **CI #250:** la prueba documental dependía de capitalización editorial. Se sustituyó por validación de identificadores canónicos y nombres exactos de base.
2. **Auditoría inicial de Alembic:** se añadió un `search_path` explícito para impedir que las migraciones crearan objetos en `public`.
3. **Auditoría de mínimo privilegio:** se eliminó la membresía owner → migrator, porque permitía al migrador asumir privilegios de propietario de la base.
4. La barrera CI impide que esa herencia de privilegios reaparezca.
5. **Auditoría espacial DBI-GEO-001:** se detectó que `search_path = dbi, pg_catalog` excluía el esquema donde la instalación predeterminada mantiene PostGIS. Se corrigió a `dbi, public`, se concedió únicamente `USAGE` sobre `public` y se mantuvo revocado `CREATE`.
6. La barrera CI ahora exige cuatro líneas de `search_path = dbi, public`, acceso `USAGE` a `public` y ausencia de cualquier concesión `CREATE` en ese esquema.

## Evidencia CI

- CI modular #252: 6/6 trabajos aprobados después de corregir la validación documental.
- CI modular #258: 6/6 trabajos aprobados después de eliminar la herencia owner → migrator.
- CI modular #264: 6/6 trabajos aprobados para la primera implementación espacial; su auditoría posterior detectó la incompatibilidad de `search_path` antes de cualquier despliegue real.
- La corrección de visibilidad PostGIS requiere una nueva ejecución completa antes del cierre de DBI-GEO-001.
- Gitleaks aprobó sin secretos detectados.
- Frontend, WhatsApp, densidad geoespacial e higiene del repositorio aprobaron.

## Exclusiones preservadas

- No se creó infraestructura real.
- No se usaron credenciales reales.
- No se ejecutaron migraciones remotas.
- No se modificó `DATABASE_URL` ni la base heredada.
- No se ejecutaron despliegues en Render ni en proveedores cloud.

## Criterios de cierre

- [x] Matriz para local, CI, staging y producción.
- [x] Roles separados y privilegios mínimos.
- [x] PostgreSQL/PostGIS declarativos e idempotentes.
- [x] Base y esquema DBI aislados.
- [x] PostGIS visible sin devolver `CREATE` sobre `public`.
- [x] Sin secretos reales.
- [x] Sin operaciones destructivas automáticas.
- [x] Procedimientos de verificación, reversión y rotación.
- [x] Sin infraestructura ni migraciones remotas.
- [x] Diff y controles estáticos auditados.

## Puerta operativa

Cualquier despliegue real debe verificar con cada rol `SHOW search_path`, `postgis_full_version()` y una función `ST_*` antes de ejecutar migraciones. Esta verificación no se realizó en una base remota dentro de estos tickets.
