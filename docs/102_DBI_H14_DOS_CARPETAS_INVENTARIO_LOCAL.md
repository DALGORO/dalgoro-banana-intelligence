# H14 / Etapa 1 — Selección local de dos carpetas en gestión del lote

**Base auditada:** `main@797b604`.

## Alcance implementado
En la sección privada «Gestionar y publicar capas GIS» del visor de finca/lote para usuarios con permiso `MANAGE` se integra `AdminAnalysisFolderPanel.tsx`. Permite seleccionar:
- **Carpeta 1**: análisis geoespacial (ortofoto RGB candidata, GeoPackage, ZIP GIS, GeoJSON, PDF y archivos auxiliares);
- **Carpeta 2**: análisis multiespectral (exactamente seis índices `ndvi`, `ndre`, `gndvi`, `evi2`, `ci_red_edge`, `ci_green`, cada uno con candidato TIFF y QML).

El explorador nativo de escritorio (`webkitdirectory`) selecciona directorios enteros. El inventario se construye exclusivamente a partir de `File.name`, `File.size` y `File.webkitRelativePath`, sin llamar a `FileReader`, `arrayBuffer`, API HTTP ni Storage. No se conservan los `File` para carga posterior: **no se envían bytes, se valida contenido ni se registra aprobación**. Se descartan rutas sin semántica relativa segura, se marcan duplicados de ruta, nombres de índice ambiguos, múltiples candidatos y pares faltantes. Límite de visualización/inventario de 1.500 archivos y de 40 rutas expuestas en el resumen por carpeta.

Solo son **candidatos inferidos por nombre y extensión**. Un GeoPackage puede contener múltiples capas: no se elige una por el nombre exterior. El motor de validación científica del PR #249 sigue disponible únicamente en CLI aislado. Los QML históricos no están versionados: no afirmar que se recuperaron.

## Acceso y compatibilidad
- La nueva pantalla está dentro de `{canPublish && realLocator}`, que exige `MANAGE` y scope de tenant/organización/finca/lote; no aparece en `/portal` para usuario solo `READ`.
- `MANAGE` **no equivale** a la acreditación del único administrador institucional DALGORO que autoriza `APPROVED/PUBLISHED`. Este paso prepara inventario, sin autorización de publicación.
- La selección de carpetas depende del soporte del atributo `webkitdirectory` del navegador. Si el navegador no ofrece rutas relativas, el inventario lo advierte; no puede garantizarse funcionalidad en todos los móviles.
- Al cambiar de finca/lote, la clave `gisScopeKey` remonta el componente y borra el inventario para evitar mostrar nombres de otro contexto.
- Nada se conserva al cerrar la vista o actualizar la página. No hay reanudación, carga masiva ni procesamiento en servidor en este PR.
- Los archivos `.shp/.shx/.dbf/.prj` sueltos se consideran componentes y no se envían solos. COG georreferenciado, NoData, CRS, fórmula y estilo QML requieren lectura de bytes y validación posterior.

## Siguiente hito (Etapa 2)
Definir un manifiesto versionado y firmado por alcance/campaña con subida privada multipart de lotes de archivos, detección de contenidos en el worker aislado, validación de tipo MIME/ZIP/COG/QML, controles de coste/cuota, reintentos y bitácora de identidad. Nada debe llegar al cliente antes de previsualización MANAGE + aprobación institucional DALGORO, sin permitir que un GeoJSON se publique directamente en el nuevo asistente.

La UI cliente evoluciona en una mejora separada y conservadora, sin inventar disponibilidad de capas.

## Pruebas
`node --test tests/analysisFolderInventory.test.mjs` dentro del job de frontend, además de lint y build. Incluye pares de seis índices, NDVI vs GNDVI, carpetas anidadas, ambigüedad, duplicados, TIFF sin clase confirmada, selección grande y ausencia de envío público.
