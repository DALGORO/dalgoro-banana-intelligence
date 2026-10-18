# H14 / Etapa 2C — Comprobar archivos REALES a partir del borrador de dos carpetas

El PR #254 incorporó la preparación local de **1 ortofoto RGB + 6 COG de índices + 6 QML**. El borrador es **metadatos por nombre**, sin lectura científica.

Este hito añade una utilidad **offline en `services/banana-density/`** que toma aquel JSON y las dos carpetas de originales, vuelve a leer los trece archivos reales y produce un expediente de prevalidación técnica. No añade HTTP, no sube archivos, no toca ni edita fuentes, no realiza migraciones ni despliegue.

## Uso en equipo científico/worker local

1. Abrir el lote y seleccionar las carpetas geoespacial y multiespectral desde la sección de gestión autorizada.
2. Elegir Campaign técnica real y exportar **«borrador JSON local (sin subir archivos)»**. Si faltan pares no se habilita el botón.
3. **Solo en el equipo que tenga físicamente los trece archivos originales** y Python/Rasterio configurados, ejecutar:

```bash
python services/banana-density/scientific_draft_preflight.py \
  --draft "/ruta/borrador.json" \
  --geospatial-root "/datos/LEVANTAMIENTO/GEO" \
  --multispectral-root "/datos/LEVANTAMIENTO/MULTI" \
  --stack-fingerprint-claimed "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" \
  --output "/expedientes/evidencia.json"
```

El fingerprint del ejemplo es **sintético**. En un caso real debe suministrarse la huella efectivamente declarada del stack de bandas del vuelo, y continuará marcada como **no cotejada con base de datos**.

No se permite sobrescribir el expediente existente ni escribir dentro de los directorios originales. Sin `--output`, se emite JSON por stdout.

## Rechazos automáticos

- Borrador con `published`, `institutional_approved`, `scientific_validated` o `server_received` cambiado a `true`, huellas falsamente precargadas, campos adicionales, roles duplicados o falta de cualquiera de los 13 archivos.
- Scope o Campaign sintácticamente inválidos (pero un UUID válido **no prueba pertenencia real**).
- Carpeta física distinta de la declarada, rutas `..`, directorios o archivos mediante symlink, extensiones incorrectas, duplicados y bytes con tamaños que ya no concuerdan.
- Ortófóto RGB no georreferenciada o que no sea un GeoTIFF uint8/uint16 de 3/4 bandas, o que no se superponga geográficamente con la grilla multiespectral. **Eso todavía no garantiza que las primeras tres bandas sean efectivamente RGB ni certifica precisión RTK/GCP.**
- Los seis TIFF científicos no pasan el control anterior del PR #249: exige Float32 COG real, CRS, NoData, grilla idéntica, píxeles válidos finitos, compresión sin pérdida; los QML originales deben ser XML QGIS pseudocolor de banda 1, con rampa válida.

Se calculan SHA-256 reales de los 13 originales leídos, conservando los originales intactos.

## Evidencias que SIEMPRE permanecen sin aprobación

```json
{
  "disposition": "offline_technical_evidence_only_not_published",
  "campaign_link_verified": false,
  "source_provenance_verified": false,
  "rgb_semantic_bands_verified": false,
  "institutional_publication_authorized": false
}
```

La validación del archivo no enlaza el Campaign declarado a PostGIS ni confirma reflectancia/calibración de bandas. El expediente anidado `index_map_preflight` también preserva sus banderas `false`.

**Esto no habilita en ningún caso la vista del cliente.** Antes de utilizar los resultados comercialmente falta la recepción segura de originales mediante API con identificadores persistidos y hash de servidor, el cotejo de campaña y procedencia, la aprobación por índice, la vista previa privada del administrador, y solo entonces la publicación scoped READ.

## Pruebas y limitaciones

CI sintetiza deliberadamente una ortofoto RGB y seis COG/QML GeoTIFF reales temporales, valida lectura y huellas, y rechaza borrador manipulado, hash falso, symlink, path traversal, tamaño alterado, Campaign inválida, RGB ajena, archivo faltante, salida sobrescrita. Son **datos sintéticos de laboratorio**, no vuelos reales ni estilos QML históricos.

El validador es offline. Las dos carpetas deben estar presentes en un entorno de ejecución y solo tras verificación de autorización de acceso al filesystem; no debe exponerse como endpoint arbitrario que acepte rutas del usuario. Las fuentes pueden cambiar entre lectura/uso si el sistema externo no congela una instantánea: para producción será obligatoria la cuarentena privada e inmutabilidad con hashes confirmados por el servidor.

**Archivos nuevos:** `banana_analyzer/scientific_reception_draft_preflight.py`, `scientific_draft_preflight.py`, `.github/scripts/ci_dbi_scientific_draft_preflight.py`; cambio limitado a workflow de integración científica.

**Siguiente paso:** diseñar persistencia e ingesta privada por archivo COG/QML, con byte-range/multipart cuando proceda y vínculos verificables a Campaign. Sin migración hasta auditoría y CI de esquema.
