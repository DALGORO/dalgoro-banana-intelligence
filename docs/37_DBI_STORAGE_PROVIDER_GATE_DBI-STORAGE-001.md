# 37 — Puerta de proveedor para almacenamiento privado DBI-STORAGE-001

## Propósito

Este documento define las capacidades mínimas que debe demostrar cualquier
proveedor o adaptador real antes de incorporarse a DALGORO Banana Intelligence.
No selecciona un servicio, no autoriza producción y no introduce precios no
medidos.

## Estado

- Ticket: `DBI-STORAGE-001`.
- Issue: #51.
- Pull request: #52.
- Etapa A: contratos, política, adaptador en memoria y métricas en construcción.
- Etapa B: bloqueada hasta aprobación explícita del proveedor no productivo.

## Principio de portabilidad

El dominio DBI depende exclusivamente de `DBIPrivateObjectStore`. Un adaptador
real debe traducir errores, metadatos y acceso temporal hacia ese puerto sin
filtrar al dominio:

- nombre de bucket o contenedor;
- hostname o endpoint;
- región;
- URL firmada;
- credencial;
- ETag específico;
- identificador de cuenta del proveedor;
- ruta local;
- clase del SDK.

## Matriz obligatoria de capacidades

| Área | Evidencia mínima exigida |
|---|---|
| Privacidad | Contenedor privado por defecto y prueba negativa de acceso anónimo |
| IAM | Identidad no humana de mínimo privilegio, sin administración global |
| Aislamiento | Prefijo o política que impida acceso transversal entre tenants |
| Cifrado en tránsito | TLS verificado, sin opción de transporte plano |
| Cifrado en reposo | Cifrado habilitado y responsabilidad de claves documentada |
| Integridad | Verificación de tamaño y SHA-256 extremo a extremo |
| Escritura condicional | Crear o aceptar reintento exacto sin sobrescritura silenciosa |
| Lectura | Flujo binario privado, acotable y sin descarga pública permanente |
| Acceso temporal | Operación y TTL explícitos; firma no persistida como autoridad |
| Retiro | Marcado lógico inmediato; purga física gobernada por retención |
| Multipartes | Aborto y limpieza demostrables de cargas incompletas |
| Auditoría | Actor técnico, operación, resultado y fecha sin contenido o firma |
| Métricas | Operaciones, bytes, latencia y errores sin claves completas |
| Recuperación | Restauración o recuperación de versión probada en no producción |
| Retención | Reglas declarativas, excepciones legales y costos documentados |
| Residencia | Región y transferencias internacionales identificadas |
| Disponibilidad | Objetivo publicado y comportamiento ante degradación probado |
| Límites | Tamaño, tasa, concurrencia y número de objetos conocidos |
| SDK | Versión fijada, licencia compatible y vulnerabilidades auditadas |
| Pruebas | Ambiente efímero o aislado reproducible sin credenciales personales |

## Política de credenciales

El adaptador real deberá usar configuración externa y una identidad técnica
separada por ambiente. Queda prohibido:

- incluir secretos en el repositorio;
- usar credenciales personales del desarrollador;
- registrar firmas, tokens o cabeceras de autorización;
- aceptar credenciales dentro de contratos del dominio;
- reutilizar credenciales de producción en CI;
- permitir que el worker herede privilegios administrativos del backend.

## Política de acceso temporal

Toda concesión deberá vincular:

- dirección canónica DBI;
- modo de lectura o escritura;
- fecha de emisión UTC;
- fecha de expiración UTC;
- TTL dentro de la política DBI;
- metadatos de integridad cuando el proveedor lo permita.

La representación específica del proveedor podrá existir únicamente dentro del
adaptador y durante la respuesta operativa. No se almacenará en tablas DBI,
logs, eventos, métricas ni documentos técnicos.

## Modelo de costos a medir

No se aprobará un proveedor solo por el precio nominal por gigabyte. El piloto
debe medir o estimar con evidencia:

```text
Costo mensual total =
  almacenamiento activo
+ almacenamiento retenido o versionado
+ solicitudes de escritura
+ solicitudes de lectura y metadatos
+ recuperación o transición de clase
+ transferencia de salida
+ replicación o residencia adicional
+ logs, auditoría y monitoreo
+ llaves administradas, si aplican
```

Escenarios mínimos:

1. Carga de ortofoto RGB individual.
2. Carga multiespectral con varias bandas.
3. Reintento idempotente de carga.
4. Lectura parcial o repetida durante procesamiento.
5. Publicación de varios artefactos derivados.
6. Retención de campañas históricas.
7. Recuperación de un objeto retirado o versionado.
8. Transferencia entre región de almacenamiento y cómputo.

Los valores monetarios deberán registrarse con fecha, región, moneda, unidad y
fuente. Ningún precio se codificará dentro del dominio.

## Recuperación y continuidad

Antes de aprobar un adaptador real deben definirse y probarse:

- qué significa pérdida de objeto frente a pérdida de metadatos DBI;
- orden de restauración entre PostgreSQL y objetos;
- detección de objetos huérfanos y metadatos sin objeto;
- recuperación de carga multipart incompleta;
- restauración de una versión o copia protegida;
- comportamiento cuando el proveedor está disponible pero degradado;
- procedimiento cuando las credenciales son revocadas;
- evidencia de que una recuperación no reactiva objetos retirados por error.

Los objetivos RPO y RTO no se fijarán sin una medición del piloto y aprobación
operativa.

## Retención

`DBI-STORAGE-001` define retiro lógico, no purga física. Una política posterior
de retención deberá establecer:

- período mínimo por propósito;
- excepciones por investigación, contrato o regulación;
- tratamiento de objetos en cuarentena;
- versionado o bloqueo, si aplica;
- autorización de purga;
- evidencia de purga;
- efecto económico del almacenamiento retenido.

## Criterios para aprobar el proveedor no productivo

La aprobación debe quedar escrita en el Issue #51 e incluir:

- proveedor y servicio exactos;
- región o ubicación de prueba;
- modalidad administrada o autogestionada;
- justificación técnica y económica;
- identidad técnica y permisos previstos;
- variables de configuración permitidas;
- dependencia o imagen fijada;
- estrategia de ambiente efímero o aislado;
- límites conocidos;
- plan de reversión;
- responsable de costos.

Sin esa aprobación no se añadirá SDK, contenedor, bucket, endpoint ni workflow de
integración del proveedor.

## Opciones de decisión posteriores

La comparación futura puede incluir servicios administrados o compatibles con
la semántica requerida, pero la selección se hará con información vigente y
verificada en el momento de la decisión. Este documento no convierte ninguna
marca o tecnología en opción predeterminada.
