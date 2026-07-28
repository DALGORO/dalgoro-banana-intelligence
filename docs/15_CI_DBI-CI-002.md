# 15 — Integración continua DBI-CI-002

## Identificación

- Ticket: `DBI-CI-002`
- Issue: `#4`
- Pull request: `#5`
- Fecha de inicio: 2026-07-28
- Rama: `ci/DBI-CI-002-integracion-continua-modular`
- Base: `main` en `dfed279a47f5459255b36688f415a2c87e5aca3f`
- Ejecución técnica verificada antes del cierre: `30407408901`

## Objetivo

Comprobar de forma independiente que cada módulo puede instalarse, compilarse e
importarse sin desplegar servicios, conectarse a bases de datos o llamar a
integraciones operativas.

## Diseño del workflow

| Trabajo | Instalación | Validación funcional mínima |
|---|---|---|
| Frontend | `npm ci` | lint con línea base y build |
| Backend | `pip install -r requirements.txt` | `pip check`, `compileall`, grafo Alembic y healthcheck |
| WhatsApp | `pip install -r requirements.txt` | `pip check`, `compileall` y endpoint Flask con Sheets simulado |
| Densidad | `pip install -r requirements.txt` | `pip check`, `compileall`, importaciones y CLI |
| Secretos | historial Git completo | Gitleaks sin comentarios ni permisos de escritura |

Las acciones externas están fijadas a SHA completos. El workflow no utiliza
`pull_request_target`, credenciales operativas ni secretos de Render.
El token de GitHub solo dispone de `contents: read` y `pull-requests: read`;
Gitleaks tiene desactivados los comentarios automáticos.

## Aislamiento de las pruebas

### Backend

- Se fuerza `sqlite+pysqlite:///:memory:` antes de importar la aplicación.
- Se usa un valor local no operativo para la configuración JWT obligatoria.
- Solo se consulta `/api/v1/health` y el endpoint raíz.
- `alembic heads` valida el grafo; no ejecuta `upgrade`, `downgrade` ni conexión.

### Bot de WhatsApp

- Se instala un módulo simulado de `google_sheets_utils` antes de importar
  `webhook.py`.
- Se desactivan notificaciones y envío de PDF.
- Los identificadores de Green API y Sheets son marcadores locales.
- Solo se consulta el endpoint Flask `/`; no se envían mensajes.

### Motor geoespacial

- Se usa backend gráfico no interactivo.
- Se importan las bibliotecas directas utilizadas por el código.
- Se construye el parser del CLI y se comprueba una ruta inexistente.
- No se ejecuta `system-check`, no se escribe un informe, no se descarga un
  modelo y no se procesa una ortofoto.

## Línea base de lint

La ejecución original de `npm run lint` produjo 118 errores y 6 advertencias.
Corregirlos dentro de este ticket requeriría modificar numerosas pantallas y
ampliaría el riesgo funcional.

La configuración propuesta conserva como advertencias la deuda heredada y
mantiene como errores las reglas no exceptuadas. El resultado local es:

```text
0 errores
115 advertencias
```

El CI ejecuta `npm run lint -- --max-warnings 115`. Una advertencia adicional
hará fallar el trabajo. La reducción progresiva de la línea base deberá ocurrir
en tickets específicos y nunca podrá incrementarse silenciosamente.

## Auditorías de dependencias

Las auditorías se ejecutan después de las pruebas funcionales y son
informativas en este ticket. No se usa corrección automática.

La ejecución local de `npm audit --audit-level=high --omit=dev` del
2026-07-28 informó:

- 5 vulnerabilidades de producción.
- 4 de severidad alta.
- 1 de severidad moderada.
- Parte de los hallazgos indicó que no existía una versión corregida disponible.

La ejecución remota `30407127911` añadió este inventario:

| Módulo | Resultado informativo |
|---|---|
| Frontend | 5 vulnerabilidades de producción: 4 altas y 1 moderada |
| Backend | 81 vulnerabilidades conocidas en 19 paquetes |
| WhatsApp | 2 vulnerabilidades conocidas en 1 paquete |
| Densidad | 3 vulnerabilidades conocidas en 2 paquetes |

Estos resultados no se consideran resueltos. Las auditorías son visibles y no
bloquean el ticket para evitar actualizaciones funcionales o masivas sin una
evaluación independiente.

## Validaciones locales

| Verificación | Resultado |
|---|---|
| `npm ci` con caché temporal autorizada | Aprobada |
| `npm run lint -- --max-warnings 115` | Aprobada, 0 errores y 115 avisos |
| `npm run build` con Node 24 | Aprobada |
| `npm audit --audit-level=high --omit=dev` | Ejecutada; hallazgos documentados |
| Compilación de los tres smoke tests | Aprobada |
| Parseo del workflow YAML y cinco trabajos esperados | Aprobado |
| Backend: instalación aislada y `pip check` | Aprobados |
| Backend: `compileall`, importación y healthcheck | Aprobados |
| Bot: instalación aislada y `pip check` | Aprobados |
| Bot: `compileall`, importación y endpoint local | Aprobados |
| Motor geoespacial: instalación, `pip check`, compilación, importaciones y CLI | Aprobados en GitHub Actions |
| GitHub Actions del ticket, ejecución `30407127911` | Aprobada: 5 de 5 trabajos |
| Gitleaks sobre historial completo | Aprobado, sin secretos detectados |

`alembic heads` terminó correctamente y mostró tres cabezas heredadas:
`20260411_01`, `2cec060d9aa4` y `7ce73aae44ce`. El CI valida que los scripts sean
interpretables, pero no oculta esta ramificación ni ejecuta migraciones. Su
resolución debe diseñarse antes de crear el historial DBI independiente.

La primera ejecución del PR (`30407020105`) reveló que Gitleaks no podía leer
los metadatos del pull request con `contents: read` únicamente. El trabajo no
había reportado un secreto: falló con `Resource not accessible by integration`.
Se añadió el permiso mínimo `pull-requests: read`, se mantuvieron desactivados
los comentarios y la repetición completa `30407127911` aprobó.

## Exclusiones confirmadas

- Render no se consulta ni modifica.
- PostgreSQL no se consulta ni modifica.
- Alembic no ejecuta migraciones.
- Green API y Google Sheets no reciben llamadas.
- El flujo conversacional no cambia.
- No se procesan datos agrícolas.
- No se actualizan modelos de IA.

## Cierre

- Implementación limitada a los ocho archivos declarados.
- Ejecución técnica previa al cierre `30407408901`: cinco de cinco trabajos
  aprobados.
- Sin comentarios, revisiones solicitando cambios ni hilos pendientes en el PR.
- Fusión mediante `squash` autorizada el 2026-07-28.
- Los riesgos heredados de Alembic, lint y dependencias permanecen documentados;
  no se declaran corregidos por este ticket.
- No se realizaron despliegues ni cambios en Render, PostgreSQL, Green API o
  Google Sheets.
