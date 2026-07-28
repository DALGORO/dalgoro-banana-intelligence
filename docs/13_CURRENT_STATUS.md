# 13 — Estado actual

## Versión
0.1.2-ci-modular-rc2

## Terminado
- Estructura inicial del monorepositorio.
- Importación limpia de los tres sistemas.
- Exclusión inicial de secretos y archivos generados.
- Documentos maestros iniciales.
- CI básica.
- `DBI-SEC-001`: auditoría de secretos, dependencias y estructura importada.

## Ticket en revisión
`DBI-CI-002` — Integración continua real e independiente por módulo.

### Alcance activo
- Cinco trabajos independientes: frontend, backend, bot, densidad y secretos.
- Instalación y verificación de dependencias por módulo.
- Smoke tests sin servicios externos ni bases productivas.
- Línea base de lint que impide aumentar los 115 avisos heredados.
- Auditorías visibles de secretos y dependencias.

### Validación ejecutada
- Frontend `npm ci`: aprobado con caché temporal autorizada.
- Frontend lint: 0 errores y 115 avisos con la línea base propuesta.
- Frontend build: aprobado con Node 24.
- Backend: instalación aislada, `pip check`, `compileall` y healthcheck
  aprobados.
- Alembic: el grafo se interpreta, pero existen tres cabezas heredadas que
  deberán resolverse antes de crear migraciones DBI.
- Bot: instalación aislada, `pip check`, `compileall` y endpoint Flask con
  Sheets simulado aprobados.
- Auditoría npm: ejecutada; mantiene hallazgos heredados sin declarar
  resolución.
- Sintaxis de los tres smoke tests y parseo del workflow: aprobados.
- GitHub Actions `30407127911`: los cinco trabajos aprobaron.
- Motor geoespacial: instalación completa, `pip check`, `compileall`,
  importaciones y CLI aprobados en un entorno limpio.
- Gitleaks: historial completo analizado sin secretos detectados.
- Auditorías informativas: frontend 5 vulnerabilidades de producción; backend
  81 hallazgos en 19 paquetes; bot 2 en 1 paquete; densidad 3 en 2 paquetes.
  Ningún hallazgo se declara corregido en este ticket.

## Último ticket completado
`DBI-SEC-001` — Auditoría de secretos, dependencias y estructura importada.

## Próximo ticket
`DBI-REPO-001` — Limpieza controlada de copias, respaldos y artefactos,
condicionado a la revisión y fusión del PR de `DBI-CI-002`.

## No realizado todavía
- No se ha fusionado código entre módulos.
- No existe todavía una base PostgreSQL/PostGIS unificada.
- No se ha creado ni modificado ninguna base DBI.
- No se han ejecutado migraciones.
- No existe todavía el dashboard agrícola.
- No existe todavía el mapa cronológico.
- No se han cambiado Green API, Google Sheets ni la configuración de Render.
- No se ha cambiado la lógica conversacional del bot.
- No se han actualizado modelos de IA.
