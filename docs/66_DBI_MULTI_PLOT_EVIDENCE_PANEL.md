# DBI-MULTI-001 · Panel de evidencia multiespectral en mapa de lote (Hito 11)

## Objetivo y alcance

Exponer evidencia multiespectral **derivada y persistida** en el visor agrícola existente,
sin agregar datos simulados, recalcular índices, pronosticar producción o
atribuir diagnósticos a NDVI/NDRE. Se mantiene el trabajo en Hito 11;
la fase E7 de staging/recuperación operativa queda diferida al Hito 13.
Esto **no** autoriza despliegue ni sustituye UAT con datos reales.

## API: lista acotada READ

Nuevo `GET /api/v1/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/multispectral-extractions`

- Autentica identidad DBI existente mediante `X-DBI-Tenant` y sesión.
- Exige `DBIPermission.READ` y ámbito exacto de organización/finca/lote,
  con denegación HTTP 404 no enumerable.
- El SQL filtra `tenant_ref`, `organization_ref`, `farm_id`, `plot_id`.
- Retorna **máximo 20** registros; orden por `created_at DESC, id DESC`.
  No consulta ni filtra filas de otras fincas en memoria.
- Utiliza el mismo verificador de integridad del GET por ID incorporado en
  PR #202: SHA-256 canónico, identidad UUID determinista, ámbitos, versión
  INSPECT, ráster científico, Sampling/UP, perfil y exactamente 4 bandas
  + 6 índices con `evidence_kind=derived`.
- Cualquier fila corrupta del resultado bloquea la **respuesta completa**
  con HTTP 409; no entrega una lista parcial con procedencia dudosa.
- Un lote sin extracciones responde `[]`. No hay endpoint nuevo de escritura,
  cambios de tablas ni migraciones.

## Interfaz de solo lectura

`FarmMapTimeline` incorpora `MultispectralEvidencePanel` únicamente cuando
se dispone de un localizador real con tenant/org/farm/plot. El módulo está
aislado del mapa MapLibre/Google y no altera visualización ni aprobación GIS.

El panel muestra:
- opción de escoger entre extracciones recientes **reales** del lote;
- fecha, soporte `copa_up` o `window`, versión INSPECT, identidad del
  ráster científico y perfil de soporte;
- aviso explícito de `support_limitation` cuando se usa ventana;
- medianas, P10–P90, conteos y porcentaje de píxeles válidos para cuatro
  bandas y seis índices (NDVI, NDRE, GNDVI, EVI2, CI Red Edge y CI Green);
- fórmula/versionado identificable para índices y procedencia de bandas;
- estados de carga, vacío, error autenticación/403/404, corrupción 409
  e indisponibilidad 503; actualización manual.

El cliente envía `X-DBI-Tenant` explícito, usa rutas codificadas y
descarta respuestas de ámbitos anteriores al navegar. **No guarda** evidencia
en localStorage, IndexedDB ni caché persistente; no descarga COG ni objetos
S3. Las estadísticas pueden depender de calibración y calidad de fuente:
no se presentan como diagnóstico de Sigatoka, indicación de fumigación
ni estimación de cajas. Los valores de bandas se muestran sin inventar
unidades físicas que el contrato todavía no certifica.

## Verificación

- `.github/scripts/ci_dbi_multi_http.py`: permisos READ,
  tenant/org/farm/plot cruzados, vacío, 404, 409 y respuesta sin objetos
  privados, tanto para lectura puntual como lista.
- `.github/scripts/ci_dbi_multi_persistence.py`: pruebas SQL reales en
  PostGIS CI de lista bajo tenant, organización, finca y lote, incluyendo
  accesos cruzados; conserva inmutabilidad científica.
- `CI modular`: frontend ESLint + TypeScript build y backend completo.
- Los workflows MULTI y migraciones siguen siendo gates obligatorios.

## Pendiente

No existe todavía vinculación de este catálogo con un `Campaign` concreto,
ni comparador multifecha, validación de campo real, inferencia clínica,
modelos agronómicos aprobados ni distribución en staging. Esos incrementos
requieren sus propias decisiones y pruebas. El corte productivo depende
también de infraestructura, recuperación operativa, costos y UAT.
