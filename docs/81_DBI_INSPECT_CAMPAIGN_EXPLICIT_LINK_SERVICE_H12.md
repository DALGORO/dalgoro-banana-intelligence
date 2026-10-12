# DBI-H12-SVC-001 · Vinculación explícita INSPECT–Campaign antes de doble firma

## Avance de programación

Se implementó `DBIInspectionCampaignLinkService.propose_link()` como servicio de **trabajo interno**, sin rutas nuevas, sin cambios de frontend y sin publicar datos al productor.

Recibe un **tenant_ref de destino explícito**, una **Campaign ID explícita**, un `observation_id` y una `observation_version_id`; compara tenant destino contra la autorización real del usuario antes de consultar datos. Comprueba `WRITE` por tenant, organización, finca y lote; requiere Campaign multiespectral scoped con `captured_at`; bloquea la identidad de la observación con `SELECT ... FOR UPDATE` compatible con la corrección INSPECT existente, y exige que la versión sea la última y `evidence_kind=observed`.

La vinculación se inserta en `dbi_inspect_campaign_links` creada por la migración 27, con el responsable `linked_by_ref`. El replay exacto es idempotente y no genera nueva fila. La misma versión con otra Campaign es conflicto; además PostgreSQL impone `UNIQUE(observation_version_id)` y FKs scoped compuestas. La sesión de la transacción pertenece al llamador; el servicio hace `flush` pero **no commit ni rollback**.

## Estado científico

Esta asociación es una **propuesta explícita de relación**, NO una correspondencia espectral verificada, autorización de campo, permiso para ML ni aprobación del cliente. El servicio no supone que la cercanía GPS o temporal significa igualdad de tejido/UP. Se deben verificar después Campaign/job/artefacto/ráster, `observed_at`, precisión GPS, localización UP/soporte COPA_UP, protocolo, calidad y versión de fuente.

Aunque la tabla admite atribuir una misma observación con distintas versiones a Campañas diferentes, **no se heredan firmas**, y la corrección no implica una campaña nueva de forma automática. Esto requiere política operativa en el backend posterior.

## Permisos y publicación

- El servicio exige `WRITE` scoped, pero **no está expuesto por API**. `WRITE` no prueba por sí solo identidad de personal DALGORO: la capa de rutas del próximo hito debe verificar la membresía profesional real.
- Las firmas técnica y administrativa obligatorias siguen pendientes de servicio transaccional y pruebas. Deben ser de **dos actores distintos** y estar vinculadas a una versión vigente; el admin exige `MANAGE + APPROVE_AGRONOMIC`.
- Las rutas cliente INSPECT **siguen bloqueadas** por #216. Ningún vínculo creado por este servicio constituye publicación, ni esta mejora permite que el cliente consulte un borrador.
- La migración 27 existe en `main` pero no se ha aplicado a producción; no ejecutar contra DB de producción.

## Pruebas

`.github/scripts/ci_dbi_inspect_campaign_link_service.py` comprueba permisos, rechazo cross-tenant y cross-plot, Campaign/observación ausentes, versiones incorrectas, `evidence_kind` distinto de observed, conflicto entre campañas, replay idempotente, contrato FOR UPDATE y ausencia de escrituras ante errores.

**Pendiente de la siguiente fase:** pruebas SQL reales de flujo completo bajo PostGIS efímero con roles del staff, idempotencia bajo concurrencia, firma técnica, firma administrativa y separación READ interno vs READ publicado. CI del servicio por dobles de sesión no equivale a una validación productiva.
