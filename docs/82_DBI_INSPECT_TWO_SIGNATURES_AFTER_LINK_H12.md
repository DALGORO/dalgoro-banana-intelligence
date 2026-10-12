# DBI-H12-SVC-002 · Dos firmas sobre vínculo Campaign–INSPECT existente

## Integración conservadora posterior a #218

`main` ya incluye el servicio de propuesta de vínculo
`DBIInspectionCampaignLinkService.propose_link` (#218) y las tablas
Campaign–INSPECT + eventos de firma de la migración 27 (#217).

Este microhito **NO crea un segundo servicio de asociación**, no hace
migraciones ni abre API. Añade únicamente
`DBIInspectionCampaignApprovalService` para firmar **un vínculo existente**,
siempre con la versión INSPECT vigente y sin publicación al cliente.

### Validación técnica
`validate_technical(context, link_id, org, farm, plot)`:
- Requiere `WRITE` scoped; no confunde personal con cliente `READ`.
- Recupera y bloquea primero la identidad estable INSPECT con
  `SELECT ... FOR UPDATE`; la corrección append-only existente toma el
  mismo lock, de modo que no puede intercalarse una nueva versión durante
  la validación.
- Bloquea también el vínculo y comprueba que apunta a la última versión
  `observed`. Reconstruye las firmas previas; rechaza replays de firma.
- Registra un evento separado `technical_validated`, sin mutar INSPECT.

### Autorización administrativa
`authorize_administrative(context, link_id, org, farm, plot)`:
- Exige `APPROVE_AGRONOMIC` y `MANAGE` scoped.
- Requiere validación técnica previa de **otra persona** sobre el mismo
  vínculo y la misma versión vigente; no basta tener ambos roles.
- Antes de firmar, verifica que exista una extracción MULTI para esa
  versión INSPECT y que la cadena explícita
  `raster científico → artefacto → job finalizado → Campaign MULTI`
  llegue a la **misma Campaign** del vínculo. Nunca usa igualdad de fechas
  o proximidad GPS como prueba.
- Agrega evento `administrative_authorized` como nueva fila;
  no publica registros y no hace commit propio.
- Si no existe una extracción verificable en las primeras 20 candidatas,
  deniega por defecto; la verificación de colecciones mayores necesitará
  una consulta scoped eficiente antes de producción.

### Semántica de correcciones

Una corrección INSPECT añade una nueva versión; el vínculo firmado de
la versión antigua sigue siendo auditable, pero **no es válido como
aprobación de la versión actual**. La nueva versión requiere nueva
propuesta de asociación y las dos firmas. El servicio #218 permanece
la autoridad sobre cómo se propone ese vínculo.

### Límites de seguridad y despliegue

- Métodos internos Python: **no endpoints de firma, ni nueva ruta de lectura
  cliente, ni UI de aprobación, ni publicación**.
- Los permisos `WRITE` / `MANAGE` no certifican por sí solos que el actor
  sea empleado/técnico DALGORO: la API interna futura **deberá** confirmar
  membership institucional confiable y distintos principales.
- El servicio usa la sesión que recibe, hace `flush`, pero el llamador
  debe controlar commit/rollback; requiere pruebas de concurrencia
  PostgreSQL real, roles DB mínimos, inmutabilidad de eventos y revocación
  antes de abrir endpoints.
- `ci_dbi_inspection_approval_service.py` es una prueba offline de sesión
  simulada, no una validación completa de transacciones PostGIS.
- El portal cliente sigue sin mostrar INSPECT pendiente por el bloqueo
  READ-only del PR #216. Las firmas internas todavía **no** hacen
  observaciones visibles ni entrenan modelos Sigatoka.
- La migración 27 ya se incorporó al repositorio, pero no fue aplicada a
  producción por este cambio.

## Próximo microhito

1. Test PostGIS real de dos actores, dos transacciones y corrección concurrente.
2. API técnica con membresía DALGORO verificada, actor derivado del servidor.
3. Separar lectura interna de lectura publicada y construir filtros
   `Campaign + versión vigente + doble firma + procedencia + estado publicado`.
4. Solo entonces mostrar observaciones aprobadas al cliente, de forma READ
   en la pestaña Seguimiento, y estudiar datasets ML validados aparte.
