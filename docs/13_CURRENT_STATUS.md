# 13 — Estado actual

## Versión
0.1.1-sec-audit (rama de trabajo)

## Terminado
- Estructura inicial del monorepositorio.
- Importación limpia de los tres sistemas.
- Exclusión inicial de secretos y archivos generados.
- Documentos maestros iniciales.
- CI básica.

## Ticket en curso
`DBI-SEC-001` — Auditoría de secretos, dependencias y estructura importada.

### Cambios preparados
- Corrección de la dependencia concatenada del motor de densidad.
- Retiro de identificadores internos como valores predeterminados del bot.
- Reducción de logs del webhook a metadatos técnicos sin payload, teléfono ni
  mensaje.
- Ampliación conservadora de `.gitignore`.
- Registro de la política de aislamiento PostgreSQL/PostGIS.
- Inventario de copias, respaldos, volcados de revisión y binarios.

### Estado de validación
- Compilación de los archivos Python modificados: aprobada.
- Sintaxis de los tres archivos de dependencias: aprobada.
- Instalación aislada y `pip check` del backend: aprobados.
- Instalación aislada y `pip check` del bot: aprobados.
- Resolución de distribuciones del motor geoespacial: aprobada en `dry-run`.
- La instalación completa del motor y las comprobaciones del frontend quedan
  pendientes de los entornos indicados en
  `docs/14_SECURITY_AUDIT_DBI-SEC-001.md`.
- El ticket permanecerá en Draft PR hasta revisión del propietario.
- No se declara instalación reproducible completa de Python hasta ejecutar el
  CI ampliado previsto en `DBI-CI-002`.

## Próximo ticket después de la aprobación
`DBI-CI-002` — Integración continua real e independiente por módulo.

## No realizado todavía
- No se ha fusionado código entre módulos.
- No existe todavía una base PostgreSQL/PostGIS unificada.
- No se ha creado ni modificado ninguna base DBI.
- No se han ejecutado migraciones.
- No existe todavía el dashboard agrícola.
- No existe todavía el mapa cronológico.
- No se han cambiado Green API, Google Sheets ni Render.
- No se ha cambiado la lógica conversacional del bot.
- No se han actualizado modelos de IA.
