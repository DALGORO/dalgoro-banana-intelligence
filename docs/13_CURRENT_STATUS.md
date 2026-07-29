# 13 — Estado actual

## Versión

0.3.0-data-isolation

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

## Último ticket completado

`DBI-DATA-001` — Base DBI aislada e historial Alembic independiente.

- Issue: #10
- Pull request: #11
- Estado: completado
- SHA técnico validado: `58e0e39a8dc9e62af3e5cd546cd92fb94e5dcb4c`
- GitHub Actions `30449255042`: seis de seis trabajos aprobados.
- Diff: 13 archivos; ocho añadidos y cinco modificados.
- Conexiones externas y migraciones online: cero.

## Ticket actual

Ninguno.

## Próximo paso

Seleccionar el siguiente ticket desde `main`. La creación de infraestructura,
la habilitación de PostGIS y cualquier migración online permanecen fuera del
alcance de `DBI-DATA-001`.

## Riesgos heredados abiertos

- El backend importado continúa usando `DATABASE_URL`.
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
- No se han creado modelos o tablas del dominio agrícola.
- No se ha conectado el backend heredado al entorno DBI.
- No existe todavía el dashboard agrícola o el mapa cronológico.
- No se han cambiado Green API, Google Sheets o Render.
- No se ha cambiado la lógica conversacional del bot.
- No se han actualizado modelos de IA.
