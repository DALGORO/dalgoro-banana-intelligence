# H13 · Portal cliente con mapa como pantalla principal

## Implementado en React

El recorrido principal del productor mantiene los recursos autorizados de `/portal` y del visor privado por finca/lote, pero reorganiza la vista:

1. Navegación lateral: Mis fincas → Ver mapa → Levantamientos → Capas → Inspecciones → Resultados del vuelo. Las pestañas INSPECT y MULTI se activan en el visor existente; ninguna nueva ruta de escritura.
2. Cabecera de finca/lote e indicador de **cantidad real** de fotografías RGB y capas GIS que se dibujan.
3. Mapa grande con base satelital **solo si Google Maps está configurado**; sin clave, fondo neutro honesto y cartografía real publicada, sin fabricar fotografías.
4. Leyenda derivada exclusivamente de RGB/GIS efectivamente visibles; sin NDVI/NDRE cartográfico falso, ni porcentajes de cobertura, mapas de salud, zonas rojas inventadas.
5. Historial scroll horizontal de levantamientos con geometría/RGB disponibles, fecha real y nombre; Anterior/Siguiente actualizan fecha **y Campaign exacta**. Incluye campañas GIS sin RGB y preserva vuelos distintos del mismo instante.
6. Al abrir el lote y mientras no haya elección manual, la interfaz ofrece el levantamiento cartográfico más reciente que haya recibido del servidor (RGB o GIS). La elección manual no se sobrescribe cuando terminan peticiones posteriores.
7. La fecha vacía no mezcla capas de varios levantamientos; si una fecha incluye varias Campaign y no hay una identidad exacta elegida, el mapa pide seleccionar una Campaign.
8. Panel derecho empieza en «Qué estás viendo» (datos del lote); índices y muestras son una segunda pestaña.
9. En celular/tableta estrecha, mapa → línea temporal → panel informativo → controles secundarios. En escritorio ancho: controles | mapa | panel, con la línea temporal debajo del mapa.
10. La procedencia de RGB se presenta como «revisión profesional aprobada» o «imagen disponible, análisis no necesariamente aprobado»; las capas GIS no afirman que todo el vuelo esté aprobado.

## No implementado / no presentar como terminado

- Mapas de NDVI/NDRE georreferenciados, semáforos de vigor/enfermedad y mapas comparativos de dos fechas: aún necesitan productos/algoritmos y validación científica explícita. El selector «comparar» explica que todavía está en desarrollo.
- No hay datos de demostración, heurísticas sanitarias ni nueva capa GIS; no se alteran YOLO, COPA_UP, PostGIS, autorizaciones o INSPECT.
- No implica despliegue a Render, activación de roles institucionales ni migración de producción.

## Pruebas y validación esperadas

- `frontend/tests/producerMapVisits.test.mjs`: une RGB y capas GIS solo por `campaign_id`, desambigua dos vuelos con idéntica fecha, excluye campañas sin capas e inconsistencias de identidad.
- `frontend/tests/dbiClientVisualLayout.test.mjs`: comprueba mapa antes del historial y ficha, navegación responsive, selección exacta y ausencia de métricas simuladas.
- CI debe aprobar lint, build, regresión web, PWA, backend y PostGIS.

**UAT pendiente:** comprobar renders reales en navegador móvil, tablet y escritorio y el origen real de ortofotos y capas con cuenta cliente autorizada. El CI verde no certifica esa validación visual ni indica que el servidor productivo haya recibido el commit.
