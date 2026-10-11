# DBI-CLIENT-VIEW-002 · Selección sincronizada mapa / MULTI por Campaign (Hito 11)

## Decisión de producto y referencia aprobada

La imagen conceptual aprobada de DALGORO Banana Intelligence sigue siendo la
**referencia oficial** de experiencia del cliente según
`docs/69_DBI_CLIENT_VISUAL_TARGET_AND_MULTI_HISTORY.md`. Este microhito
conecta la franja histórica multiespectral (PR #206) con la fecha
cartográfica del mapa, conservando su independencia técnica y la
separación por tenant, organización, finca y lote.

La selección se sincroniza por **identificador de Campaign real y
captured_at con zona horaria** cuando el cliente elige un vuelo MULTI
verificado. Una misma fecha puede pertenecer a más de una Campaign:
no basta empatar un día o una hora para asociar evidencia.

## Reglas de sincronización

1. El cliente elige una tarjeta en el historial MULTI
   (`verified_job_chain` del backend): el mapa recibe
   `campaign_id` + `captured_at`. Los rásteres y capas vectoriales
   se muestran únicamente si coinciden **ambos**, con el scope
   autorizado ya existente. La fecha aparece en el selector principal
   aunque ese vuelo solo tenga estadísticas y no tenga RGB/GIS.
2. Si no existen capas cartográficas de esa Campaign, el mapa muestra
   explícitamente `Sin capas cartográficas para la Campaign MULTI seleccionada`;
   no recupera automáticamente capas de otra campaña de igual fecha.
3. Al cambiar el selector principal de fecha, se limpia la selección
   estricta de Campaign. El panel MULTI busca una única Campaign
   verificada coincidente en el instante exacto (comparando UTC).
   Cuando hay cero o varias, **no muestra estadísticas numéricas como
   pertenecientes al mapa**: conserva el historial para que el
   cliente elija el vuelo exacto.
4. Si el cliente elige una extracción sin vínculo Campaign, el mapa
   pasa a `Todas las fechas`, sin sugerir que corresponde a un vuelo.
   La extracción sigue siendo consultable como evidencia derivada.
5. La selección estricta almacena el identificador del scope
   tenant/org/farm/plot. Un cambio de lote no reutiliza la Campaign
   anterior. El panel ya elimina respuestas asíncronas de scope previo.
6. Una inspección de GIS importada conserva su fecha/ID Campaign
   exactos para la vista previa, sin publicar automáticamente.

El mapa no se vuelve un nuevo endpoint: sigue utilizando los
catálogos GIS/RGB autorizados. El backend MULTI sigue limitado a
20 extracciones y no recibe cambios. No se fusionan Campaign de
trabajos científicos diferentes aunque compartan `captured_at`.

## Pruebas de regresión

`apps/platform-web/frontend/tests/multispectralCampaignHistory.test.mjs`
se extiende para verificar:

- fecha compartida sin ID → no selección arbitraria;
- ID Campaign exacta → solo su propia extracción y capas;
- equivalencia temporal de distintas zonas horarias;
- fecha incompatible → sin estadísticas del vuelo anterior;
- tenant, organización, finca o lote diferente → bloqueo;
- evidencia sin Campaign → solo fuera de asociación cartográfica.

El frontend ejecuta estas pruebas Node 24, ESLint y build
TypeScript/Vite, además del CI modular y los workflows especializados
existentes. No se introducen algoritmos NDVI/NDRE, comparaciones
científicas, regresiones estadísticas, inferencias Sigatoka,
recomendaciones, credenciales, migraciones ni modificaciones en Render
o S3.

## Limitaciones y aceptación visual

El selector del mapa continúa siendo cronológico; elegir una fecha
puede mostrar varias Campaign cartográficas por ese instante, pero
el panel MULTI **no hará** una asociación ambigua. La selección por
tarjeta MULTI sí restringe por Campaign exacta.

En la revisión visual de escritorio y móvil deberá comprobarse:
selector fecha principal ↔ franja MULTI, dos Campaign con misma
captura, campaña sin capas GIS, ausencia de campañas, cambios de
lote, pantalla con 401/404/409, lectura sin permiso MANAGE,
desbordamiento de tablas y layout del mapa. El mockup no se declara
replicado pixel a pixel únicamente por haber aprobado CI.

La comparación de variaciones entre vuelos permanece pendiente de
controles científicos de calibración, unidad espacial, soporte,
huellas y fórmulas. Staging y UAT real siguen en Hito 13.
