# DBI-H11-DEC-001 — INSPECT ligado a Campaign MULTI, aprendizaje supervisado y roles

> **DECISIÓN POSTERIOR CONFIRMADA — doble aprobación obligatoria:** cada versión INSPECT
> debe recibir **dos firmas independientes**, una validación técnica seguida de
> una autorización administrativa, antes de publicarse o ser consultable por el
> cliente. Una persona no puede firmar ambos pasos. La corrección abre un nuevo
> ciclo. Véase [DBI-H11-DEC-002](78_DBI_INSPECT_DUAL_APPROVAL_POLICY_H11.md).
> La política pura está bajo prueba; todavía no hay aprobación persistida ni
> filtrado de publicación en las API existentes.

**Decisión del producto (11-10-2026).** El cliente ha precisado que **cada nueva INSPECT del flujo de monitoreo debe pertenecer a un levantamiento MULTI identificable**. La razón es construir verdad-terreno capaz de contrastar señales espectrales con afectaciones observadas del banano y, tras validación científica, estudiar detección/estadificación de Sigatoka negra. **El cliente externo tiene consulta únicamente; el técnico y el administrador pueden registrar y corregir según permisos, y solo una autoridad agronómica explícita puede aprobar/publicar.**

Este documento es un **contrato de diseño**, no una implementación de vínculos nuevos, inferencia o despliegue. No autoriza cambios en producción ni transforma el actual gate de Sigatoka en diagnóstico.

## 1. Estado comprobado de GitHub `main`

- `DBIMultispectralExtractionRecord` exige `observation_version_id` que referencia la versión INSPECT, además de `source_raster_product_id`. `_resolve_observation` comprueba tenant, organización, finca, lote, evidencia `observed` y coincidencia exacta de `sampling_point_id/up_id`; `_resolve_scientific_raster` exige ráster científico `ready` del mismo scope.
- La procedencia del vuelo se obtiene por cadena explícita **extracción → ráster → artefacto → job finalizado → Campaign multiespectral**. Si falta o falla un eslabón, `campaign_linkage=unverified` y `campaign_id/captured_at=null`. Ni GPS cercano ni fechas iguales sustituyen esa cadena.
- INSPECT contiene `observed_at`, `foure`, YLS, hojas funcionales, asociación opcional UP/punto, GPS y versiones inmutables con corrección append-only. Actualmente no contiene una vinculación primaria directa obligatoria a `campaign_id`, y el API INSPECT solo permite GET **por observation_id** y sus versiones; **no existe un GET paginado por Campaign**.
- `sigatoka_readiness.py` solo tiene un gate para `sigatoka_early_risk` enfocado en **Fouré (1, 2)** y requiere modelo aprobado, verdad-terreno observada, partición de prueba por finca/fecha, suficientes positivos/negativos, sensibilidad y calibración adecuadas. No existe evidencia de un clasificador aprobado de estadios 0–6 en el portal.
- Permisos backend existentes: `READ`, `WRITE`, `SUBMIT_ANALYSIS`, `APPROVE_AGRONOMIC` y `MANAGE`; se resuelven por membresías y ámbitos efectivos (tenant/organización/finca/lote) **en servidor**, no por el título del usuario. Los permisos concretos de las cuentas clientes actuales deben auditarse antes de publicar nuevas rutas.
- #213 añadió una consulta INSPECT manual por UUID como solución transitoria. **No cumple la experiencia final**: la ruta principal será abrir el levantamiento y consultar las observaciones vinculadas; nunca pedir UUID al productor.

## 2. Identidades y vínculos obligatorios

Una **Campaign multiespectral = un levantamiento** de un lote (ID canónico, `captured_at` con zona horaria, productos científicos y estado).

Relación objetivo:

```text
Tenant / Organización / Finca / Lote
  └─ Campaign MULTI (levantamiento, captured_at)
       ├─ Ráster científico → artefacto/job verificado
       ├─ Plan de muestreo / puntos / UP (identidades comprobadas)
       └─ INSPECT 1..N (observación de campo, observed_at)
            └─ versión observada inmutable (Fouré, YLS, hojas, GPS, etc.)
                 └─ extracción MULTI 0..N (versión + ráster exactos)
                      └─ pares etiquetados elegibles para dataset
                           └─ modelo versionado y validado → inferencia advisory
```

**Cardinalidad.** Una Campaign puede contener **muchas observaciones INSPECT** (varias plantas/UP/hojas y puntos por vuelo). En el flujo nuevo cada observación se asigna a un levantamiento principal; no se duplica la verdad-terreno ni se asigna una misma versión de INSPECT a otro vuelo por coincidencia temporal. Una nueva Campaign requiere nuevo registro de visita/observación o un mecanismo explícito de revisita conforme al protocolo, nunca copiar una etiqueta anterior automáticamente.

La asociación `Campaign ↔ INSPECT` debe ser **expresa, persistente, auditada y scoped**, con `campaign_id`, `observation_id`, `observation_version_id`, scope completo, `sampling_point_id/up_id`, autor, método, tiempos y estado `pending/verified/rejected`. Preferir entidad de asociación versionada/append-only sin reescribir observaciones científicas ni cambiar identificadores existentes. El diseño concreto de FKs/constraints es una tarea backend separada, no una migración implícita de este documento.

**Regla de integridad:** la Campaign debe tener `analysis_type=multispectral` y el mismo scope; INSPECT tiene evidencia `observed`, versión comprobada y unidad/punto compatibles; la extracción debe referenciar esa misma versión, un producto científico READY y cadena Campaign verificada. **Una Campaign sin procedencia válida o con UP ambigua jamás ingresa al dataset supervisado.** Evidencia histórica sin Campaign verificada queda `pending/unlinked` y puede mostrarse en vista técnica con advertencia, no convertirse en pares de entrenamiento.

**Tiempo:** `captured_at` del vuelo, `observed_at` de campo y `created_at` de procesamiento permanecen separados. Un intervalo aceptable campo-vuelo requiere protocolo científico versionado y revisión, no una unión SQL automática por día/mes. GPS y precisión, ubicación real de la UP y geometría de soporte deben permitir correspondencia inequívoca; una ventana sustituta no equivale a COPA_UP.

## 3. Experiencia de usuario, conservando mapa como vista principal

Al abrir **Campaign MULTI 2026-...** en el mapa: mantener mapa, fecha, producto y selector actual; en **Seguimiento del lote** presentar **Observaciones INSPECT de este levantamiento**, con fecha de campo, UP/punto validado, escala Fouré observada, YLS, hojas funcionales, soporte espacial, procedencia y revisión técnica. Mostrar `Sin observaciones vinculadas verificadas` si no hay filas; **no equivale a cultivo sano**. Las observaciones de otra Campaign no aparecen aunque coincida la fecha.

- Cliente: navegación y lectura de Campaigns/resultados efectivamente **publicados y autorizados** en su lote; acceso a evidencia aprobada, fechas, observaciones y limitaciones. **Nunca** alta/corrección/asociación/aceptación de INSPECT, subida/publicación GIS, entrenamiento/validación/administración de modelos. Ocultar controles en frontend **no sustituye** denegación de endpoints WRITE/MANAGE del backend.
- Técnico DALGORO: elegir Campaign legítima al entrar a muestreo/INSPECT, registrar observaciones `observed`, proponer vínculo exacto con UP/punto, adjuntar evidencia y **corregir creando nueva versión** (no sobrescribir); ver su estado de revisión. Requiere `WRITE` scoped y permisos de archivos que correspondan.
- Administrador DALGORO: revisar evidencia y asociaciones, autorizar mediante permiso específico `APPROVE_AGRONOMIC`, gestionar modelos/datasets/publicación bajo `MANAGE` donde proceda. **Ser técnico no concede aprobación**, y ser administrador no cancela ámbitos de tenant/lote. La pertenencia/rol real debe materializarse en las membresías de autorización existentes.
- No exponer notas privadas de auditoría, identificadores personales del técnico o etiquetas internas de entrenamiento al cliente sin diseño y autorización explícitos.
- La consulta por UUID del #213 queda temporal para soporte/auditoría, pero **no será la navegación principal** del productor. Cuando exista el endpoint por campaña, debe sustituirse o relegarse al área técnica.

## 4. Aprendizaje: observado ≠ derivado ≠ inferido

**Etiquetas (verdad-terreno).** Fouré 0–6 es un **registro observado con protocolo**, no un diagnóstico espectral. Registrar qué hoja/planta/UP se observó, fecha/hora, evaluador, escala aplicada, control de calidad y correcciones. No usar observaciones `not_measured` / `not_applicable` como clase cero, ni convertir automáticamente una UP en toda la hectárea. Confirmación clínica/fitopatológica y protocolo son necesarios cuando corresponda.

**Variables (espectro).** Entrenar con bandas/índices/estadísticos y sus máscaras, calidad y versión; no presumir que NDVI/NDRE aislados distinguen Sigatoka de estrés hídrico, deficiencias, sombras, fenología o variabilidad de captura. Incluir `support_mode`, calibración, sensor, fecha, huella y proporción de píxeles válidos. COPA_UP segura es elegible tras QA; ventana sustituta se conserva como exploratoria/no elegible por defecto para estadificación de UP, hasta aprobación de protocolo.

**Dataset.** Solo pares con vínculo `verified`, etiqueta humana observada, procedencia de ráster/Campaign y soporte espacial compatibles; dataset **versionado e inmutable** con auditoría de inclusiones, exclusiones, variables y SHAs. No entrenar cruzando tenants sin autorización/licencia explícita y base de gobernanza apropiada. La ausencia de revisita no invalida observaciones transversales; cambios temporales solo con revisita de identidad espacial inequívoca.

**Modelo.** Entrenamiento **supervisado, offline y versionado**; nada de modificar pesos en producción cada vez que llega un INSPECT. Primero experimentar con riesgo temprano Fouré 1–2 bajo el gate `sigatoka_readiness.py`; para estadios 0–6 se necesita otro contrato, suficientes etiquetas por clase y validación independiente. Separar fincas y fechas para holdout (evitar fuga entre plantas del mismo vuelo), validar diferentes condiciones, sensibilidad, especificidad, matriz de confusión/calibración, intervalos de incertidumbre y desempeño en nuevas fincas. Model registry: `draft → validated → approved → retired`, con aprobación explícita.

**Resultados al cliente.** Mientras no exista un modelo aprobado y su gate científico no esté `ready`: mostrar **solo INSPECT observado y MULTI derivado**, `Sin inferencia Sigatoka validada`. Tras aprobación se podrá mostrar `indicio/riesgo estimado por modelo versión X` con incertidumbre y recomendación de **verificación de campo**, **nunca diagnóstico confirmado ni receta fitosanitaria**. No presentar estadio Fouré predicho como Fouré observado.

## 5. Microhitos técnicos futuros y gates

1. **Contrato de asociación Campaign–INSPECT**: entidad/FKs/estados/autoría, write técnico solo dentro de scope, validación de tiempos, UP y versión, auditoría. Evaluación de impacto, migración aislada y CI específica antes de tocar producción.
2. **GET paginado READ por Campaign**: filas verificadas/publicables, filtros de scope, límites y no enumerabilidad 403/404, respuesta mínima; pruebas de tenant cruzado, lotes y vuelos mismo día. No mezclar resultados de otras campañas ni mostrar pendientes al cliente.
3. **UX dual con mapa estable**: cliente pestaña `Seguimiento` sin edición; técnico flujo interno de captura/versión/asociación; admin revisión/publicación. Pruebas de permisos reales, móvil/escritorio y navegación mediante roles.
4. **Dataset supervisado trazable**: materializador reproducible con evaluación QA, manifiesto versionado, consentimientos y criterios de exclusión; no crear inferencia.
5. **Modelo y validación**: familia de riesgo temprano Fouré 1–2; después, si la calidad lo justifica, contrato ordinal para estadios 0–6; registro/validación/approval gate; no automatizar tratamientos.

### Pruebas de aceptación irrenunciables

- Una Campaign con múltiples INSPECT verificadas se consulta sin ingresar UUID.
- Dos Campaign de misma fecha no comparten observaciones por coincidencia.
- Ningún cliente con `READ` puede crear, corregir, asociar, aprobar, publicar ni llamar exitosamente endpoints reservados a técnicos/admin, incluso fabricando peticiones HTTP.
- Corrección INSPECT conserva versión anterior y obliga a revisar elegibilidad de pares afectados.
- Evidencia no vinculada, mala GPS, soporte de ventana o etiqueta ausente no genera un ejemplo supervisado falso.
- Estado `published` y auditoría de permisos se validan en backend, no solo visualmente.
- Predicción no aprobada no se ofrece ni a cliente ni como recomendación agronómica automática.
- UAT visual y datos autorizados reales posteriores al CI; no confundir CI verde con validación agronómica.

**Conclusión:** implementar primero la asociación primaria Campaign–INSPECT y el catálogo READ por campaña; **no** priorizar mejoras del formulario UUID del #213 ni prometer clasificador Sigatoka inmediato. El conocimiento se construye desde la trazabilidad exacta.
