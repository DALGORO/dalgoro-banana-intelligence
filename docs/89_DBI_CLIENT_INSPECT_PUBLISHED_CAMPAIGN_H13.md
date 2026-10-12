# H13 · INSPECT aprobado por Campaign en el seguimiento del productor

## Experiencia de cliente

La ficha de seguimiento del lote, cuando tiene Campaign MULTI exacta
seleccionada, consulta automáticamente **sólo resultados INSPECT publicados**.
Nadie necesita ingresar el UUID de una observación.

Ruta GET de lectura exclusivamente:
`/api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/published-inspections`.
Tenant y sesión se obtienen del backend DBI autenticado, nunca de campos
de identidad libre; `X-DBI-Tenant` sigue el contexto actual validado.
No se agregan POST, endpoints de firma, altas de personal o publicaciones.

## Regla fail-closed

El servicio comprueba:
- permiso `READ` de la membresía DBI y coincidencia exacta de
  tenant/organización/finca/lote y Campaign MULTI `PUBLISHED`;
- vínculos explícitos Campaign–INSPECT, sin inferencia por fecha, UP ni
  proximidad cartográfica;
- última versión INSPECT observada, sin correcciones posteriores;
- `technical_validated` y `administrative_authorized` válidos para
  dos actores distintos o una sola persona DALGORO con ambos cargos,
  verificadas al momento de registrar la firma;
- cadena científica MULTI de procedencia y SHA del payload correctos;
- máximo de 100 vínculos candidatos por petición: más que eso devuelve
  `404`, no un subconjunto parcial aparentemente completo.

La lectura descarta observaciones no elegibles y **jamás devuelve** su
identidad ni su contenido. Un conjunto vacío de resultados no permite
inferir ausencia de visitas o enfermedades.

## Proyección de privacidad

El DTO publicado incluye **sólo** `observed_at` y valor+estado de las
tres mediciones Fouré, YLS y hojas funcionales. No expone UUID internos,
nombres de técnicos, notas, fotos, GPS, UP ni `payload_json`.
`not_measured` se presenta como **No medido**, jamás como cero.

El frontend reinicia el resultado al cambiar de lote/campaña y descarta
respuestas tardías anteriores; permite reintentar la consulta. No guarda
evidencia en almacenamiento local ni la atribuye a otra Campaign.

## Estado de ejecución

El contrato y la experiencia son verificables por tests offline
y pipelines. **No se inventan observaciones** para mostrar tarjetas:
si aún no se han acreditado empleados o firmado Campaigns legítimamente,
el productor verá una ausencia de resultados publicados, nunca datos
sintéticos. La migración institucional de personal continúa sin
aplicarse en producción y todavía no existen rutas operativas de firma.
Este PR no despliega nada en Render ni activa accesos productivos.

No toca Sigatoka/IA, YOLO, GIS, algoritmos, imágenes o reglas de publicación
científica. Antes de habilitarlo para clientes reales se requiere
validación completa de permisos HTTP, catálogo publicado y UAT de navegador
en móvil y escritorio.
