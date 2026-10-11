# DBI-CLIENT-VIEW-006 · Lectura útil al productor sin diagnóstico automático (Hito 11)

## Objetivo
La interfaz aprobada conserva la identidad DALGORO, pero debe explicar qué
observación y qué soporte hay detrás de cada número, especialmente en móvil.
Este microhito agrega una lectura rápida de la **extracción autorizada que el
usuario ha seleccionado**. No crea datos y no deduce vigor, salud, cosecha,
Sigatoka, deficiencias, dosis ni causalidad por umbrales espectrales.

## Qué se muestra
1. **Observación INSPECT:** fecha de observación de campo, distinta de captura
   aérea o registro de cálculo.
2. **Vuelo:** fecha únicamente si existe `verified_job_chain` + UUID Campaign
   acreditada en el historial con el mismo instante real. En otro caso:
   «Fecha de vuelo no verificada».
3. **Variables disponibles:** número de registros de índices y de bandas
   existentes en el `payload`; no es un conteo de píxeles ni fincas.
4. **Soporte:** follaje atribuible a UP (`copa_up`) o ventana sustituta
   (`window`), sin convertir uno en límite parcelario ni superficie.
5. **Cobertura por índice:** `valid_count` de `selected_count` píxeles;
   porcentaje únicamente desde `valid_fraction` válido (0..1). Si los
   conteos son imposibles, informa «Cobertura de píxeles no disponible».
   **No es hectáreas, porcentaje de plantas sanas ni superficie de cobertura.**
6. **Descripción de los seis índices:** NDVI, NDRE, GNDVI, EVI2,
   CI Red Edge y CI Green con explicaciones espectrales y límites
   explícitos. Ningún índice interpreta directamente salud o enfermedad.
7. **Detalle opcional:** tablas originales de mediana, P10–P90,
   píxeles válidos, versión de fórmula y fuente se preservan íntegramente
   en un desplegable nativo con acceso por teclado y en móvil.

## Garantías
- `MultispectralEvidencePanel` sigue usando
  `extractionForMapCampaign` y `verifiedMultispectralCampaigns`,
  restringidos por tenant, organización, finca, lote y cadena verificada.
- Se conserva el mensaje de ambigüedad de dos Campaign para el mismo vuelo
  y el estado vacío cuando no existe evidencia.
- No hay cambios de endpoints, API, cálculos, fórmulas espectrales,
  reglas READ/MANAGE, migraciones ni producción.
- Los valores en pantalla deben provenir exclusivamente de
  `payload.summaries`, `observed_at`, `captured_at`,
  `support_mode` y los metadatos autorizados de esa misma extracción.

## Pruebas y aceptación pendiente
`dbiClientVisualLayout.test.mjs` comprueba la inclusión de lectura rápida,
la limitación científica, la existencia de tablas y casos límite de cobertura
(inexistente, imposible, sin fracción válida). Corre automáticamente en CI
Node 24 junto a lint y build.

CI **no acredita** pruebas visuales de Safari/Chrome en 375, 390, 768 y
1600 px, con usuarios READ y datos reales autorizados. Se debe verificar
lectura de fechas, teclado, mensajes de ausencia, soporte COPA_UP/ventana,
representación numérica y trazabilidad antes de UAT. La imagen conceptual
aprobada en `docs/69_DBI_CLIENT_VISUAL_TARGET_AND_MULTI_HISTORY.md`
permanece como referencia estética, no como evidencia de resultado científico.
