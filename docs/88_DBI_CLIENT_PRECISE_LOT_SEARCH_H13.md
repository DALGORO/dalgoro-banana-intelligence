# DBI-CLIENT-UX-002 — Buscar fincas y lotes sin mostrar resultados ajenos

## Problema corregido

La portada autorizada `/portal` ya permitía buscar por finca/lote, pero
en la búsqueda de un lote mostraba **todos** los lotes de su finca,
aunque muchos no coincidieran con el texto. Esto también hacía que el
indicador de lotes fuera menos útil.

## Comportamiento de la interfaz

- Si el texto coincide con el nombre/código de una finca, aparecen
  **todos los lotes autorizados** dentro de esa finca.
- Si coincide solo con uno o varios lotes por nombre/código,
  aparecen **únicamente esos lotes** bajo su finca respectiva.
- Sin búsqueda se conservan incluso fincas con cero lotes.
- La búsqueda ignora diferencias entre tildes, mayúsculas y espacios.
- Un botón `Limpiar búsqueda` restaura todos los elementos recibidos
  del catálogo del usuario (también en el estado de sin resultados).
- Los contadores de fincas y lotes se derivan exactamente de los
  elementos visibles, sin ninguna estadística inferida.
- Los enlaces siguen usando `tenant_ref`, `organization_ref`, ID
  de finca e ID de lote de la respuesta del servidor.

## Privacidad y pruebas

El helper puro `src/features/clientPortalSearch.ts` **solo filtra
el catálogo ya autorizado** por `GET /api/v1/dbi/portal/accounts`.
No consulta nuevos recursos, no cachea registros, no aumenta permisos
ni genera campañas o datos científicos.

`tests/clientPortalSearch.test.mjs` verifica tildes, coincidencia de
finca/lote, cuentas separadas, lotes vacíos, contadores y ausencia
de resultados inventados. Se ejecuta en el job frontend junto a lint,
la compilación y el contrato visual existente.

No se cambian rutas API, backend, producción, mapas GIS, INSPECT o ML.
La verificación visual con navegador en dispositivos reales sigue
pendiente y no se sustituye por estas pruebas automatizadas.
