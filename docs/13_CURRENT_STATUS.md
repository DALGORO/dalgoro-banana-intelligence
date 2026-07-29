# 13 — Estado actual

## Versión
0.1.3-repo-hygiene

## Terminado
- Estructura inicial del monorepositorio.
- Importación limpia de los tres sistemas.
- Exclusión inicial de secretos y archivos generados.
- Documentos maestros iniciales.
- CI básica.
- `DBI-SEC-001`: auditoría de secretos, dependencias y estructura importada.
- `DBI-CI-002`: integración continua modular y verificable.

## Último ticket completado
`DBI-CI-002` — Integración continua real e independiente por módulo.

### Resultado implementado
- Cinco trabajos independientes: frontend, backend, bot, densidad y secretos.
- Instalación y verificación de dependencias por módulo.
- Smoke tests sin servicios externos ni bases productivas.
- Línea base de lint que impide aumentar los 115 avisos heredados.
- Auditorías visibles de secretos y dependencias.

### Validación ejecutada
- Frontend `npm ci`: aprobado con caché temporal autorizada.
- Frontend lint: 0 errores y 115 avisos con la línea base propuesta.
- Frontend build: aprobado con Node 24.
- Backend: instalación aislada, `pip check`, `compileall` y healthcheck
  aprobados.
- Alembic: el grafo se interpreta, pero existen tres cabezas heredadas que
  deberán resolverse antes de crear migraciones DBI.
- Bot: instalación aislada, `pip check`, `compileall` y endpoint Flask con
  Sheets simulado aprobados.
- Auditoría npm: ejecutada; mantiene hallazgos heredados sin declarar
  resolución.
- Sintaxis de los tres smoke tests y parseo del workflow: aprobados.
- GitHub Actions `30407127911`: los cinco trabajos aprobaron.
- GitHub Actions técnica previa al cierre documental `30407408901`: los cinco
  trabajos aprobaron.
- Motor geoespacial: instalación completa, `pip check`, `compileall`,
  importaciones y CLI aprobados en un entorno limpio.
- Gitleaks: historial completo analizado sin secretos detectados.
- Auditorías informativas: frontend 5 vulnerabilidades de producción; backend
  81 hallazgos en 19 paquetes; bot 2 en 1 paquete; densidad 3 en 2 paquetes.
  Ningún hallazgo se declara corregido en este ticket.

## Ticket actual
`DBI-REPO-001` — Limpieza controlada de copias, respaldos y artefactos.

### Resultado implementado en la rama
- Retiro de 19 archivos no canónicos previamente inventariados.
- Conservación verificada de 10 plantillas DOCX, una plantilla XLSX y un PDF
  institucional.
- Salida de `consolidar_codigo.py` aislada en `outputs/review/`.
- Nuevo control CI basado en archivos realmente versionados.
- Sexto trabajo independiente de GitHub Actions para higiene del repositorio.

### Validación ejecutada
- Revisión de referencias sobre los 239 archivos del commit base: ninguna copia
  activa; solo el generador referenciaba el volcado regenerable de 1.025.782 líneas.
- Comparación de funciones, rutas y claves con los archivos canónicos: las
  versiones vigentes conservan o amplían el comportamiento requerido.
- Compilación local de los dos scripts modificados: aprobada.
- Caso limpio y cuatro casos prohibidos del validador: aprobados.
- Generación local dentro de `outputs/review/`: aprobada.
- Diff técnico previo a documentación: 19 eliminaciones, un archivo añadido y
  dos archivos modificados.
- GitHub Actions del Draft PR: pendiente de ejecución.

## Próximo paso
Completar GitHub Actions, revisar el Draft PR de `DBI-REPO-001` y fusionar
únicamente con autorización del propietario.
## No realizado todavía
- No se ha fusionado código entre módulos.
- No existe todavía una base PostgreSQL/PostGIS unificada.
- No se ha creado ni modificado ninguna base DBI.
- No se han ejecutado migraciones.
- No existe todavía el dashboard agrícola.
- No existe todavía el mapa cronológico.
- No se han cambiado Green API, Google Sheets ni la configuración de Render.
- No se ha cambiado la lógica conversacional del bot.
- No se han actualizado modelos de IA.
