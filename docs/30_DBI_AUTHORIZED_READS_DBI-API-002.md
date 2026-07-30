# DBI-API-002 — Consultas DBI autorizadas

## Objetivo

Exponer consultas HTTP de solo lectura para recursos DBI sin mezclar la sesión heredada, sin enumerar recursos ajenos y sin filtrar metadatos internos sensibles.

## Implementación

- Router `/dbi` montado en la API v1.
- Consultas de fincas, lotes, campañas, trabajos, activos y artefactos.
- Dependencias exclusivas `get_dbi_session` y `get_dbi_access_context`.
- Autorización por tenant, organización, finca y lote.
- Respuesta uniforme `404` para recurso inexistente o fuera de ámbito.
- Contratos Pydantic estrictos con `extra="forbid"`.
- Exclusión de `object_key`, huellas SHA-256, referencias privadas y datos internos del solicitante.
- Listados con límite fijo de 100 registros y orden determinista.

## Auditoría de seguridad

- No se usa `SessionLocal`, `get_db`, `User` ni `Company` en el router DBI.
- No existen escrituras, commits, cargas, descargas, URLs firmadas ni ejecución de trabajos.
- Todas las consultas de repositorio reciben una frontera de organización, tenant, finca o trabajo.
- Los trabajos y activos asociados a lotes se filtran nuevamente contra `plot_scopes`.
- Los recursos ajenos y los inexistentes generan la misma respuesta pública.

## Validación

La ejecución CI modular #216 (`30564030668`) terminó con 6/6 trabajos aprobados. El backend ejecutó todas sus barreras, incluida `Validar consultas DBI autorizadas offline`, además de compilación, aislamiento, sesiones, repositorios, autorización, identidad, ciclo FastAPI, dominio, contratos geoespaciales, persistencia y healthcheck.

## Límites preservados

Este incremento no incorpora PostGIS operativo, geometrías, tiles, almacenamiento de objetos, procesamiento geoespacial, escrituras DBI, migraciones online, despliegues, cambios de frontend, WhatsApp, Green API o Google Sheets.

## Resultado

DBI dispone de una superficie HTTP de lectura acotada, no enumerable, con contratos estables y validación offline. El siguiente incremento previsto es `DBI-API-003 — Escrituras DBI autorizadas`.
