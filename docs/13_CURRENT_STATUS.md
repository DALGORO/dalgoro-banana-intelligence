# 13 — Estado actual

## Versión
0.1.1-sec-audit

## Terminado
- Estructura inicial del monorepositorio.
- Importación limpia de los tres sistemas.
- Exclusión inicial de secretos y archivos generados.
- Documentos maestros iniciales.
- CI básica.
- `DBI-SEC-001`: auditoría de secretos, dependencias y estructura importada.

## Último ticket completado
`DBI-SEC-001` — Auditoría de secretos, dependencias y estructura importada.

### Resultado
- Corregida la dependencia concatenada del motor de densidad.
- Retirados los identificadores internos como valores predeterminados del bot.
- Reducidos los logs del webhook a metadatos técnicos sin payload, teléfono ni
  mensaje.
- Ampliado `.gitignore` de forma conservadora.
- Registrada la política de aislamiento PostgreSQL/PostGIS.
- Inventariadas las copias, respaldos, volcados de revisión y binarios.
- Confirmada la existencia en Render de `GOOGLE_SHEET_ID` y
  `NUMERO_PERSONAL_DALGORO`, sin registrar ni modificar sus valores.

### Estado de validación
- Compilación de los archivos Python modificados: aprobada.
- Sintaxis de los tres archivos de dependencias: aprobada.
- Instalación aislada y `pip check` del backend: aprobados.
- Instalación aislada y `pip check` del bot: aprobados.
- Resolución de distribuciones del motor geoespacial: aprobada en `dry-run`.
- GitHub Actions: compilación Python, `npm ci` y build del frontend aprobados en
  la ejecución `30403611971`.
- La instalación completa del motor queda pendiente del entorno indicado en
  `docs/14_SECURITY_AUDIT_DBI-SEC-001.md`.
- No se declara instalación reproducible completa de Python hasta ejecutar el
  CI ampliado previsto en `DBI-CI-002`.

## Próximo ticket
`DBI-CI-002` — Integración continua real e independiente por módulo.

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
