# 16 — Limpieza del repositorio DBI-REPO-001

## Identificación

- Ticket: `DBI-REPO-001`
- Issue: #6
- Fecha: 2026-07-28
- Rama: `chore/DBI-REPO-001-limpieza-controlada`
- Base: `main` en `cad5f39e470c962dde58ab52159d51ff46af1039`
- Estado: en revisión

## Objetivo y límites

Este ticket retira copias, respaldos manuales y volcados de revisión del árbol
activo, conserva sus versiones en el historial Git y añade una barrera para que
no reaparezcan. No modifica lógica funcional, dependencias, migraciones,
servicios externos ni datos.

Los 12 binarios inventariados se preservan porque son plantillas o documentos
operativos; su inspección de contenido y metadatos requiere un ticket separado.

## Método de verificación

1. Se tomó el inventario de 239 archivos del commit base importado.
2. Se buscaron referencias literales a cada uno de los 19 nombres candidatos.
3. Se compararon rutas FastAPI, funciones Python, versiones y claves YAML con
   los archivos canónicos.
4. Se comprobó la presencia de los 12 binarios en la rama del ticket.
5. Las eliminaciones se realizaron únicamente en la rama y sin reescribir el
   historial.

La única referencia encontrada fue
`apps/platform-web/consolidar_codigo.py`, que generaba el archivo vacío
`sistema_completo_para_revision.txt`. El generador ahora escribe en
`outputs/review/`, carpeta ya excluida por `.gitignore`.

## Archivos retirados y fuente canónica

| Grupo | Archivos retirados | Fuente canónica o tratamiento |
|---|---:|---|
| Copias directas del backend | 2 | `users.py` y `main.py` |
| Volcados de revisión | 3 | No son fuente ejecutable; el volcado regenerable pasa a `outputs/review/` |
| Configuraciones históricas | 7 | `cartography.yaml`, `report.yaml` y `spatial_analysis.yaml` |
| Interfaces o ejecutables históricos | 3 | `interfaz_banano.py` y `main.py` |
| Módulos geoespaciales históricos | 4 | Módulos homónimos sin sufijo dentro de `banana_analyzer` |
| **Total** | **19** | Una sola fuente canónica por función |

### Copias directas

- `apps/platform-web/backend/app/api/v1/users copy.py`
- `apps/platform-web/backend/app/main copy.py`

El router vigente importa explícitamente `.users`. El archivo canónico de
usuarios contiene las cuatro operaciones antiguas y nueve rutas adicionales;
`app/main.py` conserva el endpoint raíz e incorpora los controles actuales.

### Volcados de revisión

- `apps/platform-web/codigos.txt`
- `apps/platform-web/sistema_completo_para_revision.txt`
- `apps/whatsapp-bot/codigos.txt`

No forman parte de la ejecución. Los dos archivos `codigos.txt` contienen notas
operativas locales y el segundo archivo estaba vacío.

### Configuraciones históricas

- `services/banana-density/config/cartography_antes_linea_grafica.yaml`
- `services/banana-density/config/report_antes_linea_grafica.yaml`
- `services/banana-density/config/spatial_analysis_antes_kde.yaml`
- `services/banana-density/config/spatial_analysis_antes_oportunidades.yaml`
- `services/banana-density/config/spatial_analysis_antes_priorizacion.yaml`
- `services/banana-density/config/spatial_analysis_antes_puestos_faltantes.yaml`
- `services/banana-density/config/spatial_analysis_respaldo.yaml`

Las fuentes vigentes son `cartography.yaml` versión 2, `report.yaml` versión 2
y `spatial_analysis.yaml` versión 6. Las claves históricas de cartografía y
análisis espacial están contenidas en las versiones actuales. Reportes trasladó
los colores y activos a la estructura `report.branding` y añadió contenido
explicativo versionado.

### Código histórico del motor geoespacial

- `services/banana-density/interfaz_banano_respaldo_R2.py`
- `services/banana-density/interfaz_banano_respaldo_R3.py`
- `services/banana-density/main_antes_orquestador_fase10.py`
- `services/banana-density/src/banana_analyzer/cartographic_package_antes_linea_grafica.py`
- `services/banana-density/src/banana_analyzer/cartographic_package_antes_uint8.py`
- `services/banana-density/src/banana_analyzer/pipeline_orchestrator_antes_R2_tiles.py`
- `services/banana-density/src/banana_analyzer/technical_report_antes_linea_grafica.py`

Todos los nombres de funciones de las versiones históricas existen en el módulo
canónico correspondiente. Las versiones actuales agregan controles de
reanudación, manejo de teselas, identidad gráfica y estructura del informe.

## Activos binarios preservados

Se mantienen exactamente estos 12 archivos:

- `apps/platform-web/backend/app/static/templates/BANANERA/ACTA-APR-RHS-01.docx`
- `apps/platform-web/backend/app/static/templates/BANANERA/AGRO-PLAG-01.docx`
- `apps/platform-web/backend/app/static/templates/BANANERA/CAP-01.docx`
- `apps/platform-web/backend/app/static/templates/BANANERA/EMG-01.docx`
- `apps/platform-web/backend/app/static/templates/BANANERA/EPP-01.docx`
- `apps/platform-web/backend/app/static/templates/BANANERA/IPERC-01.xlsx`
- `apps/platform-web/backend/app/static/templates/BANANERA/ORG-COM-01.docx`
- `apps/platform-web/backend/app/static/templates/BANANERA/ORG-DEL-01.docx`
- `apps/platform-web/backend/app/static/templates/BANANERA/PPRL-01.docx`
- `apps/platform-web/backend/app/static/templates/BANANERA/PSICO-01.docx`
- `apps/platform-web/backend/app/static/templates/BANANERA/RHS-01.docx`
- `apps/whatsapp-bot/documentos/SERVICIOS_DALGORO_SAS.pdf`

El validador de higiene falla si alguno deja de estar versionado sin que se
actualice de forma explícita la decisión técnica.

## Control preventivo

`.github/scripts/ci_repository_hygiene.py` consulta `git ls-files` y rechaza:

- ` copy.py`;
- marcadores `_antes_` y `_respaldo`;
- `codigos.txt` y `sistema_completo_para_revision.txt`;
- archivos `.bak`, `.backup`, `.zip`, `.7z` y `.rar`;
- directorios de salida, caché, ejecución o dependencias.

El trabajo `repository-hygiene` se añade a `.github/workflows/ci.yml` y la rama
`chore/**` queda incluida en los disparadores de CI.

## Validaciones

| Verificación | Resultado |
|---|---|
| Inventario de 19 candidatos | Aprobado |
| Referencias a nombres no canónicos | Una referencia controlada en el generador; corregida |
| Comparación de rutas, funciones y claves | Aprobada |
| Presencia de 12 binarios | Aprobada |
| Compilación de los dos scripts | Aprobada |
| Validador con árbol limpio | Aprobada |
| Validador con cuatro patrones prohibidos | Aprobada; cuatro rechazos |
| Generación en `outputs/review/` | Aprobada |
| GitHub Actions completa | Pendiente del Draft PR |

Ninguna prueba pendiente se declara aprobada.

## Recuperación

Los archivos retirados continúan disponibles en el commit base y en el historial
de Git. Este ticket no usa limpieza de historial, rebase destructivo ni
eliminación de objetos remotos.

## Exclusiones confirmadas

- No se modifican Render, PostgreSQL, Green API ni Google Sheets.
- No se ejecuta Alembic.
- No se modifica la lógica conversacional.
- No se procesan ortofotos ni se descargan modelos.
- No se actualizan modelos de IA.
