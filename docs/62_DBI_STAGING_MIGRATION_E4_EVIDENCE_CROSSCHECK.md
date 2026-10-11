# DBI-INFRA-004 · Cruce documental E2/E3 para staging (microhito E4)

## Alcance y estado

Este microhito implementa **una simulación offline, no un ejecutor de
migraciones**. Compara el informe de auditoría E2, el expediente E3, la
huella del plan Alembic y los archivos de evidencia disponibles localmente.
No abre conexión SQL/S3, no adquiere un advisory lock, no autoriza el
despliegue ni ejecuta ninguna sentencia de migración. Sigue intacto el
bloqueo del `migration_cli apply` original para staging y producción.

**Una coincidencia de SHA-256 solo acredita que los archivos locales
presentados coinciden con las huellas declaradas; NO autentica los autores
ni demuestra un respaldo restaurable o un visto bueno independiente.**

## Entradas privadas y ejecución

El responsable del cambio prepara fuera del repositorio:

1. El expediente JSON E3 con estructura válida
   (`dbi-staging-change-review.v1`), revisión actual conocida distinta
   de HEAD, plan SHA y ventana futura.
2. Un informe JSON original de `staging_migration_verify` E2 (solo lectura),
   obtenido por el auditor en staging, con `is_at_head=false`,
   `postgis_available=true`, `dbi_schema_available=true` y
   `migration_apply=BLOCKED`.
3. Cuatro archivos correspondientes a las huellas del expediente:
   manifiesto de respaldo, reporte de restauración ensayada,
   procedimiento de reversión y acta de revisión independiente.

La utilidad no genera esos archivos ni solicita claves de conexión:

```bash
cd apps/platform-web/backend
python -m app.dbi.staging_migration_gate_simulation --simulate \
  --packet /ruta/privada/change-packet.json \
  --audit /ruta/privada/readonly-report.json \
  --backup-manifest /ruta/privada/backup-manifest.json \
  --restore-report /ruta/privada/restore-test.txt \
  --rollback-runbook /ruta/privada/recovery-plan.txt \
  --approval-document /ruta/privada/independent-review.txt
```

No subir archivos reales, tokens, rutas ni datos de clientes a GitHub.
En producción o staging real la seguridad de esos documentos y sus
permisos corresponde al administrador del entorno.

## Reglas de rechazo

- Recalcula el plan SQL offline del código actual mediante E3;
  exige que su HEAD/huella concuerden con el expediente.
- Reutiliza E3 para revisar esquema exacto, contexto staging, revisión
  anterior conocida, diferencia de roles y ventana de cambio.
- Verifica el hash **byte a byte** del informe E2 y que el contenido
  sea exactamente el esquema de auditoría esperado: ambiente
  `staging`, base `dbi_staging`, rol auditor E2, revisión anterior
  idéntica al expediente, HEAD de código actual, PostGIS/esquema presentes,
  `is_at_head=false` y `migration_apply=BLOCKED`.
- Recalcula y compara las huellas SHA-256 de los cuatro archivos locales.
  Se rechazan archivos ausentes, vacíos, de tamaño excesivo
  (8 KiB para JSON y 256 KiB para evidencia), enlaces simbólicos,
  FIFOs/no-regulares, inodos repetidos y cambios durante lectura.
  Rechaza JSON con claves duplicadas y campos inesperados.
- Cualquier error produce respuesta redactada y código distinto de cero,
  nunca datos del proveedor, secretos, rutas ni contenido de documentos.

El resultado exitoso indica `local_file_integrity=MATCHED_UNTRUSTED_INPUTS`,
`matched_file_count=6` (expediente, auditoría y cuatro documentos),
`evidence_authenticity=NOT_VERIFIED`,
`backup_restorability=NOT_VERIFIED`,
`approval_authenticity=NOT_VERIFIED`,
`audit_freshness=NOT_VERIFIED`,
`advisory_lock=NOT_ACQUIRED`,
`postflight=NOT_EXECUTED`,
`authorization=PENDING_INDEPENDENT_EXTERNAL_REVIEW`,
`migration_apply=BLOCKED` y `deployment_readiness=NOT_VERIFIED`.

Una auditoría E2 puede alterarse y su huella volver a calcularse: **esta
comprobación NO lo detecta sin una fuente de confianza externa**.
Tampoco confirma que el backup sea útil, que una restauración haya
ocurrido, ni que un actor de confianza haya aprobado realmente el
cambio. No demuestra que una revisión o los permisos no hayan variado
desde que se generó el reporte. Falta esa evidencia operacional.

## Pruebas y etapas posteriores

`.github/scripts/ci_dbi_staging_migration_gate_simulation.py` se ejecuta
en el backend del CI modular. Utiliza solo datos sintéticos y bloquea
sockets. Incluye mutaciones de rol, tenant/base, versión, hash,
PostGIS, ventana, documentos, symlinks, inodos duplicados, JSON malformado
y un intento `--apply`. Ningún test ejecuta migraciones remotas.

**E4 no provee autorización de ejecución.** Para una futura operación
staging deberán diseñarse y aprobarse por separado: identidad confiable
de quien firma los respaldos y la restauración, tiempo de vigencia de
auditoría, revisión incremental del SQL, ventana autorizada, migrador de
mínimos privilegios, lock de sesión, preflight y postflight en una única
conexión, respaldo/restauración comprobados y auditoría externa. El
siguiente microhito debe decidir cómo autenticar esos hechos, con revisión
de riesgos, **antes de escribir un solo registro en staging**.
