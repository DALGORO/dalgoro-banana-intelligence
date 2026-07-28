# 14 — Auditoría DBI-SEC-001

## Identificación

- Ticket: `DBI-SEC-001`
- Fecha: 2026-07-28
- Rama: `audit/DBI-SEC-001-seguridad-dependencias`
- Base revisada: `main`
- Commits históricos revisados: 2
- Archivos del commit inicial: 239

## Alcance y método

La auditoría cubre dependencias declaradas, patrones de secretos en los cambios
de los dos commits existentes, configuración sensible, logs del webhook,
archivos de respaldo y restricciones para la futura base PostgreSQL/PostGIS.

Los resultados distinguen:

- **Confirmado:** evidencia directa en texto o configuración revisada.
- **Riesgo:** condición que puede causar exposición o falta de
  reproducibilidad.
- **Pendiente:** requiere un entorno o una revisión específica adicional.

No se publican valores sensibles en este documento.

## Resultados de secretos y datos sensibles

| Resultado | Estado | Tratamiento |
|---|---|---|
| Claves privadas, tokens GitHub/AWS/Google/Stripe y JWT con formato reconocido | No detectados en los parches de los dos commits | Mantener escaneo automatizado en CI |
| URLs de base con credenciales de ejemplo | 2 coincidencias de baja severidad | Son marcadores en `.env.example` y `alembic.ini`; no son credenciales productivas |
| ID interno de Google Sheets como valor predeterminado | Confirmado | Retirado de `config.py`; se exige variable de entorno |
| Número interno como valor predeterminado | Confirmado | Retirado de `config.py`; se exige variable de entorno |
| Payload completo del webhook en stdout | Confirmado | Sustituido por tipo de evento y presencia de ID |
| Teléfono y mensaje agrupado en stdout | Confirmado | Retirados del log de infraestructura |

La ausencia de coincidencias de alto nivel no demuestra por sí sola ausencia
total de secretos. Los archivos binarios requieren una revisión separada y el
CI futuro debe incorporar un escáner especializado.

## Inventario de archivos no canónicos

Se identificaron 19 archivos que requieren resolución en `DBI-REPO-001`; no se
eliminan en este ticket.

### Copias directas

- `apps/platform-web/backend/app/api/v1/users copy.py`
- `apps/platform-web/backend/app/main copy.py`

### Volcados de revisión

- `apps/platform-web/codigos.txt`
- `apps/platform-web/sistema_completo_para_revision.txt`
- `apps/whatsapp-bot/codigos.txt`

### Respaldos o versiones anteriores del motor geoespacial

- `services/banana-density/config/cartography_antes_linea_grafica.yaml`
- `services/banana-density/config/report_antes_linea_grafica.yaml`
- `services/banana-density/config/spatial_analysis_antes_kde.yaml`
- `services/banana-density/config/spatial_analysis_antes_oportunidades.yaml`
- `services/banana-density/config/spatial_analysis_antes_priorizacion.yaml`
- `services/banana-density/config/spatial_analysis_antes_puestos_faltantes.yaml`
- `services/banana-density/config/spatial_analysis_respaldo.yaml`
- `services/banana-density/interfaz_banano_respaldo_R2.py`
- `services/banana-density/interfaz_banano_respaldo_R3.py`
- `services/banana-density/main_antes_orquestador_fase10.py`
- `services/banana-density/src/banana_analyzer/cartographic_package_antes_linea_grafica.py`
- `services/banana-density/src/banana_analyzer/cartographic_package_antes_uint8.py`
- `services/banana-density/src/banana_analyzer/pipeline_orchestrator_antes_R2_tiles.py`
- `services/banana-density/src/banana_analyzer/technical_report_antes_linea_grafica.py`

Antes de retirar cualquiera se deberá comprobar importaciones, referencias,
equivalencia funcional y archivo canónico.

## Inventario de binarios

Existen 12 archivos binarios versionados: 10 plantillas DOCX, una plantilla
XLSX y un PDF institucional. No se eliminaron porque pueden ser activos
funcionales. Su revisión de metadatos, datos personales y macros queda
pendiente antes de cerrar definitivamente la auditoría de contenido binario.

## Dependencias

### Backend FastAPI

- Las versiones están fijadas.
- Conviven `psycopg`, `psycopg-binary` y `psycopg2-binary`.
- No se retira ningún controlador hasta comprobar modelos, migraciones,
  despliegue y compatibilidad en `DBI-CI-002`.

### Bot de WhatsApp

- Las seis dependencias no tienen versión fijada.
- No se fijan arbitrariamente para evitar modificar el despliegue que funciona
  en Render.
- Antes de crear el lock se deben exportar y registrar las versiones
  efectivamente instaladas en el servicio operativo.

### Motor de densidad

- Se corrigió la concatenación entre `openpyxl` y `reportlab`.
- Se mantienen rangos existentes para OpenCV, Excel y ReportLab.
- La instalación completa requiere validar compatibilidad de PyTorch, GDAL y
  bibliotecas geoespaciales en un entorno limpio.

## Riesgo PostgreSQL/PostGIS

El backend importado continúa leyendo `DATABASE_URL`, y Alembic utiliza esa
misma configuración. Por seguridad:

- no se modificó esa conexión;
- no se ejecutó Alembic;
- no se creó ninguna base;
- no se reutilizará la base existente;
- la implementación DBI usará `DBI_DATABASE_URL`, historial independiente y
  servicios separados.

El valor de ejemplo `sst_compliance` de `alembic.ini` permanece documentado como
riesgo heredado; su sustitución corresponde al diseño controlado de
`DBI-DATA-001`, no a este ticket.

## Middleware de suscripción

`enforce_subscription_access()` permite continuar ante fallos de decodificación,
usuario ausente, suscripción ausente o excepción general. No se modifica porque
un cambio podría afectar el sistema actual. Debe resolverse mediante un ticket
específico con política explícita, pruebas de autorización y plan de
compatibilidad.

## Validaciones

| Verificación | Resultado |
|---|---|
| `python -m compileall` sobre `config.py` y `webhook.py` modificados | Aprobada |
| Aserciones de ausencia de valores internos y payload completo | Aprobadas |
| Casos de extracción de texto, texto extendido, ubicación y audio | Aprobados |
| Sintaxis de 80 dependencias del backend | Aprobada |
| Sintaxis de 6 dependencias del bot | Aprobada |
| Sintaxis de 12 dependencias del motor geoespacial | Aprobada |
| Instalación aislada del backend y `pip check` | Aprobada |
| Importaciones principales del backend | Aprobadas |
| Instalación aislada del bot y `pip check` | Aprobada |
| Importaciones declaradas del bot | Aprobadas |
| Resolución `dry-run --no-deps` del motor geoespacial | Aprobada |
| Instalación completa y `pip check` del motor geoespacial | Pendiente por tamaño y dependencias nativas |
| Frontend `npm ci` y build | Aprobados en GitHub Actions, ejecución `30403611971` |
| Compilación de los tres módulos Python en GitHub Actions | Aprobada en la ejecución `30403611971` |
| Frontend lint | Pendiente de `DBI-CI-002`; el CI actual no lo ejecuta |
| Healthcheck integrado del backend | Pendiente de entorno aislado con configuración de prueba |
| Migraciones Alembic | No ejecutadas por control de alcance |

La primera instalación del backend se interrumpió porque la caché
predeterminada de `pip` era de solo lectura. La repetición con una caché
temporal autorizada terminó correctamente; no fue un defecto de las
dependencias declaradas.

Se detectaron cinco dependencias compartidas entre módulos: `openpyxl`,
`python-dotenv`, `PyYAML`, `reportlab` y `requests`. Esta coincidencia no es un
error; se conserva hasta definir entornos y contratos independientes en
`DBI-CI-002`.

## Criterios de salida

- No desplegar esta rama en Render.
- No ejecutar migraciones con esta rama.
- Confirmar en Render que `GOOGLE_SHEET_ID` y
  `NUMERO_PERSONAL_DALGORO` existen antes de fusionar.
- Aprobar el diff y GitHub Actions antes de fusionar.
- Ejecutar `DBI-CI-002` como siguiente ticket.
