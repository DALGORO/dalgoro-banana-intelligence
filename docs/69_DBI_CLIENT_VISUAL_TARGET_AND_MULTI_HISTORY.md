# DBI-CLIENT-VIEW-001 · Modelo visual y funcional aprobado por el usuario

## Referencia de experiencia del cliente — Hito 11

El usuario aprobó el **mockup conceptual** de DALGORO Banana Intelligence
como **objetivo de diseño y funcionalidad**, no como captura exacta de
software actualmente desplegado. La composición objetivo del escritorio es:

1. Navegación y sesión privadas; únicamente fincas, lotes y campañas
   permitidos para la identidad DBI.
2. Mapa agrícola central con fondo satelital u ortofoto RGB autorizada,
   límites y capas GIS. Conmutadores de visibilidad en mapa.
3. Selección de levantamiento histórico y consulta de atributos de
   geometrías sin mezclar ámbitos o campañas.
4. Panel de evidencia multiespectral con diez variables (cuatro bandas
   y seis índices), fecha de observación INSPECT, fecha de registro del
   derivado, Campaign y fecha de vuelo **solo si están verificadas**,
   estadísticas y limitación científica explícita.
5. Diseño consistente y adaptable a móvil; iconografía, leyendas,
   jerarquía tipográfica y controles accesibles.
6. Nunca presentar diagnósticos de Sigatoka, recomendaciones agrícolas
   o comparaciones espectrales como resultados reales no validados.

La imagen rige el **orden visual, arquitectura de información y metas
funcionales** de los siguientes hitos. La apariencia pixel a pixel solo
podrá confirmarse tras revisión visual del navegador en resoluciones
de escritorio y móvil, con permisos y datos de prueba, antes de UAT
real y producción. No se cargará una captura ni datos inventados como
sustituto de esa validación.

## Matriz de estado verificable (código ≠ despliegue)

| Función de la vista objetivo | Estado del código | Verificación pendiente |
| --- | --- | --- |
| Acceso privado, selección finca/lote | Implementado en portal DBI | UAT real con usuarios/roles |
| Mapa con Google satélite opcional y RGB privado | Implementado condicionalmente a configuración | Credenciales, cobertura y UAT RGB |
| Capas GIS por lote/campaña y acciones autorizadas | Implementado por microhitos GIS | Archivos reales, estilos y revisión visual |
| Consulta de atributos del mapa | Integración previa existente | Revisión UX y UAT |
| Historial cartográfico por Campaign | Integración previa existente | UX conjunta con MULTI |
| Diez variables multiespectrales derivadas y sus fechas | Implementado PR #202–205 | Datos científicos reales aprobados |
| Historial MULTI de campañas verificadas | Este microhito | Prueba visual con datos representativos |
| Comparación estadística de vuelos | **No implementada** | Normalización y calibración compatibles, misma unidad, soporte, fórmulas y QA |
| Diagnósticos IA/tratamientos | **No automáticos** | Validación agronómica y revisión humana |
| Despliegue real, restaurabilidad y continuidad | **No acreditados** | Hito 13 / staging / UAT |

## Microhito: historial MULTI derivado de procedencia verificada

`multispectralCampaignHistory.ts` crea un catálogo de **máximo 20
extracciones autorizadas**, y únicamente incluye filas que cumplan:

- coincidencia exacta del tenant, organización, finca y lote del visor;
- `campaign_linkage = verified_job_chain` del backend;
- UUID de Campaign y extracción bien formados;
- fecha `captured_at` con zona horaria válida, normalizada UTC;
- una misma Campaign no puede exhibir fechas de captura
  contradictorias (queda completamente excluida);
- varias extracciones de la misma Campaign se agrupan, sin contar
  dos veces un mismo ID. La extracción seleccionada es la de fecha
  de registro más reciente, sin atribuirle la fecha del vuelo.

El panel muestra tarjetas accesibles de fecha/identificador abreviado
de Campaign, conteo de extracciones y selección sin escrituras.
La lista mantiene extracciones sin Campaign, pero **fuera** del
historial verificado y marcadas como no verificadas. En un lote
sin campañas verificadas, se muestra estado vacío real y no
tarjetas ficticias. El historial no crea diferencias NDVI/NDRE,
gráficos de tendencia, cambios porcentuales o alertas agronómicas.

La comprobación Node 24
`tests/multispectralCampaignHistory.test.mjs` rechaza asociaciones
sin verificación, ámbitos ajenos, fechas inválidas y capturas
contradictorias; exige agrupación, orden histórico y ausencia de
valores de comparación. Frontend ESLint/TypeScript/Vite siguen
siendo obligatorios.

## Aceptación visual futura

Antes de aceptar la vista final como equivalente a la referencia
aprobada, revisar en navegador:

- 1440 px y 1280 px: mapa como superficie dominante, herramientas
  de capas fáciles de descubrir, panel multiespectral legible y
  navegación de campañas sin desplazamiento confuso.
- 390 px y 768 px: paneles reorganizados sin solaparse con el mapa,
  controles accesibles y tablas con desplazamiento horizontal.
- Estados con 0 y varias campañas, 0 y múltiples extracciones,
  evidencia verificada/no verificada, carga, 401, 404, 409,
  ausencia de imagen RGB y permisos READ sin MANAGE.
- Inspeccionar que los indicadores `derived` siempre expongan su
  limitación; no se filtren COG, keys, fotos ni datos ajenos.
- Obtener evidencias visuales de navegador y aprobación del usuario
  antes de declarar similitud final. CI por sí solo no la acredita.

**No se modifica producción ni los cálculos científicos.**
