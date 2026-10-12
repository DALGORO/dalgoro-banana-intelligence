# DBI-H12-SVC-002 · Firmas y auditoría sobre vínculo Campaign–INSPECT existente

> **Regla vigente a partir de H12-AUTH-002:** ver [doc. 85](85_DBI_INSPECT_SINGLE_ADMIN_DUAL_ROLE_H12.md).
> Un único administrador DALGORO puede ser también técnico y completar
> **una sola acción de aprobación** cuando ambas acreditaciones están
> verificadas por el servidor. El historial conserva dos eventos atómicos
> con el mismo principal, sin simular independencia. Si un técnico distinto
> valida, se mantiene el flujo técnico→administrador de dos personas.
> Las afirmaciones históricas de dos principales distintos en este documento
> describen exclusivamente ese flujo de dos personas.

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
- Consulta el vínculo dentro del candado ya adquirido sobre la identidad INSPECT
  y comprueba que apunta a la última versión `observed`. No usa `FOR UPDATE`
  sobre el vínculo append-only (evita exigir `UPDATE`); reconstruye las firmas
  previas y rechaza replays.
- Registra un evento separado `technical_validated`, sin mutar INSPECT.

### Autorización administrativa
`authorize_administrative(context, link_id, org, farm, plot)`:
- Exige `APPROVE_AGRONOMIC` y `MANAGE` scoped.
- Requiere validación técnica previa de **otra persona** sobre el mismo
  vínculo y la misma versión vigente en la modalidad de dos personas.
  La modalidad unipersonal exige dos acreditaciones institucionales vigentes
  al MISMO UUID canónico y se registra en un acto del administrador.
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
propuesta de asociación y una nueva aprobación según la modalidad.
El servicio #218 permanece
la autoridad sobre cómo se propone ese vínculo.

### Límites de seguridad y despliegue

- Métodos internos Python: **no endpoints de firma, ni nueva ruta de lectura
  cliente, ni UI de aprobación, ni publicación**.
- Los permisos `WRITE` / `MANAGE` no certifican por sí solos que el actor
  sea empleado/técnico DALGORO: la API interna futura **deberá** confirmar
  membresía institucional confiable: principal único en modo unipersonal,
  dos principales distintos cuando revisa otro técnico.
- El servicio usa la sesión que recibe, hace `flush`, pero el llamador
  controla commit/rollback; eventos y vínculos no precisan privilegios
  `UPDATE`/`DELETE`. El rol de CI conserva permiso de actualización
  únicamente sobre `created_at` de la identidad INSPECT, necesario para
  obtener `FOR UPDATE` en PostgreSQL. Falta implementar garantías DB de
  inmutabilidad y revocación antes de abrir endpoints.
- `ci_dbi_inspection_approval_service.py` cubre política con mocks.
  `ci_dbi_inspection_approval_persistence.py` prueba después del fixture
  MULTI dos transacciones de firmas sobre procedencia científica real,
  separación de identidades, ACL, falta de evidencia, versión obsoleta y
  lock concurrente en PostGIS efímero. No reemplaza pruebas UAT ni
  auditoría de membresías reales.
- El portal cliente sigue sin mostrar INSPECT pendiente por el bloqueo
  READ-only del PR #216. Las firmas internas todavía **no** hacen
  observaciones visibles ni entrenan modelos Sigatoka.
- La migración 27 ya se incorporó al repositorio, pero no fue aplicada a
  producción por este cambio.

## Próximo microhito

1. Certificar membresía institucional DALGORO de técnico y administrador
   desde fuentes confiables, con principal resuelto por servidor.
2. Añadir pruebas de escritura concurrente real de corrección + firma y
   controles DB de inmutabilidad de eventos y revocación auditada.
3. Integrar lectura publicada ya preparada en #224 mediante catálogo y API
   con autorización, sin abrir el GET privado legado.
4. Ejecutar UAT de privacidad antes de mostrar evidencia READ a clientes
   y, por separado, QA de datasets Sigatoka.
