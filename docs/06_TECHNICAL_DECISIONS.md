# 06 — Decisiones técnicas

## DEC-001
**Decisión:** usar un monorepositorio modular.

**Motivo:** los módulos comparten usuarios, fincas, lotes, contratos y datos,
pero deben poder evolucionar y probarse por separado.

## DEC-002
**Decisión:** no subir ortofotos, GeoPackage, pesos de modelos, datasets,
resultados generados ni credenciales a Git.

**Motivo:** seguridad, tamaño y rendimiento del repositorio.

## DEC-003
**Decisión:** conservar los sistemas importados sin refactorización destructiva
durante el primer commit.

**Motivo:** mantener una línea base reproducible antes de integrar.

## DEC-004
**Decisión:** considerar `apps/platform-web/backend` como candidato a API central
de DALGORO Banana Intelligence.

**Motivo:** ya contiene FastAPI, autenticación, usuarios, empresas, documentos,
suscripciones, auditoría y migraciones. La adaptación definitiva se diseñará en
`DBI-ARC-001`; `DBI-SEC-001` no fusiona ni refactoriza módulos.

## DEC-005
**Decisión:** aislar físicamente PostgreSQL/PostGIS de los sistemas existentes.

**Motivo:** evitar que una conexión, migración o error operativo de la nueva
plataforma altere bases que ya funcionan en producción.

**Controles obligatorios:**

- Usar `DBI_DATABASE_URL` exclusivamente para la plataforma nueva.
- No copiar ni reutilizar la conexión productiva actual.
- Crear bases separadas para desarrollo, pruebas, staging y producción.
- Usar servicios nuevos para staging y producción.
- Mantener historial Alembic DBI independiente.
- Detener una migración si el entorno o nombre de base no pertenece a la lista
  autorizada.
- Separar roles `dbi_migrator`, `dbi_app` y `dbi_readonly`.
- Ejecutar migraciones de producción solo con aprobación explícita.

## DEC-006
**Decisión:** no registrar payloads completos de webhooks ni datos personales en
logs de infraestructura.

**Motivo:** los eventos pueden incluir teléfonos, mensajes, ubicaciones y otros
datos personales. Los logs operativos deben limitarse a metadatos técnicos
mínimos; el almacenamiento funcional autorizado en Google Sheets se mantiene
sin cambios en este ticket.

## DEC-007
**Decisión:** validar cada módulo en un trabajo de CI independiente y sin acceso
a servicios operativos.

**Motivo:** una compilación global no permite identificar qué módulo rompió la
instalación ni demuestra que sus dependencias, importaciones y endpoints mínimos
funcionen.

**Controles obligatorios:**

- Instalar cada `requirements.txt` en su propio runner.
- Ejecutar `pip check` y `compileall` por módulo.
- Probar el backend con SQLite en memoria y sin ejecutar migraciones.
- Sustituir Google Sheets antes de importar el bot en el smoke test.
- No invocar Green API, Render, PostgreSQL ni descargar modelos de IA.
- Instalar e importar el motor geoespacial sin procesar ortofotos.
- Ejecutar lint y build del frontend con Node 24.
- Mantener visibles los 115 avisos heredados de lint y rechazar cualquier
  incremento mediante una línea base cuantificada.
- Bloquear secretos detectados y registrar auditorías de dependencias aunque
  existan hallazgos heredados que requieran un ticket separado.
- Fijar las acciones externas a SHA completos para reducir riesgo de cadena de
  suministro.
