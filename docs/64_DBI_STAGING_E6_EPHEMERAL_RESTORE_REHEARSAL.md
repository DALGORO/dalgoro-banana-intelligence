# DBI-INFRA-006 · Ensayo real de respaldo y restauración PostGIS efímero (E6)

## Alcance: recuperación sintética en CI, nunca staging

El microhito E6 añade un ensayo **real de `pg_dump` y `pg_restore`**
al workflow existente `DBI migrations integration`. Utiliza solo el
contenedor descartable `postgis/postgis:16-3.5` fijado por SHA-256,
en GitHub Actions, con dos bases nuevas identificadas aleatoriamente
(`dbi_e6_src_*`, `dbi_e6_dst_*`). No toca los datos de `dbi_test`
preexistentes, no utiliza los datos de clientes, no accede a Render/S3
y no conecta a staging ni a producción.

### Qué demuestra el ensayo

1. Previo a cualquier comando Docker/SQL exige entorno `test`,
   destino exacto `dbi_test` y rol `dbi_test_migrator` en loopback,
   identidad autorizada de workflow y job de GitHub, runner alojado en
   GitHub y activación explícita para la prueba.
2. Comprueba que exista **un solo** contenedor exponiendo 5432 y que
   su imagen coincida con el digest fijado del servicio PostGIS del
   workflow. No acepta nombres de imagen/host/base externos.
3. Crea origen y destino independientes dentro del contenedor efímero.
   El origen recibe PostGIS, esquema `dbi`, tabla con restricciones
   `PRIMARY KEY`, `UNIQUE`, índice GiST, geometrías Point EPSG:4326 y
   tres filas sintéticas de dos tenants falsos.
4. Genera un archivo personalizado PostgreSQL (formato `-Fc`) con
   `pg_dump`; comprueba su cabecera, tamaño limitado y SHA-256.
   Trunca una **copia** y exige que `pg_restore --list` falle.
5. Elimina una fila del **origen después del dump**: el estado original
   ya no coincide con la huella de referencia. Restaura el dump en
   la base destino con `pg_restore --exit-on-error`.
6. Comprueba el SHA-256 del conjunto de filas, geometrías EWKB, columnas,
   restricciones e índices, igualdad exacta con la instantánea original,
   recuento de tres filas y presencia de dos tenants sintéticos.
7. Borra ambas bases creadas, archivos de respaldo y copia corrupta;
   una limpieza fallida impide que el ensayo aparezca aprobado.

Todo comando usa argumentos separados (sin shell), tiempo límite y
respuesta JSON redactada. No imprime comandos, rutas internas,
credenciales, payloads ni contenido de archivos.

### Integración

- Script: `.github/scripts/ci_dbi_backup_restore_rehearsal.py`.
- Pruebas offline de barreras: `CI modular`, paso
  `--check-guards-offline`, sin Docker ni PostgreSQL.
- Ejecución real: `DBI migrations integration`, paso
  `--rehearse-ci`, después de completar el montaje de DBI test.
- Únicamente un job CI autorizado puede ejecutar la restauración;
  **no existe CLI para hacer backups/restores de staging**.

### Resultado y límites

Éxito del ensayo puede declarar:
`environment=test`,
`pg_dump_restore=COMPLETED`,
`geometry_and_schema=MATCHED`,
`corrupted_archive=REJECTED`,
`cleanup=COMPLETE`.
**No demuestra** la recuperabilidad de una base staging real,
la validez de los respaldos E3, la retención, credenciales, políticas
RPO/RTO, privilegios reales de staging, autenticidad de firmas E5,
cifrado o restauración de S3.

Por tanto, incluso tras un éxito,
`staging_backup_restorability=NOT_VERIFIED`,
`migration_apply=BLOCKED` y
`deployment_readiness=NOT_VERIFIED`.

Las guardas de `migration_cli`, la política de claves E5 y los
algoritmos GIS/Density/YOLO/GOLD/COPA_UP se mantienen intactos.

## Requisito operativo posterior (no realizado)

Un administrador responsable deberá aprobar infraestructura staging
separada, respaldo cifrado y protegido, restauración documentada en
otro entorno segregado, RPO/RTO observados, autenticación externa de
evidencias, roles mínimos y revisión de riesgos. El ensayo CI solo
acredita que el procedimiento técnico básico funciona con un conjunto
sintético y temporal; no se puede utilizar como permiso para aplicar
migraciones staging.
