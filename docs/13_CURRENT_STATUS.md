# 13 — Estado actual

## Versión

0.2.0-architecture-draft

## Terminado

- Estructura inicial del monorepositorio.
- Importación limpia de los tres sistemas.
- Exclusión inicial de secretos y archivos generados.
- Documentos maestros iniciales.
- CI básica.
- `DBI-SEC-001`: auditoría de secretos, dependencias y estructura importada.
- `DBI-CI-002`: integración continua modular y verificable.
- `DBI-REPO-001`: limpieza controlada de copias, respaldos y artefactos.

## Último ticket completado

`DBI-REPO-001` — Limpieza controlada de copias, respaldos y artefactos.

## Ticket actual

`DBI-ARC-001` — Arquitectura objetivo, límites y contratos de integración.

- Issue: #8
- Rama: `architecture/DBI-ARC-001-limites-contratos`
- Pull request: #9
- Estado: en revisión
- Base: `main` en `14775cf6b4cd8afa47e22e1728ad44cc55187509`

### Alcance

- Confirmar el papel del backend FastAPI como plano de control.
- Separar API, worker geoespacial, frontend y adaptador WhatsApp.
- Definir propiedad de datos y artefactos.
- Definir contratos conceptuales versionados e idempotentes.
- Definir trazabilidad agronómica y gobierno Champion/Challenger.
- Establecer la secuencia segura hacia `DBI-DATA-001`.

### Archivos involucrados

- `docs/01_SYSTEM_ARCHITECTURE.md`
- `docs/06_TECHNICAL_DECISIONS.md`
- `docs/13_CURRENT_STATUS.md`
- `docs/17_ARCHITECTURE_DBI-ARC-001.md`

### Exclusiones

- No se modifica código funcional.
- No se añaden endpoints, tablas, migraciones ni dependencias.
- No se crea ni consulta PostgreSQL/PostGIS.
- No se modifican Render, Green API o Google Sheets.
- No se procesa una ortofoto ni se descarga un modelo.
- No se actualiza ni promueve un modelo de IA.

### Validación ejecutada

- Diff remoto: cuatro documentos; tres modificados y uno añadido.
- Rama: cero commits por detrás de `main`.
- Contenido remoto coincidente con los archivos validados localmente.
- Markdownlint: cero errores con longitud de tablas excluida.
- Cinco ejemplos JSON analizados correctamente.
- Trece decisiones técnicas consecutivas.
- GitHub Actions `30420556081`: primera ejecución con seis de seis trabajos aprobados.
- GitHub Actions `30420731911`: seis de seis trabajos aprobados después de
  las precisiones documentales.
- No se consultaron servicios ni bases operativas.

## Próximo paso

Revisar el Draft PR #9 y mantenerlo sin fusionar hasta la autorización del
propietario.

Después de aprobar `DBI-ARC-001`, el siguiente ticket previsto es
`DBI-DATA-001`: base DBI aislada e historial Alembic independiente. Ese ticket
deberá diseñar y probar la configuración sin tocar bases productivas.

## Riesgos heredados abiertos

- El backend importado continúa usando `DATABASE_URL`.
- Alembic conserva tres cabezas heredadas: `20260411_01`, `2cec060d9aa4` y
  `7ce73aae44ce`.
- El middleware de suscripción permite continuar ante varias excepciones.
- El bot depende actualmente de Green API y Google Sheets.
- El motor geoespacial depende de PyTorch, GDAL y almacenamiento local.
- El frontend mantiene 115 avisos ESLint como línea base.
- Las vulnerabilidades de dependencias inventariadas siguen pendientes de
  tickets específicos.

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
