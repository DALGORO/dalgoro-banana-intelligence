# H14 · Evolución paralela de la interfaz del cliente (entrada al mapa)

**Objetivo**: al mismo tiempo que el inventario de dos carpetas (PR #250), facilitar la entrada del productor a sus mapas reales.

## Cambios acotados
- La página `/portal` ofrece una guía legible de tres pasos: buscar finca, abrir lote y elegir vuelo/capas. No agrega categorías ficticias ni indicadores agronómicos inventados.
- La acción por lote cambia de texto pequeño «Ver mapa» a «Abrir mapa», con un área visual de toque de al menos 44px y contraste en modos claro/oscuro.
- Indica explícitamente que únicamente se entregan mapas/resultados publicados y que el visor notificará cuando no existan evidencias.
- Conserva `filterClientPortalFarms`, scope de cuentas autorizadas, ruta original de mapas, carga asíncrona, errores y estado vacío. No cambia datos ni peticiones.
- Diseño responsivo: los tres pasos se disponen en columna en pantallas pequeñas.

## Lo que NO afirma esta UI
No confirma que hoy estén disponibles los seis mapas multiespectrales, ni que cada lote contenga imágenes, ni que Render esté actualizado. Las pruebas Node verifican estructura y contratos, no equivalen a una sesión de usabilidad en celular o cuenta real.

## Próxima evolución del cliente
Al conectar ingesta segura, preview MANAGE y aprobación institucional por campaña/capa, se activarán **solo** los switches para productos ya publicados. La pantalla cliente no mostrará carpetas, nombres técnicos de archivos, hashes ni acciones administrativas.

**Archivos**: `ClientPortal.tsx`, `dbi-client-view.css`, `tests/clientMapEntry.test.mjs`, `.github/workflows/ci.yml`. Sin migraciones, producción o cambios científicos.
