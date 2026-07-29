# 22 — Persistencia de trabajos DBI-JOB-002

## Identificación

- Ticket: `DBI-JOB-002`
- Issue: #18
- Fecha: 2026-07-29
- Rama: `feat/DBI-JOB-002-persistencia-trabajos-intentos`
- Base: `main` en `d886830a53de3f3084284def8947107106cd6934`
- Pull request: pendiente
- Estado: en implementación

## Objetivo

Persistir el estado global y los intentos de los trabajos geoespaciales sobre
metadatos exclusivos de `DBIBase`, sin crear todavía motor, sesión, repositorio,
endpoint, cola, almacenamiento de objetos o ejecución del pipeline.

Este corte materializa en esquema las garantías de idempotencia y trazabilidad
definidas por `DBI-JOB-001`. No transforma los modelos en una operación
conectada a una base real.

## Evidencia revisada

La revisión de `main` confirmó:

- `DBI-JOB-001` implementa contratos estrictos y una máquina de estados pura;
- `DBIBase` contiene únicamente finca, lote y campaña;
- el historial DBI tiene una sola cabeza en
  `dbi_0002_agricultural_domain`;
- el backend todavía no dispone de motor, sesión o repositorio DBI;
- no existen activos, artefactos, hallazgos o trabajos persistentes;
- no existe cola, broker, productor o consumidor;
- el adaptador del worker no resuelve activos ni ejecuta el pipeline.

No se consultaron PostgreSQL, Render, Green API, Google Sheets, almacenamiento
de objetos o servicios de mensajería.

## Diseño implementado

### Trabajo global

`dbi_analysis_jobs` conserva:

- identificador UUID generado por la aplicación;
- tenant, solicitud y correlación como referencias opacas;
- claves foráneas a finca y lote;
- referencia opcional a campaña, porque el comando v1 no exige campaña;
- referencias opacas de ortofoto, límite y exclusiones;
- versión del modelo y configuración del pipeline;
- actor solicitante;
- huella SHA-256 del comando canónico;
- estado global y fechas UTC.

La unicidad de `tenant_ref + request_id` respalda la idempotencia del comando.
El estado se limita a los siete valores definidos por la máquina de estados de
`DBI-JOB-001`.

### Intentos

`dbi_analysis_job_attempts` conserva cada ejecución o reintento como una fila
separada. El par `job_id + attempt_number` es único y el número debe ser
positivo.

Cada intento registra:

- estado de ejecución;
- referencias opcionales de worker y build del pipeline;
- huella opcional del resultado;
- código técnico de fallo sin payload sensible;
- fechas de cola, inicio y finalización;
- fechas de creación y actualización.

Las restricciones impiden iniciar antes de encolar, terminar sin inicio o
finalizar antes del comienzo.

## Implementación por archivo

### Backend

- `app/dbi/models/analysis_jobs.py`: trabajo e intento.
- `app/dbi/models/__init__.py`: exportaciones del dominio DBI.

### Migración

- `dbi_alembic/versions/20260729_03_analysis_jobs.py`: dos tablas,
  restricciones, claves foráneas e índices.

### Integración continua

- `.github/scripts/ci_analysis_job_persistence.py`: metadatos, restricciones,
  relaciones, grafo y SQL offline.
- `.github/workflows/ci.yml`: ejecución del control en el trabajo backend.

### Documentación

- `docs/01_SYSTEM_ARCHITECTURE.md`: persistencia implementada y secuencia.
- `docs/06_TECHNICAL_DECISIONS.md`: `DEC-018`.
- `docs/13_CURRENT_STATUS.md`: ticket vigente.
- `docs/22_ANALYSIS_JOB_PERSISTENCE_DBI-JOB-002.md`: evidencia técnica.

## Validaciones previstas

| Verificación | Criterio |
| --- | --- |
| Compilación Python | Sin errores |
| Metadatos DBI | Cinco tablas exactas |
| Tablas nuevas | Trabajo e intento |
| Idempotencia | Tenant y solicitud únicos |
| Intentos | Número positivo y único por trabajo |
| Estados | Valores explícitos |
| Huellas | SHA-256 minúscula de 64 caracteres |
| Relaciones | Solo tablas DBI |
| Cabeza DBI | `dbi_0003_analysis_jobs` |
| SQL Alembic | Generación exclusivamente offline |
| Extensiones y datos iniciales | Ausentes |
| Conexiones externas | Cero |

## Naturaleza de los datos

Este ticket define estructura transaccional, no evidencia agronómica:

- dato observado: ninguno;
- inferencia: ninguna;
- hipótesis: ninguna;
- recomendación: ninguna;
- confianza: no aplica;
- aprobación profesional: no aplica.

Las referencias usadas por las pruebas serán marcadores estructurales y no
describirán una finca, ortofoto, modelo o resultado real.

## Riesgos residuales

- No existe sesión o repositorio DBI para aplicar transacciones.
- La pertenencia coherente de lote y campaña a la finca debe validarse antes de
  crear un trabajo operativo.
- No existe autorización por tenant, finca o lote.
- No se persisten activos, artefactos o hallazgos.
- No existe auditoría de cada transición de estado.
- No existe cola, broker, productor o consumidor.
- No existe almacenamiento privado ni resolución de activos.
- No existe ejecución del pipeline.
- No existe endpoint para crear o consultar trabajos.
- El mapa cronológico continúa vacío.

## Exclusiones confirmadas

- No se creó ni consultó una base.
- No se ejecutó una migración online.
- No se creó motor, sesión o repositorio DBI.
- No se añadió un endpoint.
- No se creó una cola, broker, productor o consumidor.
- No se conectó almacenamiento de objetos.
- No se habilitó PostGIS.
- No se procesó una ortofoto ni se ejecutó inferencia.
- No se modificó `pipeline_orchestrator.py`.
- No se modificaron Render, Green API o Google Sheets.
- No se cambió la lógica conversacional del bot.
- No se descargó, actualizó o promovió un modelo de IA.
