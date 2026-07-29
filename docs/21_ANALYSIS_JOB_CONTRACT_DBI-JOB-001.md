# 21 — Contrato de trabajo geoespacial DBI-JOB-001

## Identificación

- Ticket: `DBI-JOB-001`
- Issue: #16
- Fecha: 2026-07-29
- Rama: `feat/DBI-JOB-001-contratos-trabajos-v1`
- Base: `main` en `b70889179baa031f48124b369fe393a702cbfd81`
- Pull request: pendiente
- Estado: en implementación

## Objetivo

Implementar la primera frontera ejecutable y versionada entre la API central y
el futuro worker geoespacial sin crear todavía cola, almacenamiento de objetos,
persistencia operativa o ejecución del pipeline.

El corte convierte los ejemplos conceptuales de `DBI-ARC-001` en contratos
estrictos y una máquina de estados pura. No convierte esos contratos en
endpoints, mensajes publicados o resultados reales.

## Evidencia revisada

La revisión de `main` confirmó:

- el dominio agrícola DBI ya modela finca, lote y campaña;
- el backend no dispone todavía de motor, sesión o repositorio DBI;
- el mapa cronológico permanece vacío y no consulta persistencia;
- el pipeline geoespacial contiene 17 etapas y recibe rutas locales;
- FastAPI no debe importar PyTorch, GDAL o el orquestador;
- el worker futuro debe recibir referencias autorizadas, no rutas locales;
- el estado global del trabajo es distinto del estado interno de las etapas;
- los reintentos deben conservar intentos y artefactos previos;
- los hallazgos deben distinguir clasificación, confianza y revisión
  profesional.

No se consultaron PostgreSQL, Render, Green API, Google Sheets, almacenamiento
de objetos o servicios de mensajería.

## Contratos implementados

### Comando de análisis

`analysis-job-command.v1` contiene:

- `request_id` para idempotencia;
- `correlation_id` para trazabilidad;
- identificadores internos de trabajo, tenant, finca y lote;
- referencias opacas de ortofoto, límite y exclusiones;
- versión aprobada de modelo;
- versión de configuración del pipeline;
- actor solicitante.

Todos los identificadores usan referencias internas de hasta 128 caracteres.
El contrato rechaza campos desconocidos, URLs, separadores de ruta y
credenciales embebidas.

### Manifiesto de artefacto

`artifact-manifest.v1` exige:

- identificador de artefacto y trabajo;
- rol canónico;
- clave relativa de objeto;
- tipo de contenido;
- tamaño positivo;
- huella SHA-256 en minúsculas;
- una de las 17 etapas actuales;
- CRS opcional;
- fecha consciente de zona horaria.

La clave de objeto no puede ser una URL, ruta absoluta, ruta de Windows o
contener segmentos `.` o `..`.

### Resultado de trabajo

`analysis-job-result.v1` representa únicamente resultados terminales:
`succeeded`, `failed` o `canceled`. Conserva intento, build del pipeline, fechas,
artefactos, métricas, hallazgos, advertencias y errores.

Cada hallazgo usa `agronomic-finding.v1` y conserva:

- clasificación `observed`, `inference`, `hypothesis` o `recommendation`;
- declaración técnica;
- artefactos y fuentes técnicas;
- versión del modelo;
- nivel, puntaje opcional y método de confianza;
- estado, actor y fecha de revisión profesional.

Una decisión profesional aprobada o rechazada exige revisor y fecha. Un estado
pendiente o no requerido no puede declarar esos datos.

## Máquina de estados

La función `evaluate_analysis_job_transition()` aplica:

```text
accepted → queued → running → succeeded
                            ↘ failed
queued/running → cancel_requested → canceled
failed → queued  (solo con retry_authorized=True)
```

Repetir el mismo estado devuelve un no-op idempotente. `succeeded` y `canceled`
son terminales y no pueden reabrirse.

Esta función no escribe en base, no publica mensajes y no registra auditoría.
Esas responsabilidades corresponden a tickets posteriores.

## Adaptador del worker

`worker_contract.py` usa únicamente la biblioteca estándar. Valida los campos
exactos y normaliza el comando en dataclasses inmutables.

El adaptador no:

- importa módulos del backend;
- importa `pipeline_orchestrator`;
- invoca `run_full_pipeline`;
- usa `subprocess`;
- abre archivos;
- crea directorios;
- resuelve activos a rutas locales.

La resolución autorizada de activos, el espacio temporal y la ejecución del
pipeline requieren almacenamiento y orquestación reales en tickets
posteriores.

## Implementación por archivo

### Backend

- `app/schemas/dbi_analysis_jobs.py`: comando, resultado, manifiesto y hallazgo.
- `app/dbi/jobs/state_machine.py`: estados, transiciones e idempotencia.
- `app/dbi/jobs/__init__.py`: exportación explícita de las reglas.

### Worker

- `services/banana-density/src/banana_analyzer/worker_contract.py`: validación
  pura del comando v1.

### Integración continua

- `.github/scripts/ci_analysis_job_contract.py`: paridad de contratos,
  manifiestos, 17 etapas, estados y aislamiento.
- `.github/workflows/ci.yml`: ejecución del control en el trabajo backend.

### Documentación

- `docs/01_SYSTEM_ARCHITECTURE.md`: frontera implementada y secuencia.
- `docs/06_TECHNICAL_DECISIONS.md`: `DEC-017`.
- `docs/13_CURRENT_STATUS.md`: estado del ticket.
- `docs/21_ANALYSIS_JOB_CONTRACT_DBI-JOB-001.md`: evidencia técnica.

## Validaciones locales ejecutadas

| Verificación | Resultado |
| --- | --- |
| Compilación Python | Aprobada |
| Comando Pydantic estricto | Aprobado |
| Paridad del adaptador estándar | Aprobada |
| Campos adicionales | Rechazados por ambos componentes |
| URL y ruta local de activo | Rechazadas por ambos componentes |
| Manifiesto con tamaño cero | Rechazado |
| Manifiesto con SHA-256 inválida | Rechazado |
| Clave de objeto local o URL | Rechazada |
| Etapas del contrato frente al pipeline | 17 de 17 |
| Transiciones válidas | Aprobadas |
| Reapertura de estado terminal | Rechazada |
| Reintento sin autorización | Rechazado |
| Reintento autorizado | Aprobado |
| Ejecución de pipeline | Cero |
| Conexiones externas | Cero |

## Criterios de aceptación

| Criterio | Evidencia |
| --- | --- |
| Tres contratos versionados | Constantes y literales Pydantic |
| Campos estrictos | `extra="forbid"` y adaptador exacto |
| Referencias opacas | Patrón compartido y casos negativos |
| Worker independiente | Biblioteca estándar sin importación del backend |
| Pipeline no ejecutado | Barrera de fuentes y prueba en memoria |
| Estados controlados | Matriz de transiciones pura |
| Reintento autorizado | `retry_authorized=True` obligatorio |
| Artefactos verificables | Tamaño, SHA-256, rol, etapa y objeto |
| CI completa | Pendiente de ejecución remota |
| Estado documentado | Documentos 01, 06, 13 y 21 |

## Naturaleza de los datos

Este ticket define estructura y reglas, no evidencia agronómica:

- dato observado: ninguno;
- inferencia: ninguna;
- hipótesis: ninguna;
- recomendación: ninguna;
- confianza: no aplica;
- aprobación profesional: no aplica.

Los textos usados por las pruebas son marcadores estructurales y no describen
una finca, cultivo, ortofoto, modelo o resultado real.

## Riesgos residuales

- No existe persistencia de trabajos, intentos, activos o artefactos.
- No existe idempotencia respaldada por una restricción de base.
- No existe autorización por tenant, finca o lote.
- No existe cola, broker, productor o consumidor.
- No existe almacenamiento privado ni resolución de activos.
- No existe espacio temporal administrado para el worker.
- No existe adaptador que genere la configuración local del pipeline.
- No existe endpoint para crear o consultar trabajos.
- No existe auditoría operativa de transiciones.
- El mapa cronológico continúa vacío.

## Exclusiones confirmadas

- No se creó ni consultó una base.
- No se ejecutó o añadió una migración.
- No se creó motor, sesión o repositorio DBI.
- No se añadió un endpoint.
- No se creó una cola, broker o consumidor.
- No se conectó almacenamiento de objetos.
- No se habilitó PostGIS.
- No se procesó una ortofoto ni se ejecutó inferencia.
- No se modificó `pipeline_orchestrator.py`.
- No se modificaron Render, Green API o Google Sheets.
- No se cambió la lógica conversacional del bot.
- No se descargó, actualizó o promovió un modelo de IA.
