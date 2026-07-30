# 27 — Backlog maestro DBI-PLAN-001

<!-- markdownlint-disable MD013 -->

## Identificación

- Ticket: `DBI-PLAN-001`.
- Issue: #28.
- Fecha: 2026-07-29.
- Rama: `feat/DBI-PLAN-001-backlog-maestro`.
- Base: `main` en `21346aeb7bf568fba97ca0c4fa7364b12b4670df`.
- Estado: en revisión.
- Código funcional modificado: ninguno.

## Objetivo

Convertir la arquitectura objetivo, el Project Charter, el README y el estado
real de `main` en una ruta completa y verificable hacia DALGORO Banana
Intelligence.

Este documento es la fuente canónica del orden futuro. Los Issues de GitHub
mantienen el seguimiento operativo. Una capacidad planificada no se considera
implementada hasta que su propio ticket, rama, pruebas, Pull Request y evidencia
de cierre estén integrados en `main`.

## Fuentes y método

La planificación se contrastó con:

- `README.md` y `docs/00_PROJECT_CHARTER.md`;
- `docs/01_SYSTEM_ARCHITECTURE.md`;
- `docs/06_TECHNICAL_DECISIONS.md`;
- `docs/13_CURRENT_STATUS.md`;
- los informes técnicos `docs/14_...` a `docs/26_...`;
- los 13 Issues de implementación cerrados hasta `DBI-AUTH-001`;
- `app/main.py`, autenticación y dependencias FastAPI heredadas;
- modelos, sesiones, repositorios y autorización DBI;
- contratos de mapa, trabajos, activos y worker;
- frontend, bot, Google Sheets y motor geoespacial importados;
- `.github/workflows/ci.yml` y sus barreras offline.

No se consultaron bases, Render, Green API, Google Sheets, almacenamiento,
colas, modelos remotos ni datos productivos.

## Reglas de gobierno

1. Cada incremento usa un identificador único, Issue, rama y Draft PR.
2. El Issue define objetivo, alcance, exclusiones, dependencias, riesgos,
   pruebas y criterios de aceptación antes de escribir código.
3. Ningún ticket puede consumir una dependencia pendiente como si existiera.
4. Una migración online, un despliegue o un corte productivo exige autorización
   explícita independiente.
5. `DATABASE_URL`, migraciones heredadas y servicios productivos permanecen
   separados de DBI.
6. Los datos agrícolas distinguen dato observado, inferencia, hipótesis,
   recomendación, fuente, confianza y aprobación profesional.
7. Un modelo Challenger nunca sustituye automáticamente al Champion.
8. Rendimiento, volumen de ortofotos, costos, restauración y UAT son puertas de
   producción, no tareas opcionales posteriores.
9. Las estimaciones de tiempo o costo solo se fijarán después de medir una línea
   base; este backlog no constituye una promesa contractual.
10. Cambiar el orden, dividir o retirar un ticket requiere evidencia y
    actualización conjunta de este documento y del estado oficial.

## Línea base implementada

| Área | Estado confirmado en `main` | Límite actual |
| --- | --- | --- |
| Arquitectura | Límites, propiedad de datos y contratos conceptuales aprobados | Los servicios continúan separados |
| Datos DBI | Configuración, Alembic, siete tablas, fábrica, repositorios y UoW offline | No existe base DBI aprovisionada |
| Autorización | Política pura y cerrada por defecto | No existe autoridad de membresías ni resolvedor |
| Mapa | Ruta React y contrato HTTP vacío | Sin persistencia, geometrías o capas reales |
| Trabajos | Contratos, estados, trabajos e intentos persistibles | Sin API, cola o ejecución |
| Activos | Metadatos y manifiestos persistibles | Sin almacenamiento o transferencia |
| Worker | Pipeline local y adaptador puro del comando v1 | Recibe rutas locales fuera del contrato DBI |
| SST | Aplicación heredada funcional | Usa base, modelos y autoridad heredados |
| Bot | Flujo Green API y Google Sheets importado | No consume la API DBI |
| CI | Seis trabajos modulares y barreras offline | No prueba servicios DBI reales |

## Cobertura del objetivo funcional

| Capacidad objetivo | Estado al iniciar `DBI-PLAN-001` | Tickets de cobertura |
| --- | --- | --- |
| Dashboard ejecutivo | Parcial: dashboard SST heredado | `DBI-DASH-001` |
| Mapas cronológicos | Parcial: contrato e interfaz vacíos | `DBI-GEO-001`, `DBI-MAP-002` |
| Densidad y análisis geoespacial | Parcial: motor local y contratos | `DBI-JOB-003`, `DBI-QUEUE-001`, `DBI-WORKER-001`, `DBI-RESULT-001` |
| RGB, NDVI, NDRE y multiespectral | Pendiente | `DBI-MULTI-001` |
| Inspecciones y actividades | Pendiente | `DBI-INSPECT-001` |
| Agrometeorología | Pendiente | `DBI-METEO-001` |
| Cosecha, racimos, cintas, clústeres y cajas | Pendiente | `DBI-PROD-001` |
| Empacadora | Pendiente | `DBI-PACK-001` |
| SST agrícola sobre DBI | Parcial: módulo heredado separado | `DBI-SST-001` |
| WhatsApp | Parcial: bot con Sheets | `DBI-BOT-001`, `DBI-BOT-002`, `DBI-BOT-003` |
| Biblioteca técnica | Pendiente | `DBI-LIB-001` |
| Recomendaciones y aprobación profesional | Contrato conceptual | `DBI-AGR-001` |
| Gobierno de modelos | Decisión documental | `DBI-ML-001` |
| Usuarios, organizaciones y permisos DBI | Política pura sin membresías | `DBI-AUTH-002`, `DBI-ADMIN-001` |
| Rendimiento, volumen y costos | Pendiente | `DBI-PERF-001` |
| Despliegue y continuidad | Pendiente | `DBI-DEPLOY-001`, `DBI-DR-001` |
| Piloto y transferencia | Pendiente | `DBI-UAT-001` |

Todas las capacidades declaradas en el Charter y el README tienen al menos un
ticket de cierre. La cobertura indica responsabilidad futura; no afirma que la
capacidad ya exista.

## Hitos operativos

| Hito | Issue | Propósito | Puerta de salida |
| --- | --- | --- | --- |
| 9 | #29 | Plano de control y persistencia DBI operativa | Identidad, API y base aislada verificadas |
| 10 | #30 | Almacenamiento, cola y ejecución geoespacial | Trabajo extremo a extremo idempotente |
| 11 | #31 | Producto agrícola, dashboard y PWA | Módulos funcionales trazables y autorizados |
| 12 | #32 | Migración controlada del bot y Sheets | DBI como autoridad única aprobada |
| 13 | #33 | Operación, seguridad y producción | Capacidad, recuperación y UAT demostrados |

Los hitos expresan puertas de salida. Pueden desarrollarse tickets compatibles
en paralelo, pero ninguno puede omitir sus dependencias o la evidencia de su
propia aceptación.

## Backlog ordenado

### Hito 9 — Plano de control y persistencia operativa

#### 1. `DBI-AUTH-002` — Identidad y membresías DBI

- Objetivo: persistir la autoridad canónica de membresías y resolver un
  `DBIAccessContext` cerrado por defecto.
- Depende de: `DBI-AUTH-001`, `DBI-DATA-004` y `DBI-PLAN-001`.
- Resultado verificable: modelos y migración DBI offline, resolvedor con sesión
  explícita y casos de denegación por identidad o pertenencia inconsistente.
- Exclusiones: FastAPI, JWT, conexión PostgreSQL y cambios en `User` o
  `Company`.

#### 2. `DBI-API-001` — Ciclo de vida DBI en FastAPI

- Objetivo: crear y disponer motor/fábrica DBI en el ciclo de vida de la API y
  exponer dependencias sin objetos globales de sesión.
- Depende de: `DBI-AUTH-002`, `DBI-DATA-004`.
- Resultado verificable: lifespan, dependencias y rollback probados con dobles;
  importación sin conexión.
- Exclusiones: endpoints de dominio, base real y sesión heredada.

#### 3. `DBI-API-002` — Consultas DBI autorizadas

- Objetivo: exponer lecturas de finca, lote, campaña, trabajo, activo y
  artefacto mediante la política DBI.
- Depende de: `DBI-API-001`, `DBI-AUTH-002`.
- Resultado verificable: contratos estrictos, 401/403/404 no enumerables y
  consultas acotadas probadas.
- Exclusiones: escritura, carga de binarios y procesamiento.

#### 4. `DBI-API-003` — Escrituras DBI autorizadas

- Objetivo: crear y actualizar finca, lote y campaña mediante unidad de trabajo,
  idempotencia y auditoría mínima.
- Depende de: `DBI-API-002`.
- Resultado verificable: validación, conflictos, rollback y autorización
  probados.
- Exclusiones: geometrías PostGIS, activos, trabajos y borrados destructivos.

#### 5. `DBI-INFRA-001` — PostgreSQL/PostGIS y roles por ambiente

- Objetivo: aprovisionar servicios DBI separados y roles `dbi_migrator`,
  `dbi_app` y `dbi_readonly`.
- Depende de: `DBI-DATA-001`, aprobación explícita de infraestructura.
- Resultado verificable: desarrollo/pruebas aislados, PostGIS disponible,
  secretos externos a Git y permisos mínimos comprobados.
- Exclusiones: producción, carga de datos y migraciones heredadas.

#### 6. `DBI-GEO-001` — Geometrías operativas y esquema espacial

- Objetivo: modelar límites autorizados de finca/lote y geometrías consultables
  con CRS y validaciones explícitas.
- Depende de: `DBI-AUTH-002`, `DBI-DATA-002`.
- Resultado verificable: modelos, revisión Alembic y SQL PostGIS validados
  offline con una sola cabeza DBI.
- Exclusiones: tiles, ortofotos, análisis y migración online.

#### 7. `DBI-MIG-001` — Aplicación controlada de migraciones DBI

- Objetivo: aplicar el historial DBI en desarrollo y pruebas sobre servicios
  aislados, incluyendo ensayo de avance y reversión aprobada.
- Depende de: `DBI-INFRA-001`, `DBI-GEO-001`.
- Resultado verificable: base vacía a cabeza, verificación de tablas/roles y
  restauración del ensayo sin tocar bases heredadas.
- Exclusiones: staging, producción y datos productivos.

#### 8. `DBI-ADMIN-001` — Administración funcional DBI

- Objetivo: administrar principales, organizaciones, membresías y permisos sin
  convertir el rol heredado `ADMIN` en acceso universal.
- Depende de: `DBI-API-003`, `DBI-AUTH-002`.
- Resultado verificable: operaciones autorizadas, auditoría, revocación y
  protección contra autoescalamiento.
- Exclusiones: facturación, acceso global implícito y administración de
  infraestructura.

### Hito 10 — Almacenamiento, cola y ejecución geoespacial

#### 9. `DBI-STORAGE-001` — Almacenamiento privado de objetos

- Objetivo: definir un puerto de almacenamiento y un adaptador privado con
  claves relativas, cifrado, integridad y acceso temporal.
- Depende de: `DBI-AUTH-002`, aprobación de proveedor.
- Resultado verificable: carga/lectura/borrado lógico con dobles y entorno no
  productivo; ninguna credencial o URL persistida como contrato.
- Exclusiones: endpoints de activos y ejecución del worker.

#### 10. `DBI-ASSET-002` — Registro, carga y verificación de activos

- Objetivo: coordinar metadatos DBI y objetos privados para entradas autorizadas.
- Depende de: `DBI-STORAGE-001`, `DBI-API-001`, `DBI-ASSET-001`.
- Resultado verificable: carga idempotente, SHA-256, tamaño, MIME, estado y
  limpieza compensatoria probados.
- Exclusiones: análisis, cola y artefactos del worker.

#### 11. `DBI-JOB-003` — Servicio y API idempotente de trabajos

- Objetivo: aceptar, consultar, cancelar y reintentar trabajos mediante
  `tenant_ref + request_id`.
- Depende de: `DBI-ASSET-002`, `DBI-API-001`, `DBI-JOB-002`.
- Resultado verificable: comandos v1 creados desde referencias verificadas,
  transiciones válidas y duplicados neutralizados.
- Exclusiones: publicación real en cola y ejecución.

#### 12. `DBI-QUEUE-001` — Entrega durable de comandos y resultados

- Objetivo: introducir productor, consumidor, confirmación, reintento y cola de
  mensajes fallidos sobre contratos versionados.
- Depende de: `DBI-JOB-003`, aprobación de proveedor.
- Resultado verificable: entrega al menos una vez sin duplicar efectos, trazas
  de correlación y recuperación de mensajes fallidos.
- Exclusiones: lógica del pipeline y escritura directa del worker en DBI.

#### 13. `DBI-ML-001` — Registro de modelos y Champion/Challenger

- Objetivo: registrar versiones, artefactos, métricas, datasets de evaluación y
  decisiones de promoción.
- Depende de: `DBI-AUTH-002`, `DBI-STORAGE-001`.
- Resultado verificable: estados Champion/Challenger, comparación reproducible,
  aprobación registrada y prohibición de promoción automática.
- Exclusiones: entrenamiento automático y cambio de modelo productivo sin
  aprobación.

#### 14. `DBI-WORKER-001` — Ejecución aislada del pipeline

- Objetivo: resolver activos autorizados, ejecutar el pipeline en espacio
  temporal y publicar manifiestos sin importar el backend.
- Depende de: `DBI-QUEUE-001`, `DBI-STORAGE-001`, `DBI-ML-001`.
- Resultado verificable: éxito, fallo, cancelación y reintento con limpieza,
  límites de recursos y artefactos inmutables.
- Exclusiones: escritura directa en tablas de dominio y rutas del equipo del
  analista.

#### 15. `DBI-RESULT-001` — Ingesta idempotente de resultados

- Objetivo: validar resultados v1 y persistir intentos, artefactos, métricas y
  hallazgos una sola vez.
- Depende de: `DBI-WORKER-001`, `DBI-JOB-003`.
- Resultado verificable: consumidor transaccional, manifiestos verificados,
  duplicados inocuos y rechazo de referencias cruzadas.
- Exclusiones: aprobación automática de recomendaciones.

#### 16. `DBI-MAP-002` — Cronología real de capas

- Objetivo: sustituir la respuesta vacía por campañas, geometrías y artefactos
  autorizados con fechas reales.
- Depende de: `DBI-API-002`, `DBI-GEO-001`, `DBI-RESULT-001`.
- Resultado verificable: catálogo/disponibilidad diferenciados, dos fechas para
  comparación, acceso temporal y estados vacío/error probados.
- Exclusiones: datos simulados y acceso público a objetos privados.

#### 17. `DBI-MULTI-001` — Productos RGB y multiespectrales

- Objetivo: versionar entradas, calibración y productos RGB, NDVI, NDRE y otros
  índices aprobados.
- Depende de: `DBI-WORKER-001`, `DBI-ML-001`, `DBI-STORAGE-001`.
- Resultado verificable: procedencia, fórmula/configuración, CRS, calidad,
  rango, máscara y artefactos reproducibles.
- Exclusiones: interpretación agronómica automática o índice sin fuente y
  control de calidad.

### Hito 11 — Producto agrícola, dashboard y PWA

#### 18. `DBI-DASH-001` — Dashboard agrícola integrado

- Objetivo: mostrar KPIs autorizados con fecha, fuente, cobertura, calidad y
  estados sin datos.
- Depende de: `DBI-API-002`, `DBI-MAP-002`.
- Resultado verificable: contratos agregados, filtros de finca/lote/campaña y
  cifras reconciliables con la fuente.
- Exclusiones: métricas inventadas y acceso directo del frontend a la base.

#### 19. `DBI-PWA-001` — PWA y base de captura offline

- Objetivo: instalar, cachear la interfaz segura y ofrecer una cola local
  versionada para formularios permitidos.
- Depende de: `DBI-DASH-001`, `DBI-API-002`.
- Resultado verificable: instalación, actualización, expiración de sesión,
  sincronización idempotente y conflictos visibles.
- Exclusiones: almacenar secretos, ortofotos o permisos indefinidamente.

#### 20. `DBI-INSPECT-001` — Inspecciones y actividades

- Objetivo: planificar, ejecutar y cerrar inspecciones y actividades de campo
  con evidencia y responsables.
- Depende de: `DBI-API-003`, `DBI-PWA-001`, `DBI-GEO-001`.
- Resultado verificable: estados, asignación, ubicación autorizada, anexos,
  sincronización y auditoría.
- Exclusiones: recomendaciones automáticas y sustitución de aprobación
  profesional.

#### 21. `DBI-METEO-001` — Agrometeorología

- Objetivo: integrar observaciones y pronósticos con estación, fuente, tiempo,
  calidad y cobertura espacial.
- Depende de: `DBI-API-003`, `DBI-GEO-001`.
- Resultado verificable: ingestión idempotente, unidades, zona horaria,
  ausencia de datos y procedencia probadas.
- Exclusiones: alertas agronómicas sin umbral aprobado o proveedor no evaluado.

#### 22. `DBI-PROD-001` — Cosecha y trazabilidad productiva

- Objetivo: registrar racimos, cintas, clústeres, cosecha, rechazo y cajas por
  finca, lote y campaña.
- Depende de: `DBI-API-003`.
- Resultado verificable: catálogos, unidades, estados, conciliación y auditoría
  con reglas de negocio aprobadas.
- Exclusiones: operación de empacadora y predicción automática.

#### 23. `DBI-PACK-001` — Operación de empacadora

- Objetivo: modelar recepción, proceso, calidad, empaque, cajas y despacho con
  vínculo a la cosecha.
- Depende de: `DBI-PROD-001`.
- Resultado verificable: balances de entrada/salida, mermas, lotes, turnos,
  trazabilidad y conciliación.
- Exclusiones: facturación, ERP y automatización industrial no aprobada.

#### 24. `DBI-SST-001` — Integración SST con DBI

- Objetivo: relacionar obligaciones, IPERC, incidentes y evidencias SST con la
  organización/finca DBI sin doble autoridad silenciosa.
- Depende de: `DBI-API-003`, `DBI-ADMIN-001`.
- Resultado verificable: mapa de datos, adaptador, autorización, conciliación y
  regresión del módulo heredado.
- Exclusiones: migración destructiva de tablas heredadas y cambios normativos
  sin validación profesional.

#### 25. `DBI-LIB-001` — Biblioteca técnica trazable

- Objetivo: gestionar fuentes técnicas versionadas, vigencia, jurisdicción,
  autoría y relaciones con hallazgos.
- Depende de: `DBI-API-003`, `DBI-STORAGE-001`.
- Resultado verificable: metadatos, búsqueda, permisos, versiones, retiro y
  citas persistentes.
- Exclusiones: copiar obras sin licencia y tratar una fuente como recomendación
  aprobada.

#### 26. `DBI-AGR-001` — Revisión y aprobación agronómica

- Objetivo: gestionar borradores, observaciones, aprobación, rechazo, vigencia
  y corrección de hallazgos y recomendaciones.
- Depende de: `DBI-RESULT-001`, `DBI-LIB-001`, `DBI-AUTH-002`.
- Resultado verificable: clasificación, fuentes, confianza, revisor, firma de
  decisión, historial y revocación auditables.
- Exclusiones: autoaprobación por IA y ocultar incertidumbre o correcciones.

### Hito 12 — Migración controlada del bot

#### 27. `DBI-BOT-001` — Adaptador WhatsApp hacia la API DBI

- Objetivo: separar transporte Green API de operaciones DBI mediante un cliente
  de API idempotente.
- Depende de: `DBI-API-002`, `DBI-AUTH-002`.
- Resultado verificable: contrato, autenticación de servicio, correlación,
  reintentos y regresión conversacional con dobles.
- Exclusiones: retirar Sheets o modificar mensajes humanizados.

#### 28. `DBI-BOT-002` — Conciliación y migración desde Sheets

- Objetivo: inventariar, transformar, ensayar y conciliar contactos, mensajes,
  citas, conversaciones y estados.
- Depende de: `DBI-BOT-001`, `DBI-API-003`.
- Resultado verificable: conteos, huellas, duplicados, errores, reejecución y
  reporte de diferencias sobre copia controlada.
- Exclusiones: corte productivo y eliminación de hojas.

#### 29. `DBI-BOT-003` — Corte y retirada de doble autoridad

- Objetivo: convertir DBI en autoridad aprobada manteniendo Green API como
  transporte, contingencia y reversión.
- Depende de: `DBI-BOT-002`.
- Resultado verificable: ensayo, ventana, respaldo, monitoreo, reconciliación
  posterior y rollback probado.
- Exclusiones: cambio sin aprobación, pérdida de historial o borrado inmediato
  de Sheets.

### Hito 13 — Operación y salida a producción

#### 30. `DBI-OBS-001` — Observabilidad, auditoría y trazas

- Objetivo: instrumentar correlación, métricas, logs mínimos, auditoría y
  alertas sin exponer datos personales o secretos.
- Depende de: `DBI-API-001`, `DBI-RESULT-001`.
- Resultado verificable: trazas API-cola-worker, paneles, alertas, retención y
  pruebas de redacción de datos.
- Exclusiones: payloads completos y credenciales en telemetría.

#### 31. `DBI-SEC-002` — Dependencias y endurecimiento

- Objetivo: priorizar y remediar vulnerabilidades heredadas sin actualizaciones
  masivas no verificadas.
- Depende de: `DBI-PLAN-001`.
- Resultado verificable: inventario, riesgo, actualización por lote pequeño,
  regresión, SBOM y excepciones con vencimiento.
- Exclusiones: `npm audit fix` automático y ocultar hallazgos.

#### 32. `DBI-PERF-001` — Rendimiento, volumen y costos

- Objetivo: medir API, base, transferencia, cola y pipeline con volúmenes
  representativos de ortofotos y usuarios.
- Depende de: `DBI-MAP-002`, `DBI-MULTI-001`, `DBI-PROD-001`.
- Resultado verificable: escenarios, percentiles, concurrencia, límites,
  capacidad, costo unitario y umbrales de rechazo.
- Exclusiones: usar datos productivos sin autorización o prometer capacidad no
  medida.

#### 33. `DBI-DEPLOY-001` — Despliegues separados por ambiente

- Objetivo: automatizar artefactos inmutables, configuración, promoción y
  rollback en desarrollo, pruebas, staging y producción separados.
- Depende de: `DBI-INFRA-001`, `DBI-MIG-001`, `DBI-OBS-001`,
  `DBI-SEC-002`, `DBI-PERF-001`.
- Resultado verificable: pipeline, aprobaciones, secretos, migraciones,
  smoke tests y rollback por ambiente.
- Exclusiones: desplegar producción durante la implementación del ticket.

#### 34. `DBI-DR-001` — Respaldos, restauración y continuidad

- Objetivo: definir y probar RPO/RTO, copias, restauración de base/objetos,
  continuidad de cola y runbooks.
- Depende de: `DBI-DEPLOY-001`, `DBI-STORAGE-001`.
- Resultado verificable: restauración aislada, integridad, tiempos medidos,
  responsables y simulacro documentado.
- Exclusiones: considerar un respaldo no restaurado como evidencia suficiente.

#### 35. `DBI-UAT-001` — Piloto integral y transferencia

- Objetivo: ejecutar un piloto con criterios funcionales, técnicos,
  agronómicos, seguridad, rendimiento, continuidad y operación autónoma.
- Depende de: `DBI-INSPECT-001`, `DBI-METEO-001`, `DBI-PACK-001`,
  `DBI-SST-001`, `DBI-AGR-001`, `DBI-BOT-003` y `DBI-DR-001`.
- Resultado verificable: matriz de aceptación, incidencias resueltas, manuales,
  capacitación, responsables, acta de aceptación y plan de soporte.
- Exclusiones: declarar producción completa con criterios abiertos o evidencia
  simulada.

## Dependencias críticas

- `DBI-AUTH-002` es el primer ticket ejecutable y no requiere conexión.
- FastAPI depende de una autoridad DBI; no debe inferir ámbitos desde roles
  heredados.
- La migración online depende de infraestructura aislada y de un historial
  offline validado.
- La cola depende del servicio idempotente de trabajos.
- El worker depende de almacenamiento privado, cola y modelo registrado.
- El mapa real depende de geometrías y resultados persistidos.
- La aprobación agronómica depende de hallazgos y fuentes técnicas.
- El corte del bot depende de conciliación reproducible.
- Despliegue depende de observabilidad, seguridad, capacidad y costos medidos.
- UAT no sustituye restauración, revisión agronómica o gobierno de modelos.

## Puertas obligatorias

### Puerta de seguridad y privacidad

- Secretos fuera de Git.
- Permisos mínimos por identidad y servicio.
- Logs sin payloads personales completos.
- Dependencias auditadas y excepciones con responsable y vencimiento.

### Puerta de datos y autorización

- Fuente canónica explícita.
- Idempotencia, integridad y auditoría.
- Tenant, organización, finca y lote validados.
- Migraciones y reversión ensayadas en el ambiente autorizado.

### Puerta agronómica

- Naturaleza del hallazgo explícita.
- Fuente y procedencia verificables.
- Confianza separada de aprobación.
- Recomendaciones visibles como borrador hasta revisión profesional.

### Puerta de modelos

- Versión, artefacto, configuración y dataset de evaluación registrados.
- Champion y Challenger comparados con métricas equivalentes.
- Promoción y rollback aprobados por una persona autorizada.

### Puerta de capacidad y costo

- Tamaños y concurrencia representativos.
- Percentiles, fallos, reintentos y límites medidos.
- Costo por trabajo, almacenamiento, transferencia y ambiente.
- Umbrales de aceptación o rechazo acordados.

### Puerta de continuidad y aceptación

- Respaldo restaurado, no solo creado.
- RPO/RTO medidos.
- Runbooks y responsables transferidos.
- UAT con evidencia y criterios cerrados.

## Próximo ticket

El próximo incremento ejecutable es
[`DBI-AUTH-002` — Resolución canónica de identidad y membresías DBI offline](https://github.com/dalgorosas/dalgoro-banana-intelligence/issues/34).
Su seguimiento corresponde al Issue #34.

La selección se fundamenta en que la política `DBI-AUTH-001` ya existe, pero
ninguna fuente canónica produce todavía el contexto que exige. El ticket puede
validarse completamente offline antes de incorporar FastAPI o una base real.

No debe iniciarse hasta que `DBI-PLAN-001` sea revisado, fusionado y cerrado.

## Criterios de mantenimiento del backlog

- El cierre de cada ticket actualiza este documento y
  `docs/13_CURRENT_STATUS.md`.
- Un ticket dividido conserva trazabilidad hacia el identificador original.
- Un ticket retirado registra motivo y evidencia; no desaparece silenciosamente.
- Las dependencias nuevas no pueden introducir ciclos.
- Los rastreadores #29 a #33 permanecen abiertos hasta cumplir su puerta de
  salida.
- El cierre de un rastreador no autoriza producción por sí solo.

<!-- markdownlint-enable MD013 -->
