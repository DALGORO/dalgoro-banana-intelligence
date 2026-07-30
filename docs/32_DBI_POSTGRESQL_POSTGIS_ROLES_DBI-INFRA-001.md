# DBI-INFRA-001 — PostgreSQL/PostGIS y roles por ambiente

## Estado

Implementación inicial en Draft PR. Este documento se completará con la evidencia final de CI y auditoría antes del cierre.

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

## Exclusiones preservadas

- No se creó infraestructura real.
- No se usaron credenciales reales.
- No se ejecutaron migraciones remotas.
- No se modificó `DATABASE_URL` ni la base heredada.
- No se implementaron geometrías operativas, índices espaciales de negocio o tiles.

## Evidencia pendiente

- Ejecución CI modular completa.
- Auditoría del diff y logs.
- Confirmación de conversaciones pendientes.
