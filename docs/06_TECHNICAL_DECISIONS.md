# 06 — Decisiones técnicas

## DEC-001

**Decisión:** usar un monorepositorio modular.

**Motivo:** los módulos comparten usuarios, fincas, lotes, contratos y datos,
pero deben poder evolucionar y probarse por separado.

## DEC-002

**Decisión:** no subir ortofotos, GeoPackage, pesos de modelos, datasets,
resultados generados ni credenciales a Git.

**Motivo:** seguridad, tamaño y rendimiento del repositorio.

## DEC-003

**Decisión:** conservar los sistemas importados sin refactorización destructiva
durante el primer commit.

**Motivo:** mantener una línea base reproducible antes de integrar.

## DEC-004

**Decisión:** considerar `apps/platform-web/backend` como candidato a API central
de DALGORO Banana Intelligence.

**Motivo:** ya contiene FastAPI, autenticación, usuarios, empresas, documentos,
suscripciones, auditoría y migraciones. La adaptación definitiva se define en
`DBI-ARC-001` y se implementará por tickets posteriores.

## DEC-005

**Decisión:** aislar físicamente PostgreSQL/PostGIS de los sistemas existentes.

**Motivo:** evitar que una conexión, migración o error operativo de la nueva
plataforma altere bases que ya funcionan en producción.

**Controles obligatorios:**

- Usar `DBI_DATABASE_URL` exclusivamente para la plataforma nueva.
- No copiar ni reutilizar la conexión productiva actual.
- Crear bases separadas para desarrollo, pruebas, staging y producción.
- Usar servicios nuevos para staging y producción.
- Mantener historial Alembic DBI independiente.
- Detener una migración si el entorno o nombre de base no pertenece a la lista
  autorizada.
- Separar roles `dbi_migrator`, `dbi_app` y `dbi_readonly`.
- Ejecutar migraciones de producción solo con aprobación explícita.

## DEC-006

**Decisión:** no registrar payloads completos de webhooks ni datos personales en
logs de infraestructura.

**Motivo:** los eventos pueden incluir teléfonos, mensajes, ubicaciones y otros
datos personales. Los logs operativos deben limitarse a metadatos técnicos
mínimos; el almacenamiento funcional autorizado en Google Sheets se mantiene
sin cambios hasta su migración controlada.

## DEC-007

**Decisión:** validar cada módulo en un trabajo de CI independiente y sin acceso
a servicios operativos.

**Motivo:** una compilación global no permite identificar qué módulo rompió la
instalación ni demuestra que sus dependencias, importaciones y endpoints mínimos
funcionen.

**Controles obligatorios:**

- Instalar cada `requirements.txt` en su propio runner.
- Ejecutar `pip check` y `compileall` por módulo.
- Probar el backend con SQLite en memoria y sin ejecutar migraciones.
- Sustituir Google Sheets antes de importar el bot en el smoke test.
- No invocar Green API, Render, PostgreSQL ni descargar modelos de IA.
- Instalar e importar el motor geoespacial sin procesar ortofotos.
- Ejecutar lint y build del frontend con Node 24.
- Mantener visibles los 115 avisos heredados de lint y rechazar cualquier
  incremento mediante una línea base cuantificada.
- Bloquear secretos detectados y registrar auditorías de dependencias aunque
  existan hallazgos heredados que requieran un ticket separado.
- Fijar las acciones externas a SHA completos para reducir riesgo de cadena de
  suministro.

## DEC-008

**Decisión:** mantener una sola fuente canónica por módulo y conservar las
versiones históricas exclusivamente en el historial de Git.

**Motivo:** las copias con nombres como `copy`, `_antes_` o `_respaldo`
pueden compilar por accidente, confundir revisiones y provocar que una
corrección se aplique al archivo equivocado.

**Controles obligatorios:**

- No versionar copias directas, respaldos manuales, archivos comprimidos ni
  volcados de revisión.
- Generar `sistema_completo_para_revision.txt` únicamente dentro de
  `outputs/review/`, ruta excluida de Git.
- Validar en CI las rutas obtenidas con `git ls-files`.
- Mantener las configuraciones y módulos históricos recuperables desde Git, sin
  duplicarlos en el árbol activo.
- Preservar y comprobar los 12 activos binarios funcionales hasta que un ticket
  específico evalúe su sustitución o traslado.
- No reescribir el historial del repositorio como parte de una limpieza
  ordinaria.

## DEC-009

**Decisión:** evolucionar `apps/platform-web/backend` como plano de control de
DALGORO Banana Intelligence mediante adaptación incremental.

**Motivo:** el backend ya ofrece autenticación, organizaciones, autorización,
auditoría y una superficie HTTP que puede reutilizarse. Reescribirlo o renombrar
masivamente el dominio SST antes de disponer de contratos y una base DBI
aislada aumentaría el riesgo.

**Controles obligatorios:**

- Conservar los routers y modelos heredados hasta que exista una migración
  explícita y probada.
- Añadir el dominio agrícola en módulos nuevos y delimitados.
- Evitar que los routers controlen directamente transporte, almacenamiento y
  procesamiento geoespacial.
- No declarar un endpoint, tabla o migración como existente hasta que su ticket
  lo implemente y pruebe.

## DEC-010

**Decisión:** ejecutar el análisis geoespacial como trabajo asíncrono en un
worker separado.

**Motivo:** el pipeline tiene 17 etapas, usa PyTorch, GDAL y artefactos grandes,
y puede requerir CPU/GPU y tiempos incompatibles con una petición HTTP
síncrona.

**Controles obligatorios:**

- La API crea y consulta trabajos; no ejecuta el pipeline dentro de su proceso.
- El worker recibe referencias autorizadas, nunca rutas locales del cliente.
- El worker usa almacenamiento temporal descartable.
- Los resultados se publican mediante manifiesto versionado e idempotente.
- El worker no escribe directamente en tablas de dominio.
- Los reintentos no pueden duplicar trabajos ni artefactos canónicos.

## DEC-011

**Decisión:** separar datos transaccionales, geometrías consultables y archivos
pesados por responsabilidad.

**Motivo:** PostgreSQL/PostGIS es adecuado para relaciones, estado, auditoría y
consultas espaciales, pero no para ortofotos, modelos, PDF, XLSX o GeoPackage
pesados.

**Controles obligatorios:**

- PostgreSQL/PostGIS conserva metadatos, relaciones y geometrías operativas.
- El almacenamiento de objetos conserva binarios privados e inmutables.
- Cada artefacto tiene huella SHA-256, tipo, tamaño, origen y etapa productora.
- Las descargas usan autorización temporal.
- Google Sheets mantiene la autoridad del bot solo durante la transición.
- No se permite doble autoridad silenciosa entre Sheets y PostgreSQL.

## DEC-012

**Decisión:** versionar contratos de trabajos, resultados y eventos desde su
primera implementación.

**Motivo:** la API, el worker y el bot evolucionarán a ritmos distintos. Un
contrato estable y explícito evita importaciones cruzadas y cambios
incompatibles.

**Controles obligatorios:**

- Incluir `schema_version`, identificador de correlación e idempotencia.
- Validar estados y transiciones.
- Referenciar activos por identificadores internos u objetos autorizados.
- Rechazar campos críticos desconocidos en comandos de ejecución.
- Mantener compatibilidad o migración explícita entre versiones.
- No interpretar los ejemplos de `DBI-ARC-001` como endpoints ya implementados.

## DEC-013

**Decisión:** tratar toda salida agronómica e inteligencia artificial como
evidencia trazable y sujeta a aprobación.

**Motivo:** una detección, una inferencia geométrica y una recomendación
profesional no tienen el mismo significado ni nivel de certeza.

**Controles obligatorios:**

- Clasificar cada hallazgo como dato observado, inferencia, hipótesis o
  recomendación.
- Registrar fuentes, versión del modelo, configuración, nivel de confianza y
  responsable.
- Las recomendaciones no aprobadas se muestran como borrador técnico.
- Un modelo Challenger no sustituye al Champion automáticamente.
- La promoción requiere métricas comparables, revisión y aprobación registrada.
- Conservar procedencia y auditoría de cualquier corrección humana.

## DEC-014

**Decisión:** iniciar el historial de datos DBI en un entorno Alembic
independiente, sin enlazar ni corregir las tres cabezas heredadas.

**Motivo:** mezclar revisiones del sistema importado con el nuevo dominio
agrícola podría aplicar operaciones sobre una base no autorizada y convertir
deuda histórica en una dependencia de DBI.

**Controles obligatorios:**

- `app/db/dbi_config.py` lee únicamente `DBI_ENVIRONMENT` y
  `DBI_DATABASE_URL`.
- Solo se aceptan URLs PostgreSQL y el nombre exacto autorizado por ambiente.
- Ningún motor o sesión DBI se crea durante la importación del módulo.
- `dbi_alembic.ini` apunta exclusivamente a `dbi_alembic/`.
- La tabla de control es `alembic_version_dbi`.
- La primera revisión `dbi_0001_baseline` no crea tablas de dominio.
- `alembic/`, `app/core/config.py` y `app/db/session.py` no se modifican como
  parte de `DBI-DATA-001`.
- CI valida ambos grafos y genera SQL DBI solo en modo offline.
- Crear bases, extensiones o roles y ejecutar migraciones online requiere un
  ticket posterior y aprobación explícita.

## DEC-015

**Decisión:** iniciar el mapa cronológico con un contrato de lectura estricto y
una interfaz MapLibre sin fuentes cartográficas externas ni datos simulados.

**Motivo:** la experiencia de navegación, filtros y comparación puede
establecerse antes de disponer de PostGIS y campañas reales, pero una maqueta
con geometrías o índices inventados podría confundirse con evidencia
agronómica.

**Controles obligatorios:**

- Versionar la respuesta como `farm-map-timeline.v1`.
- Rechazar campos desconocidos en los modelos del contrato.
- Exponer la consulta bajo la autenticación existente.
- Tratar los identificadores de finca como referencias internas opacas.
- Distinguir catálogo de capas de capas efectivamente disponibles.
- Devolver una cronología vacía mientras no exista persistencia autorizada.
- No incluir URLs, rutas locales, geometrías o mediciones de marcador.
- Mantener MapLibre con un estilo local y `sources: {}` en este corte.
- Habilitar comparación solo con dos fechas reales distintas.
- Conservar clasificación, confianza, procedencia y revisión profesional para
  cada entrada futura.
- No crear tablas, migraciones o conexiones como parte de `DBI-MAP-001`.

## DEC-016

**Decisión:** modelar finca, lote y campaña en metadatos DBI independientes
antes de crear sesiones, endpoints o capacidades geoespaciales.

**Motivo:** el contrato cartográfico necesita identificadores y campañas
persistentes, pero acoplar simultáneamente esquema, acceso online, autorización
y PostGIS impediría aislar riesgos y verificar el historial de migraciones.

**Controles obligatorios:**

- Usar exclusivamente `DBIBase` y el historial `dbi_alembic`.
- Crear solo `dbi_farms`, `dbi_plots` y `dbi_campaigns`.
- Mantener referencias internas UUID y códigos únicos por ámbito.
- No crear claves foráneas hacia modelos heredados.
- Restringir estados y consistencia temporal en la base.
- Generar UUID en la aplicación sin exigir extensiones PostgreSQL.
- No crear geometrías ni habilitar PostGIS en este corte.
- No sembrar fincas, lotes, campañas o resultados de ejemplo.
- Validar la revisión mediante SQL offline, sin conexiones.
- Mantener el mapa cronológico en estado vacío hasta un ticket de acceso
  autorizado.

## DEC-017

**Decisión:** implementar contratos estrictos y una máquina de estados pura
antes de incorporar cola, persistencia de trabajos o ejecución remota.

**Motivo:** conectar simultáneamente FastAPI, almacenamiento, mensajería y el
pipeline con PyTorch/GDAL impediría aislar errores de contrato, idempotencia y
seguridad de referencias.

**Controles obligatorios:**

- Versionar comando, resultado y manifiesto desde su primera implementación.
- Rechazar campos desconocidos en la API y en el adaptador del worker.
- Transportar identificadores internos de activos, nunca credenciales, URLs o
  rutas locales.
- Mantener el adaptador del worker independiente del backend.
- No importar ni ejecutar el orquestador desde la validación del comando.
- Distinguir estado global del trabajo de las 17 etapas internas del pipeline.
- Tratar la repetición del mismo estado como un no-op idempotente.
- Exigir autorización explícita para el reintento `failed → queued`.
- Mantener `succeeded` y `canceled` como estados terminales.
- Exigir tamaño positivo, huella SHA-256, rol y etapa en cada manifiesto.
- Conservar clasificación, fuentes, confianza y revisión profesional en cada
  hallazgo futuro.
- No crear endpoints, tablas, migraciones, colas o infraestructura en
  `DBI-JOB-001`.

## DEC-018

**Decisión:** persistir el estado global y los intentos antes de crear sesiones,
endpoints, cola o ejecución del worker.

**Motivo:** la idempotencia y los reintentos deben tener respaldo transaccional
antes de introducir efectos externos. Conectar simultáneamente persistencia,
mensajería, almacenamiento y pipeline impediría determinar qué componente
duplicó o perdió un trabajo.

**Controles obligatorios:**

- Usar exclusivamente `DBIBase` y el historial `dbi_alembic`.
- Separar el trabajo global de cada intento numerado.
- Hacer único `tenant_ref + request_id`.
- Relacionar trabajos solo con finca, lote y campaña DBI.
- Mantener las referencias de activos como identificadores opacos.
- Conservar huellas SHA-256, estados y fechas mediante restricciones.
- No crear claves foráneas hacia modelos heredados.
- No crear motor, sesión, repositorio o endpoint en `DBI-JOB-002`.
- No crear cola, broker, almacenamiento o ejecución del pipeline.
- Validar metadatos y migración exclusivamente en modo offline.

## DEC-019

**Decisión:** persistir metadatos de activos y artefactos antes de conectar
almacenamiento de objetos, sesiones, endpoints o cola.

**Motivo:** la pertenencia, integridad y verificabilidad de entradas y salidas
deben existir antes de introducir transferencia de binarios o efectos externos.
Conectar simultáneamente esquema, bucket, mensajería y worker impediría aislar
referencias cruzadas, objetos inválidos o artefactos duplicados.

**Controles obligatorios:**

- Usar exclusivamente `DBIBase` y el historial `dbi_alembic`.
- Separar activos de entrada y artefactos producidos.
- Relacionar los activos solo con finca y lote DBI.
- Vincular cada artefacto con un trabajo y un intento coherentes.
- Conservar claves relativas de objeto, MIME, tamaño positivo y SHA-256.
- Alinear roles y etapas con `artifact-manifest.v1`.
- No almacenar URL, credencial o ruta local como clave de objeto.
- No crear claves foráneas hacia modelos heredados.
- No crear motor, sesión, repositorio o endpoint en `DBI-ASSET-001`.
- No conectar bucket, SDK, URL firmada, cola o ejecución del pipeline.
- Validar metadatos y migración exclusivamente en modo offline.

## DEC-020

**Decisión:** crear motores y sesiones DBI únicamente mediante una fábrica
explícita, diferida y separada de la sesión heredada.

**Motivo:** los modelos DBI necesitan una frontera transaccional antes de
incorporar repositorios o endpoints, pero crear recursos globales o integrar el
ciclo de vida de FastAPI en el mismo cambio podría conectar una base durante la
importación y dificultar el aislamiento.

**Controles obligatorios:**

- Cargar exclusivamente configuración validada por `load_dbi_database_config()`.
- No importar `app/db/session.py` o `app/core/config.py`.
- No crear motores, fábricas o sesiones como objetos globales.
- Pasar el objeto `URL` validado a SQLAlchemy sin registrarlo o renderizarlo.
- Exigir un motor explícito para construir la fábrica de sesiones.
- Confirmar solo cuando el bloque transaccional termina correctamente.
- Ejecutar rollback si falla el bloque o el propio commit.
- Cerrar la sesión en todos los caminos y propagar la excepción.
- No integrar todavía la fábrica con `app/main.py` o routers.
- No crear repositorios, endpoints, cola, almacenamiento o ejecución.
- Validar el comportamiento con dobles y sin abrir conexiones.

## DEC-021

**Decisión:** separar repositorios DBI, unidad de trabajo y autorización en
incrementos verificables.

**Motivo:** los modelos y la fábrica transaccional necesitan una superficie de
acceso común antes de integrarse con FastAPI. Incorporar simultáneamente
consultas, identidad, ciclo de vida, endpoints y una base real impediría aislar
lecturas transversales y efectos transaccionales.

**Controles obligatorios:**

- Recibir una sesión DBI explícita en cada repositorio.
- No construir motores, fábricas o sesiones dentro de repositorios.
- Exigir `organization_ref` para finca, lote y campaña.
- Exigir `tenant_ref` para trabajo, intento, activo y artefacto.
- Unir lote y campaña con finca antes de aplicar el ámbito organizacional.
- Unir intento y artefacto con trabajo antes de aplicar el ámbito de tenant.
- Mantener `tenant_ref + request_id` en la consulta idempotente de trabajos.
- No confirmar, revertir, cerrar o eliminar dentro de repositorios.
- Reutilizar `dbi_session_scope()` como única autoridad transaccional.
- No interpretar el ámbito de consulta como autorización de identidad.
- No integrar FastAPI, endpoints, infraestructura o ejecución en este corte.
- Validar consultas y transacciones con dobles, sin conexiones.

## DEC-022

**Decisión:** separar la política de autorización DBI de la autenticación
heredada y de la resolución futura de pertenencias.

**Motivo:** `organization_ref` y `tenant_ref` son referencias opacas sin una
relación canónica con `User`, `Company` o los roles heredados. Inferir acceso
desde JWT, `ADMIN` o `Company.owner_id` antes de definir esa autoridad podría
crear acceso transversal y acoplar la nueva plataforma a `DATABASE_URL`.

**Controles obligatorios:**

- Recibir identidad, tenant, organizaciones, fincas, lotes y permisos como un
  contexto explícito ya resuelto.
- Exigir identidad y tenant no vacíos.
- Rechazar comodines y permisos desconocidos.
- Copiar los ámbitos a colecciones inmutables.
- Exigir tenant en toda autorización.
- Exigir organización antes de finca y finca antes de lote.
- Negar por defecto cualquier permiso o pertenencia ausente.
- Usar un único tipo y mensaje de denegación para no enumerar recursos.
- No interpretar `ADMIN`, otro rol heredado o `Company.owner_id` como acceso
  DBI.
- No importar FastAPI, SQLAlchemy, seguridad, modelos o sesiones heredadas.
- No resolver JWT, consultar pertenencias, invocar repositorios o abrir
  conexiones en este corte.
- Validar la política con biblioteca estándar y casos completamente offline.

## DEC-023

**Decisión:** mantener un backlog maestro canónico, trazable y gobernado por
dependencias antes de continuar la integración operativa.

**Motivo:** la arquitectura resumía cinco hitos pendientes, pero GitHub no
contenía un backlog abierto y varias capacidades del Project Charter y README
no tenían ticket específico. Continuar seleccionando incrementos aislados
podría producir una plataforma técnicamente parcial sin una ruta verificable
hacia el producto completo.

**Controles obligatorios:**

- `docs/27_MASTER_BACKLOG_DBI-PLAN-001.md` conserva el inventario, el orden, las
  dependencias, las puertas y la cobertura funcional.
- Los Issues #29 a #33 rastrean las puertas de salida de los hitos 9 a 13.
- Cada implementación futura requiere su propio Issue, rama, pruebas y Pull
  Request; un rastreador no autoriza cambios por sí solo.
- Todo ticket declara objetivo, dependencias, resultado verificable y
  exclusiones antes de modificar código.
- Las capacidades futuras se distinguen de las confirmadas en `main`.
- Ninguna dependencia puede referenciar un ticket ausente o formar ciclos.
- Seguridad, privacidad, autorización, revisión agronómica, gobierno de modelos,
  rendimiento, costos, restauración y UAT son puertas obligatorias.
- No se asignan fechas o presupuestos sin medición y estimación aprobadas.
- El cierre de cada ticket actualiza el backlog y
  `docs/13_CURRENT_STATUS.md`.
- Cambiar el orden o alcance exige evidencia y un ticket explícito.

## DEC-024

**Decisión:** persistir una autoridad DBI normalizada de principal, membresía,
permisos y ámbitos antes de integrar identidad con FastAPI.

**Motivo:** `DBIAccessContext` aplica permisos globales a todos sus ámbitos.
Mezclar en una sola concesión permisos distintos por organización, finca o lote
podría combinar privilegios y pertenencias que nunca fueron aprobados juntos.
Además, deducir la autoridad desde `User`, `Company`, `ADMIN` o JWT
mantendría el acoplamiento con la base heredada.

**Controles obligatorios:**

- Usar exclusivamente `DBIBase` y el historial `dbi_alembic`.
- Asignar un UUID canónico a cada `legacy_identity_ref` opaca.
- Mantener `tenant_ref` y `organization_ref` como referencias opacas.
- No crear claves foráneas hacia tablas heredadas.
- Hacer única la relación principal–tenant.
- Separar permisos globales de ámbitos jerárquicos.
- Alinear permisos exactamente con `DBIPermission`.
- Permitir contexto solo a principal y membresía `active`.
- Rechazar ausencia, duplicidad, inactividad, revocación o inconsistencia.
- Validar finca–organización y lote–finca–organización.
- Usar el UUID DBI como `principal_ref` del contexto.
- Recibir la sesión en el repositorio y el repositorio en el resolvedor.
- Conservar un único tipo y mensaje de denegación.
- No decodificar JWT ni interpretar roles heredados.
- No crear motores, fábricas, conexiones, endpoints o dependencias FastAPI.
- Mantener una sola cabeza DBI y las tres cabezas heredadas intactas.
- Validar modelos, consultas, resolución y SQL exclusivamente offline.
