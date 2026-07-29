# 13 — Estado actual

## Versión

0.4.0-map-timeline

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

`DBI-MAP-001` — Interfaz cronológica de mapas y contrato v1.

- Issue: #12
- Rama: `feat/DBI-MAP-001-mapa-cronologico-v1`
- Pull request: #13
- Estado: en revisión
- Base: `main` en `4abd2ae1d67114098a73f269924bcb9ad91b3779`
- SHA técnico validado: `614a1aea7a00cc15170adc22f09dbb717f3b5d5f`
- GitHub Actions `30454509983`: seis de seis trabajos aprobados.
- Diff: 15 archivos; seis añadidos y nueve modificados.
- Conexiones externas, migraciones y datos simulados: cero.

## Próximo paso

Validar `DBI-MAP-001` en GitHub Actions y revisar su Draft PR. La creación de
infraestructura, la habilitación de PostGIS, las campañas reales y cualquier
migración online permanecen fuera de este ticket.

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
- El mapa cronológico v1 todavía no dispone de fincas, campañas, geometrías,
  tiles o fechas reales.
- No se han cambiado Green API, Google Sheets o Render.
- No se ha cambiado la lógica conversacional del bot.
- No se han actualizado modelos de IA.
