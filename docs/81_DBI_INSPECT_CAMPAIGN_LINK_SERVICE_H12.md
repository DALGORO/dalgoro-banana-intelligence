# DBI-H12-API-001 · Asociación interna INSPECT–Campaign con validación transaccional

## Objetivo
Avanzar desde las tablas creadas en PR #217 (Alembic 27) a un servicio de
asociación científica, sin habilitar aún la captura por Campaign obligatoria
ni los dos actos administrativos de publicación.

`DBIInspectionCampaignLinkService.link_current_version` recibe autoridad de
`DBIAccessContext` **resuelta por el backend** y exige conjuntamente `READ`
y `WRITE` scoped de tenant/organización/finca/lote. No acepta `tenant_ref`,
roles o actor como atributos libres del cuerpo del cliente.

## Condiciones del servicio

- Campaign tiene identidad completa coincidente, `analysis_type=multispectral`,
  `captured_at` real y estado al menos `SAMPLING_READY`, `FIELD_WORK`,
  `FIELD_COMPLETED`, `APPROVED` o `PUBLISHED`.
- Bloquea la fila de identidad de INSPECT `SELECT ... FOR UPDATE` antes de
  leer la versión vigente. La corrección también bloquea esa identidad:
  se rechaza una vinculación concurrente a una versión que dejó de ser
  la vigente.
- Requiere registro INSPECT dentro del scope exacto y versión vigente
  con `evidence_kind=observed`; no deduce emparejamientos por fecha/GPS.
- Impide cambiar de Campaign automáticamente entre versiones de la misma
  observación (requiere un flujo específico de reasociación futuro).
- Reintento idéntico regresa la fila existente; una asociación nueva crea
  una única fila y ejecuta `flush` pero **no `commit/rollback`**.
  PostgreSQL también impone UNIQUE por versión y FKs compuestas.
- Cada corrección de campo crea versión distinta, **sin heredar el vínculo
  ni las firmas de una versión antigua**. El técnico debe vincular
  expresamente la nueva versión y empezar de nuevo el proceso de aprobación.
- No certifica proximidad temporal campo-vuelo, seguridad de COPA_UP,
  calidad espectral, causalidad de enfermedad ni etiquetas entrenables.

## Pruebas

`.github/scripts/ci_dbi_inspect_campaign_link_persistence.py` se ejecuta
en PostGIS efímero de GitHub Actions, DESPUÉS de crear el fixture INSPECT:
identidad scoped, denegación READ-only y WRITE-only, cross-tenant y
cross-plot, rechazo a Density, rechazo a versión antigua, repetición
idempotente, conflicto de Campaign y verificación de fila persistida.

No se utiliza producción, almacenamiento S3 real ni credenciales ajenas al
contenedor efímero de CI. Ningún cambio de algoritmo o FRONTEND en este PR.

## Bloqueos para la siguiente fase

- **Sin endpoints nuevos.** Ninguna cuenta puede llamar a este servicio
  por HTTP hasta diseñar una ruta interna dedicada y auditar membresías
  reales de técnico/administrador DALGORO. `WRITE` scoped es necesario,
  pero todavía no demuestra por sí solo la condición laboral de técnico.
- Sin firma técnica ni administrativa en este PR, sin publicación READ
  y sin enlace al catálogo del cliente. GET INSPECT READ-only sigue
  bloqueado por #216.
- La verificación multiespectral profunda exigirá cadena real
  Campaign→job→artefacto→ráster READY y coincidencia de extracción/UP,
  antes de autorizar publicación o generar material para entrenamiento.
- En la interfaz técnica futura, cada nueva INSPECT deberá **seleccionar
  Campaign válida** como parte del proceso de captura, pero no forzaremos
  cambios en esquemas INSPECT legacy sin migración y compatibilidad offline.
- Aprobaciones persistidas requieren dos actores diferentes, permisos
  correspondientes, serialización, firma sobre versión vigente, auditoría
  y rechazo de correcciones. El cliente solo visualizará versiones con
  publicación efectiva, nunca borradores ni una aprobación inferida por
  la existencia de dos filas.

## Puertas de salida

PR con CI completamente aprobado, suite PostGIS integrada y revisión del
estado de `main`. Después, servicio de firmas transaccionales + API
interna con pruebas RBAC, seguido de catálogo READ-publicado scoped.
UAT visual/móvil y despliegue controlado serán fases posteriores.
