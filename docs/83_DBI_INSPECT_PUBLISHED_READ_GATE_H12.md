# DBI-H12-SVC-003 · Lectura fail-closed INSPECT doblemente aprobada (sin API)

## Propósito y estado

El vínculo INSPECT–Campaign (#218), la migración aditiva 27 (#217)
y el servicio de firmas independientes (#221) ya están en main.
Este microhito prepara **una capa de lectura para clientes**, sin abrir rutas
HTTP ni habilitar información no revisada.

`DBIInspectionPublishedReadService.get_approved()` recupera una observación
por `Campaign ID + observation_id` y devuelve únicamente un DTO mínimo si
TODAS las condiciones son verdaderas:

1. Usuario tiene permiso `READ` scoped en el tenant/organización/finca/lote.
2. Campaign solicitada es `multispectral`, tiene `captured_at` real y
   está en estado explícito `PUBLISHED`.
3. El vínculo Campaign–INSPECT pertenece exactamente al mismo scope y
   a esa observación.
4. El vínculo se refiere a la **última** versión INSPECT `observed`.
   Una corrección posterior bloquea la lectura de la versión previa.
5. El libro persistido contiene **dos firmas válidas**, una técnica y otra
   administrativa de identidades diferentes y orden temporal correcto.
6. La extracción espectral tiene procedencia verificable por la cadena
   ráster científico → artefacto → trabajo concluido → la misma Campaign.
7. El `payload_json` sigue coincidiendo con su SHA-256, valida contra
   contrato INSPECT y conserva tenant/org/farm/plot/fecha/UP/punto de
   muestreo congruentes con el registro persistido.

Si cualquier condición falla, `DBIInspectionPublishedUnavailable` deniega
la lectura. Esto no transforma Fouré observado en diagnóstico inferido.

## Salida mínima para el productor

`DBIApprovedInspectionSummary` únicamente devuelve:
`campaign_id`, `observation_id`, `version_id`, fecha de observación,
UP/punto si están registrados, estado/valor de Fouré, YLS y hojas
funcionales. Un `not_measured` permanece como ausente, no se inventa 0.

**No se exponen** autor/evaluador/operador, notas libres de campo, archivos
privados, ubicación GPS detallada, SHA o payload crudo. Los campos visibles
son únicamente datos registrados y autorizados, no afirmaciones de salud
del banano ni probabilidades de Sigatoka.

## Seguridad, límites y trabajo pendiente

- Este PR NO agrega endpoint HTTP, tabla/migración, permisos, escrituras,
  interfaz, cambios de roles, despliegue ni entrenamiento de IA.
- No habilitar el antiguo GET por UUID a cuentas `READ` sin `WRITE`.
- `ci_dbi_inspection_published_read.py` cubre cliente sin scope, Campaign/
  vínculo ausente, versión obsoleta, evidencia derivada, falta de firmas,
  cadena científica ausente, SHA alterado y DTO sin información privada.
- El servicio comprueba la versión mediante lecturas en la sesión de SQLAlchemy;
  antes de exponerlo por API **faltan pruebas transaccionales PostGIS reales de
  correcciones concurrentes** y una política de aislamiento/locking que evite
  una nueva versión confirmada mientras se construye la respuesta.
- También falta un catálogo **paginado y seguro por Campaign** para no pedir
  UUID al productor; debe filtrar la elegibilidad en el servidor, sin
  revelar IDs de INSPECT pendientes ni contadores internos de otros lotes.
- La membresía institucional real de técnicos y administradores debe
  auditarse antes de habilitar firmas por HTTP. Los métodos internos de
  aprobación existentes NO certifican por sí mismos identidad DALGORO.
- Los datos de entrenamiento científico requieren QA de tejido COPA_UP,
  protocolo y validación por clase; la publicación de campo no equivale
  a autorización para entrenar, clasificar estadios ni indicar tratamientos.
- CI de servicios con mocks **no equivale** a ejecución real con PostGIS,
  usuarios autorizados y revisión de privacidad. Staging y producción
  quedan fuera del alcance.

## Siguiente puerta de entrada

Solo una vez completadas la prueba transaccional, auditoría de membresías,
GET paginado por Campaign, políticas de publicación y UAT, se podrá conectar
el cliente al panel `Seguimiento del lote` en modo estrictamente READ.
