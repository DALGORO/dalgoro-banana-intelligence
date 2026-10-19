# UX productor · Fase 4 — lectura comprensible de los seis índices

## Alcance independiente
Rediseño conservador de la lectura multiespectral en `MultispectralEvidencePanel.tsx`, rama aislada sobre `main`, sin dependencia de #280/#281/#282 ni de H14.

- El productor visualiza tres conceptos **sin gráficos con umbrales artificiales**: mediana de píxeles válidos, intervalo descriptivo P10–P90 y contexto de soporte/observación de campo.
- Cada ficha separa visualmente **Dato derivado**, **Qué describe** y **Qué no permite concluir**. Un índice por sí solo no identifica enfermedades, causas ni tratamiento.
- El resumen proviene únicamente de `selected.payload.summaries` de la extracción autorizada que ya resuelve `extractionForMapCampaign`.
- Un helper de presentación nuevo en `producerEvidenceReadout.ts` no calcula nuevos índices ni estadísticas: formatea `p10` y `p90` persistidos, rechazando recuentos inválidos, intervalos invertidos y no finitos. Si no existen datos válidos, indica «No disponible».
- No se comparan campañas entre fechas; el porcentaje de píxeles válidos sigue sin equivaler a área, porcentaje de plantas sanas ni productividad.
- Estilos aislados en `dbi-multi-readout-guide.css`, responsivos y modo oscuro. Test en la suite visual DBI ya ejecutada por CI.

## Invariantes
No toca requests, tenant/org/farm/plot, `selectedMapCampaignId`, método de selección, versiones de fórmula, algoritmos NDVI/NDRE/GNDVI/EVI2/CI, capturas INSPECT, mapas, permisos READ/MANAGE, S3, SQL, carga de TIFF ni publicación.

## Aceptación y límites
1. `node --test tests/dbiClientVisualLayout.test.mjs` y `npm run build` exitosos con lint de línea base.
2. Cualquier valor nulo/no finito/contradictorio debe mostrarse como no disponible; no se inventan líneas de referencia agronómicas.
3. Revisar manualmente legibilidad móvil con datos autorizados antes de integrar.
4. Gitleaks puede detectar un falso positivo histórico exploratorio ya identificado por PR UX anteriores; **no desactivar el escáner ni aprobar merge mientras el check de seguridad esté rojo**.
5. Mantener el PR en borrador hasta autorización; sin migraciones ni despliegues Render.
