# 37 — Resultado de la puerta de proveedor DBI-STORAGE-001

## Propósito

Este documento registra la decisión y evidencia del proveedor de integración
no productivo de `DBI-STORAGE-001`. No selecciona proveedor de producción ni
autoriza infraestructura persistente, datos reales, suscripciones o gasto
externo.

## Identificación

- Ticket: `DBI-STORAGE-001`.
- Issue: #51.
- Pull request: #52.
- Hito: #30.
- SHA funcional auditado:
  `f0aebbad24c0a6f456f0a30a96399d1a37734005`.
- Proveedor de integración: SeaweedFS 4.29 en modo S3.
- Modalidad: contenedor efímero dentro de GitHub Actions.
- Datos: exclusivamente sintéticos.
- Costo directo del proveedor: USD 0,00.

## Decisión aprobada

El usuario aprobó continuar con un adaptador S3-compatible no productivo bajo
estas condiciones:

- MinIO rechazado;
- alternativa mantenida;
- gratuita para la prueba del proveedor;
- sin cuenta cloud, tarjeta o suscripción;
- sin datos reales;
- sin credenciales personales;
- sin infraestructura persistente;
- sin proveedor de producción seleccionado.

SeaweedFS fue elegido únicamente como servicio de compatibilidad S3 para CI.

## Imagen y dependencia

Imagen fijada:

```text
docker.io/chrislusf/seaweedfs:4.29@sha256:d47c7ee99fcb951351d7194915f4e3a5ea604a8e8871183d713907dec4fb9bf5
```

SDK fijado:

```text
boto3==1.43.62
botocore==1.43.62
jmespath==1.1.0
python-dateutil==2.9.0.post0
s3transfer==0.19.2
```

La CI rechaza `latest`, cambios del digest, versiones divergentes, requisitos
rotos, `awscrt` no autorizado y licencias no aprobadas.

## Matriz de la puerta no productiva

| Área | Resultado | Evidencia |
|---|---|---|
| Privacidad | Aprobado | Acceso anónimo devuelve HTTP 403 |
| Imagen | Aprobado | Tag 4.29 fijado por digest SHA-256 |
| IAM | Aprobado | Identidad sin `Admin`, limitada a un bucket |
| Aislamiento | Aprobado | Acceso al bucket sintético prohibido es denegado |
| Credenciales | Aprobado | Sintéticas; no están en entorno ni logs del contenedor |
| Red | Aprobado para CI | Puerto publicado solo en `127.0.0.1:8333` |
| Persistencia | Aprobado para CI | `tmpfs`; sin bind mounts ni volúmenes |
| Integridad | Aprobado | MIME, tamaño y SHA-256 extremo a extremo |
| Escritura condicional | Aprobado | `If-None-Match: *` y conflicto determinista |
| Idempotencia | Aprobado | Reintento exacto devuelve `created=false` |
| Lectura | Aprobado | Flujo privado con verificación de SHA-256 |
| Acceso temporal | Aprobado | SigV4, TTL, modo y metadata completos |
| Retiro lógico | Aprobado | Tags, inaccesibilidad y no reactivación |
| Carga incompleta | Aprobado | Dos fallos recuperados sin residuos |
| Métricas | Aprobado | Operaciones, bytes, duración y errores agregados |
| Logs | Aprobado | Sin secreto, contenido, URL firmada ni clave de objeto |
| Limpieza | Aprobado | Contenedor y datos temporales eliminados |
| Licencias | Aprobado | Apache 2.0, MIT o dual Apache/BSD |
| Datos reales | No utilizados | Solo constantes sintéticas en CI |
| Costo del proveedor | USD 0,00 | Servicio ejecutado dentro del runner |
| TLS remoto | No aplica a CI | HTTP únicamente sobre loopback |
| Cifrado persistente | No aplica a CI | No existe disco persistente; datos en `tmpfs` |
| Producción | No autorizada | Requiere una puerta independiente |

## IAM

Identidad:

```text
dbi-ci-bucket-user
```

Permisos:

```text
Read:dbi-ci-synthetic
List:dbi-ci-synthetic
Tagging:dbi-ci-synthetic
Write:dbi-ci-synthetic
```

Prohibiciones verificadas:

- acción `Admin`;
- wildcard;
- bucket `dbi-ci-forbidden`;
- credencial productiva;
- credencial personal;
- credenciales dentro del entorno del contenedor;
- credenciales en logs.

La configuración IAM es un archivo temporal generado en el runner, copiado al
contenedor antes del arranque y eliminado del runner inmediatamente. El
contenedor y el archivo interno se destruyen al finalizar el job.

## Superficie del contenedor

Controles:

- digest inmutable;
- puerto loopback;
- `cap-drop ALL`;
- capacidades restituidas: `CHOWN`, `SETGID`, `SETUID`;
- `no-new-privileges`;
- límites de CPU, memoria y procesos;
- datos y temporales en `tmpfs`;
- sin bind mounts ni volúmenes;
- eliminación forzada mediante `trap`.

El job de frontera usa límites menores y no escribe objetos. El job funcional
amplía únicamente la capacidad temporal necesaria para los volúmenes internos
de SeaweedFS.

## Escenarios funcionales aprobados

1. Escritura directa de objeto sintético.
2. Reintento exacto idempotente.
3. Conflicto por metadata divergente.
4. Lectura directa con integridad.
5. Grant firmado de carga.
6. Grant firmado de lectura.
7. Acceso anónimo denegado.
8. Bucket fuera del IAM denegado.
9. Retiro lógico idempotente.
10. Lectura de retirado denegada.
11. Reactivación implícita denegada.
12. Carga directa incompleta rechazada antes de contactar el proveedor.
13. Reintento correcto posterior a carga directa fallida.
14. Carga firmada sin header obligatorio rechazada.
15. Confirmación de ausencia del objeto tras la carga firmada fallida.
16. Nuevo grant y carga correcta posterior.
17. Limpieza total del contenedor.

## Métricas auditadas

```text
Duración funcional:            465,1 ms
Objetos sintéticos creados:    4
Bytes sintéticos únicos:       114
Cargas fallidas recuperadas:   2
Costo directo del proveedor:   USD 0,00
```

Operaciones:

```text
generate_presigned_url: 4
get_object:              2
get_object_tagging:     29
head_object:            35
put_object:              9
put_object_tagging:      4
```

Estas métricas no contienen tenant, UUID, objeto, clave, MIME, SHA-256,
contenido, credencial o URL firmada.

La facturación de minutos del runner depende del plan de GitHub. No es un costo
del proveedor S3 y no se autorizó gasto adicional en este ticket.

## Licencias

Componentes agregados:

- SeaweedFS: Apache License 2.0;
- boto3: Apache License 2.0;
- botocore: Apache License 2.0;
- s3transfer: Apache License 2.0;
- jmespath: MIT;
- python-dateutil: licencia dual Apache/BSD.

La prueba del SDK valida la metadata instalada y bloquea marcadores AGPL/GPL no
autorizados dentro del conjunto incorporado por este ticket.

## Cifrado y límites de la evidencia

### Tránsito en CI

El endpoint usa HTTP solo en loopback. Cliente y servidor viven en el mismo
runner y el puerto no escucha en una interfaz pública. Esto es aceptable para la
prueba efímera, pero no equivale a TLS remoto.

### Reposo en CI

No hay almacenamiento persistente. Los objetos viven en `tmpfs` y se destruyen
al finalizar. Por ello no existe una capa persistente cuyo cifrado en reposo
pueda probarse.

### Producción futura

Un proveedor productivo deberá demostrar mediante otro ticket o puerta:

- HTTPS con validación TLS;
- cifrado persistente en reposo;
- administración y rotación de llaves;
- residencia de datos;
- backup, restauración, RPO y RTO;
- retención y purga gobernadas;
- disponibilidad y soporte;
- IAM separado por ambiente;
- costos medidos con datos operativos;
- cumplimiento contractual y regulatorio.

`DBIS3ObjectStoreConfig` ya rechaza HTTP fuera de loopback y HTTPS con
`verify_tls=False`.

## Recuperación demostrada

La integración prueba dos categorías:

### Falla antes del proveedor

Un flujo con menos bytes que los declarados produce `DBIStorageIntegrityError`
sin realizar una llamada `PutObject`. La clave sigue ausente y un reintento
correcto crea el objeto.

### Falla de carga firmada

Un `PUT` firmado al que se elimina un header obligatorio es rechazado. El objeto
permanece ausente; posteriormente se emite otro grant y la carga correcta se
completa.

Estas pruebas cubren recuperación de carga, no restauración de backups
persistentes.

## Evidencia de GitHub Actions

SHA funcional:

```text
f0aebbad24c0a6f456f0a30a96399d1a37734005
```

- `CI modular #540`: 6/6 aprobada.
- `DBI storage provider integration #24`: dos trabajos aprobados.
- `DBI migrations integration #225`: aprobada.

El SHA documental posterior debe repetir las tres workflows antes de marcar el
PR listo.

## Resultado de la puerta

**Aprobado para integración S3 efímera no productiva.**

Esta aprobación permite fusionar:

- contratos proveedor-neutrales;
- adaptador en memoria;
- métricas agregadas;
- adaptador S3-compatible;
- SDK fijado;
- workflow SeaweedFS efímero;
- pruebas sintéticas.

No permite:

- usar datos reales;
- desplegar SeaweedFS;
- seleccionar proveedor productivo;
- crear bucket persistente;
- activar endpoints de carga;
- conectar activos, cola o worker;
- autorizar pagos o suscripciones;
- afirmar cumplimiento de cifrado, residencia o continuidad de producción.
