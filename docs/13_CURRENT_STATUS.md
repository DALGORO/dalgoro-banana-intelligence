# 13 — Estado actual

## Versión

0.5.0-agricultural-domain

## Terminado

- Estructura inicial del monorepositorio.
- Importación limpia de los tres sistemas.
- Exclusión inicial de secretos y archivos generados.
- Documentos maestros iniciales.
- CI básica.
- `DBI-SEC-001`: auditoría de secretos, dependencias y estructura importada.
- `DBI-CI-002`: integración continua modular y verificable.
- `DBI-REPO-001`: limpieza controlada de copias, respaldos y artefactos.
- `DBI-ARC-001`: arquitectura objetivo, límites y contratos de integración.
- `DBI-DATA-001`: base DBI aislada e historial Alembic independiente.
- `DBI-MAP-001`: interfaz cronológica de mapas y contrato v1.

## Último ticket completado

`DBI-MAP-001` — Interfaz cronológica de mapas y contrato v1.

- Issue: #12
- Pull request: #13
- Estado: completado
- SHA técnico validado: `167892a95ed708e5481df94dc187749884210cd1`.
- GitHub Actions `30454883303`: seis de seis trabajos aprobados.
- Diff: 15 archivos; seis añadidos y nueve modificados.
- Conexiones externas, migraciones y datos simulados: cero.

## Ticket actual

`DBI-DATA-002` — Persistencia mínima de finca, lote y campaña.

- Issue: #14
- Rama: `feat/DBI-DATA-002-dominio-agricola-v1`
- Estado: en implementación
- Base: `de5a5412a254c7d382c98ac4284e948e217fee2a`
- Conexiones externas y migraciones online: cero.

## Próximo paso

Validar el esquema DBI, la revisión `dbi_0002_agricultural_domain` y el Draft
PR del Issue #14. Crear infraestructura, habilitar PostGIS, insertar campañas
reales o ejecutar migraciones online continúa requiriendo aprobación explícita.

## Riesgos heredados abiertos

- El backend importado continúa usando `DATABASE_URL`.
- DBI todavía no dispone de motor, sesión o repositorio de acceso.
- Alembic heredado conserva tres cabezas: `20260411_01`, `2cec060d9aa4` y
  `7ce73aae44ce`.
- El middleware de suscripción permite continuar ante varias excepciones.
- El bot depende actualmente de Green API y Google Sheets.
- El motor geoespacial depende de PyTorch, GDAL y almacenamiento local.
- El frontend mantiene 115 avisos ESLint como línea base.
- Las vulnerabilidades de dependencias inventariadas siguen pendientes de
  tickets específicos.

## No realizado todavía

- No se ha creado una base PostgreSQL/PostGIS DBI.
- No se han creado roles `dbi_migrator`, `dbi_app` o `dbi_readonly`.
- No se ha habilitado PostGIS.
- Los modelos y la migración del dominio agrícola existen solo como código del
  ticket actual; no se han aplicado a una base.
- No se ha conectado el backend heredado al entorno DBI.
- El mapa cronológico v1 todavía no consulta persistencia y no dispone de
  geometrías, tiles o fechas reales.
- No se han cambiado Green API, Google Sheets o Render.
- No se ha cambiado la lógica conversacional del bot.
- No se han actualizado modelos de IA.
