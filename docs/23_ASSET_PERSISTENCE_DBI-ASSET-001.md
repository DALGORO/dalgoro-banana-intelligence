# 23 — Persistencia de activos DBI-ASSET-001

## Identificación

- Ticket: `DBI-ASSET-001`
- Issue: #20
- Fecha: 2026-07-29
- Rama: `feat/DBI-ASSET-001-persistencia-activos-artefactos`
- Base: `main` en `77c849c733b2bbe140de4f63982b3a33dfd95816`
- Pull request: #21
- Estado: completado

## Objetivo

Persistir metadatos verificables de activos de entrada y artefactos producidos
por trabajos geoespaciales sobre `DBIBase`, sin crear todavía motor, sesión,
repositorio, endpoint, almacenamiento de objetos, cola o ejecución del worker.

Este corte extiende las garantías de `artifact-manifest.v1` al esquema
transaccional. No registra archivos reales ni convierte una clave de objeto en
una URL o ruta local.

## Evidencia revisada

La revisión de `main` confirmó:

- `DBI-JOB-001` define contratos estrictos para comandos, resultados,
  artefactos y hallazgos;
- `DBI-JOB-002` persiste trabajos e intentos, pero conserva las entradas como
  referencias opacas;
- `ArtifactManifest` exige rol, etapa, MIME, tamaño positivo, SHA-256, clave de
  objeto relativa y fecha consciente de zona horaria;
- los nueve roles y las 17 etapas del pipeline ya están enumerados;
- no existe tabla de activos o artefactos;
- no existe sesión, repositorio, endpoint, bucket, cola o consumidor;
- el adaptador del worker no resuelve activos ni ejecuta el pipeline.

No se consultaron PostgreSQL, Render, Green API, Google Sheets, almacenamiento
de objetos o servicios de mensajería.

## Diseño implementado

### Activos de entrada

`dbi_analysis_input_assets` conserva:

- identificador UUID generado por la aplicación;
- tenant y actor como referencias opacas;
- claves foráneas a finca y, opcionalmente, lote;
- tipo `orthophoto`, `boundary` o `exclusions`;
- estado `registered`, `verified`, `quarantined` o `retired`;
- clave relativa de objeto, tipo MIME, tamaño positivo y huella SHA-256;
- CRS opcional y fecha de verificación;
- fechas de creación y actualización.

La combinación `tenant_ref + object_key` es única. El estado `verified` exige
una fecha de verificación. La tabla no contiene URL, credencial o ruta local.

### Artefactos producidos

`dbi_analysis_artifacts` materializa `artifact-manifest.v1`:

- identificador, trabajo e intento;
- versión del manifiesto;
- uno de los nueve roles canónicos;
- clave relativa de objeto, MIME, tamaño y SHA-256;
- una de las 17 etapas productoras;
- CRS opcional y fecha de creación.

La pareja `attempt_id + job_id` referencia una clave única del intento. Esta
integridad compuesta impide asociar un artefacto con un trabajo y un intento
perteneciente a otro trabajo.

La clave de objeto es única para los artefactos y rechaza:

- esquemas URL por exclusión del carácter `:`;
- rutas absolutas;
- barras invertidas;
- segmentos vacíos;
- segmentos `.` o `..`.

### Historial Alembic

`dbi_0004_assets_artifacts` desciende directamente de
`dbi_0003_analysis_jobs`. Añade la clave compuesta del intento antes de crear
los artefactos y la retira después de eliminar ambas tablas durante el
`downgrade`.

La revisión no habilita extensiones, no genera UUID en PostgreSQL, no inserta
datos y no altera el historial Alembic heredado.

## Implementación por archivo

### Backend

- `app/dbi/models/assets.py`: activos y artefactos.
- `app/dbi/models/analysis_jobs.py`: identidad compuesta del intento.
- `app/dbi/models/__init__.py`: exportaciones explícitas.

### Migración

- `dbi_alembic/versions/20260729_04_assets_artifacts.py`: dos tablas,
  restricciones, claves foráneas e índices.

### Integración continua

- `.github/scripts/ci_asset_persistence.py`: metadatos, restricciones,
  paridad con contratos, grafo y SQL offline.
- `.github/scripts/ci_analysis_job_persistence.py`: conserva la validación de
  la revisión de trabajos sin congelarla como cabeza permanente.
- `.github/workflows/ci.yml`: ejecución del nuevo control en backend.

### Documentación

- `docs/01_SYSTEM_ARCHITECTURE.md`: persistencia implementada y secuencia.
- `docs/06_TECHNICAL_DECISIONS.md`: `DEC-019`.
- `docs/13_CURRENT_STATUS.md`: ticket vigente.
- `docs/23_ASSET_PERSISTENCE_DBI-ASSET-001.md`: evidencia técnica.

## Validaciones locales ejecutadas

| Verificación | Resultado |
| --- | --- |
| Compilación Python | Aprobada |
| Dominio agrícola heredado | Aprobado |
| Contrato API–worker heredado | Aprobado |
| Persistencia de trabajos heredada | Aprobada |
| Metadatos DBI | Siete tablas exactas |
| Integridad trabajo–intento | Clave foránea compuesta |
| Activos | Tipos, estados y pertenencia restringidos |
| Artefactos | Nueve roles y 17 etapas |
| Objetos | Claves relativas, MIME, tamaño y SHA-256 |
| Cabeza DBI | `dbi_0004_assets_artifacts` |
| SQL Alembic | Generación exclusivamente offline |
| Extensiones y datos iniciales | Ausentes |
| Conexiones externas | Cero |

Las dependencias focalizadas usadas en el entorno descartable coincidieron con
el backend: Alembic 1.17.0, SQLAlchemy 2.0.44, psycopg 3.2.12 y Pydantic 2.12.3.
No se modificó `requirements.txt`.

## Validación remota

GitHub Actions `30473493853` aprobó seis de seis trabajos sobre el SHA final
validado `e43ff9e743fbd0a472b66cd1cba9a6c08075a074`:

- backend con instalación completa, ambos grafos Alembic, aislamiento, dominio,
  mapa, contratos, trabajos, siete tablas, activos, artefactos y healthcheck;
- frontend con instalación, lint y build de producción;
- bot con instalación, compilación y smoke test;
- motor de densidad con dependencias, compilación, importaciones y CLI;
- higiene de artefactos y detección de secretos.

El diff contiene 11 archivos —cuatro añadidos y siete modificados— y cero
retraso frente a `main`. El cierre fue autorizado expresamente para el PR #21.
No se abrió una conexión, no se ejecutó una migración online, no se resolvió un
objeto y no se invocó el pipeline.

## Naturaleza de los datos

Este ticket define metadatos estructurales y no evidencia agronómica:

- dato observado: ninguno;
- inferencia: ninguna;
- hipótesis: ninguna;
- recomendación: ninguna;
- fuente técnica: contratos y metadatos del repositorio;
- confianza: no aplica;
- aprobación profesional: no aplica.

Las pruebas no describen una finca, ortofoto, modelo o resultado real.

## Riesgos residuales

- Los trabajos aún conservan referencias opacas de entrada y no las resuelven.
- No existe sesión o repositorio DBI para validar tenant, finca y lote en una
  transacción.
- No existe servicio que emita claves de objeto.
- No existe almacenamiento privado ni verificación del contenido binario.
- No existen URLs temporales autorizadas para carga o descarga.
- No se persisten hallazgos agronómicos.
- No existe cola, productor, consumidor o ejecución del pipeline.
- El mapa cronológico continúa vacío.

## Exclusiones confirmadas

- No se creó ni consultó una base.
- No se ejecutó una migración online.
- No se creó motor, sesión o repositorio DBI.
- No se añadió un endpoint.
- No se conectó un bucket o SDK de almacenamiento.
- No se generó una URL firmada.
- No se creó una cola, broker, productor o consumidor.
- No se habilitó PostGIS.
- No se procesó una ortofoto ni se ejecutó inferencia.
- No se modificó `pipeline_orchestrator.py`.
- No se modificaron Render, Green API o Google Sheets.
- No se cambió la lógica conversacional del bot.
- No se descargó, actualizó o promovió un modelo de IA.
