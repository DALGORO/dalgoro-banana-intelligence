# DBI-CLIENT-VIEW-008 · Consulta INSPECT autorizada por ID en la ficha de lote (Hito 11)

## Descubrimiento del contrato existente

La API actual `dbi_inspection.py` **NO expone un listado GET de observaciones por lote**.
Solo ofrece READ por identidad:
`GET /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/field-observations/{observation_id}`,
y lectura de versiones de esa identidad. Crear, corregir y asociar UP son WRITE,
y quedan fuera de este microhito. El frontend no adivina IDs ni utiliza
caché offline privado como sustituto de un catálogo READ del servidor.

## Diseño elegido y utilidad para el productor

El mapa y las pestañas creadas en #212 siguen activos.
La pestaña **Seguimiento del lote** permite consultar **una observación
INSPECT conocida** introduciendo su UUID, facilitado por personal técnico.
El botón ejecuta la consulta únicamente bajo petición explícita y
solo cuando el ID tiene formato válido. No se descarga ninguna colección
de observaciones ni se muestran fotos o rutas a S3.

De un registro autorizado se presenta:
- Fecha de observación INSPECT y fecha de registro de versión **por separado**.
- Versión del registro vigente, ID de UP si consta, ID del punto de muestreo
  si consta, y existencia/precisión declarada de GPS.
- Valores observados de Fouré, YLS y hojas funcionales;
  `not_measured` / `not_applicable` se expresan como **No medido** /
  **No aplicable**, nunca como `0`, normalidad ni diagnóstico.
- Recordatorio explícito de que ninguna relación con la Campaign aérea
  se presume por coincidencia de fecha, localización o UP.

## Garantías

- READ y alcance del servidor existentes, con cabecera `X-DBI-Tenant`;
  protección adicional en el cliente contra ID, tenant, organización,
  finca, lote y tipo de evidencia discordantes.
- Sin consultas automáticas, sin escribir datos, sin listado ficticio,
  sin IndexedDB/localStorage para las lecturas ni caché entre lotes.
- Control de secuencia y desmontaje por `scopeKey` para no mostrar
  una respuesta antigua tras navegación, edición de ID o petición nueva.
- Las respuestas 401/403/404/409/503 muestran mensajes neutrales.
  403/404 no revelan si otra finca posee el ID.
- Sin inferencias sobre Sigatoka, plantas sanas/enfermas,
  fertilización ni comparaciones multifecha.
- Sin endpoints nuevos, migraciones, despliegue,
  modificación de roles ni algoritmos científicos.

## Limitación y siguiente trabajo backend opcional

Esta primera consulta **requiere conocer el ID de la observación**.
Para que el productor consulte todas sus observaciones sin introducir UUID,
el próximo microhito requerirá diseñar y revisar un contrato
`GET field-observations` por lote, con autorización READ, paginación,
límites, filtros y pruebas de aislamiento. No se debe aprobar tal API
sin validar su privacidad, volumen, visibilidad de campos y procedencia.
La consulta por ID permite avanzar de forma segura sin ese cambio todavía.

## Gate y pruebas pendientes

`tests/dbiClientVisualLayout.test.mjs` prueba identidad y alcance,
estados observados/no medidos, uso READ y ausencia de llamadas de escritura.
CI completo debe pasar en el commit exacto del PR.

Quedan pendientes navegador móvil/escritorio, UAT con observaciones
reales y perfiles autorizados, versiones corregidas, estados 401/404/409
y validación de legibilidad frente a los PNG corporativos.
CI no prueba datos reales ni sustituye revisión agronómica.
