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
- `DBI-DATA-002`: persistencia mínima de finca, lote y campaña.

## Último ticket completado

`DBI-DATA-002` — Persistencia mínima de finca, lote y campaña.

- Issue: #14
- Pull request: #15
- Estado: completado
- SHA final validado: `7933181459a1b04c666d80d8b776454c69a50108`.
- GitHub Actions `30458515477`: seis de seis trabajos aprobados.
- Diff: 13 archivos; seis añadidos y siete modificados.
- Conexiones externas y migraciones online: cero.

## Ticket actual

Ninguno.

## Próximo paso

Seleccionar el siguiente ticket desde `main`. Crear infraestructura, habilitar
PostGIS, insertar campañas reales o ejecutar migraciones online continúa
requiriendo aprobación explícita.

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
- Los modelos y la migración del dominio agrícola están integrados en código;
  no se han aplicado a una base.
- No se ha conectado el backend heredado al entorno DBI.
- El mapa cronológico v1 todavía no consulta persistencia y no dispone de
  geometrías, tiles o fechas reales.
- No se han cambiado Green API, Google Sheets o Render.
- No se ha cambiado la lógica conversacional del bot.
- No se han actualizado modelos de IA.
