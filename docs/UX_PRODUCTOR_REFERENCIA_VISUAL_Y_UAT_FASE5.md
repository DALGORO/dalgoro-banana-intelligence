# DALGORO Banana Intelligence — Especificación visual y pruebas iniciales (Fase 5)

## Compromiso de fidelidad, sin confundir simulación con software

Las **dos imágenes de simulación aprobadas en la conversación (escritorio y teléfono)** constituyen la **referencia visual objetivo** del portal privado del productor. No son capturas del aplicativo ejecutándose, ni demuestran que las funciones o datos de la imagen estén desplegados o aprobados.

**Criterio formal de aceptación:** la primera prueba funcional debe conservar el lenguaje visual y recorrido descritos abajo, sujeto a diferencias de datos autorizados y tamaños de pantalla. La igualdad exacta píxel a píxel **no se puede prometer sin ejecutar la app, montar los PR, obtener capturas reales y confrontarlas en el mismo navegador/dispositivo**. No aprobar el diseño simplemente porque el mockup es convincente.

## Contrato visual de referencia

| Vista | Obligatorio comprobar | Verificación |
| --- | --- | --- |
| Identidad | Marca DALGORO/DBI, petróleo/cobre, textos claros, navegación adaptativa | Inspección visual + rutas reales |
| Portal productor | Búsqueda legible, listado finca/lote autorizado, acceso directo al mapa | PR #280, backend READ real |
| Visor de lote | Mapa priorizado, Campaign/fecha exacta, historial, retroceso a fincas | PR #281, GIS/tiles reales |
| Guía de capas | Secciones RGB, GIS, MULTI, distinguir disponible/seleccionado/sin mapa | PR #282, no inventar cartografía |
| Evidencia MULTI | Seis índices, mediana, P10–P90, cobertura válida, descripción neutral | PR #283, muestras autorizadas |
| Evidencia móvil | Tarjetas desplazables, «Ver todos», foco de teclado, lectura sin recortes | Fase 5, pruebas Node y revisión móvil |
| Ausencias | Mensaje claro si no hay vuelo, mapas publicados o muestra validada | API real sin datos falsos |

## Diferencias comprobadas frente a las ilustraciones

1. Las imágenes **combinan el inicio, el listado de fincas y el visor en una sola vista**. La aplicación actual los resuelve mediante rutas y componentes diferentes; no debe afirmarse que ya existe exactamente esa página unificada.
2. El mapa satelital, los polígonos, la escala gráfica, las miniaturas y el nombre/identidad del productor de las imágenes son ilustrativos. Las pruebas deben alimentarse de la cartografía autorizada y de la sesión real; puede verse el fondo neutro de contingencia.
3. Nombres «Finca La Esperanza» y «Lote Norte A», superficies como «12,4 ha», fechas y cifras NDVI/NDRE/etc. **no son registros garantizados de la cuenta**.
4. La simulación móvil utiliza un carrusel para los índices; la **Fase 5 aproxima ese comportamiento** en el componente real sin cambiar los cálculos y permite expandir todas las fichas.
5. El mockup puede sugerir que el soporte espacial de la muestra equivale a la superficie completa del lote. **La plataforma real no debe afirmar esa equivalencia**, especialmente en el caso de COPA_UP o ventana sustituta.
6. No indicar mapas temáticos multiespectrales, diagnósticos de plagas/Sigatoka, fertilización, productividad, alertas automáticas ni tratamientos si tales productos no están autorizados, validados y publicados.
7. La URL mostrada en una maqueta no es evidencia de dominio, despliegue o disponibilidad real.

## Plan de prueba visual antes de la primera aceptación

- **Escritorio:** probar a 1440 px y 1280 px, sin superposición de paneles ni recortes; verificar portal y mapa por sus rutas reales.
- **Teléfono:** probar a 390 px, 375 px y 320 px; confirmar que el mapa se puede manipular, el carrusel de los seis índices se desplaza y «Ver todos» muestra fichas completas.
- **Teclado y accesibilidad:** buscar finca, navegar al lote, elegir vuelo, abrir guía y recorrer/expandir índices; foco visible y objetivos táctiles >=44 px.
- **Datos/scope:** con y sin fincas, mapas, capas y extracciones; validar separación de tenants, ausencia de resultados científicos inventados, rechazos de P10/P90 incoherentes y estados de error.
- **Evidencia final:** guardar capturas verdaderas en navegador móvil/escritorio y confrontar con las dos imágenes conceptuales, anotando discrepancias y corrigiendo cada una antes de aprobar diseño visual.
- **Seguridad e integración:** no declarar CI general aprobada mientras Gitleaks permanezca rojo; ninguna rama UX #280–#283 ni Fase 5 se ha fusionado automáticamente.

## Implementación de Fase 5

`MultispectralEvidencePanel.tsx` añade preferencia de presentación exclusivamente local: modo carrusel móvil accesible por scroll/touch/teclado, botón «Ver todos» para vista vertical y vuelta a «Vista compacta». Mantiene **todos los índices seleccionados** en `visibleIndices`, usa `extractionForMapCampaign` sin cambios y no añade llamadas, rutas, resúmenes, alertas o cálculos.

CSS móvil y de accesibilidad extendida en `dbi-multi-readout-guide.css`. Pruebas estructurales conservadoras en `dbiClientVisualLayout.test.mjs`.

La validación automatizada de UI **no sustituye** una comparación visual en navegador. Continuar en PR borrador, sin merge, cambios productivos, migración, Render, grants S3 ni carga TIFF.
