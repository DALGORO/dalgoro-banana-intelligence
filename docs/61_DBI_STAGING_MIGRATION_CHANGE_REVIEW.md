# DBI-INFRA-003 · Expediente previo a una migración staging (microhito E3)

## Decisión de diseño

La aplicación real de migraciones en staging **permanece bloqueada**. Se
conservan `app.dbi.migration_cli`, `migration_apply.py`, su workflow
de pruebas y la barrera de producción sin modificaciones. Este microhito
entrega un **expediente OFFLINE** que permite vincular una revisión
registrada de staging con la huella del SQL Alembic versionado, así como
registrar las referencias de aprobación y recuperación que deberán
verificarse externamente antes de considerar la ventana de cambio.

Ni un expediente completo ni su estado validado constituyen permiso de
ejecución, prueba restaurada o evidencia autenticada.

## Herramienta y comandos

En entorno backend con dependencias instaladas, sin credenciales reales:

```bash
cd apps/platform-web/backend
python -m app.dbi.staging_migration_change_review --plan
```

El plan utiliza una URL **sintética**, solo para renderizar Alembic
`upgrade head --sql` a través de `migration_plan.generate_offline_plan`.
No instancia motores ni abre conexiones. Emite `head_revision` y
`plan_sha256` del SQL **completo generado**. Esa huella no equivale al
delta de migraciones pendiente ni permite aplicarlo sin revisar el
estado real de la base y el conjunto de revisiones intermedias.

Con un expediente JSON local **fuera de GitHub**, preparado por quienes
gestionan el cambio y sus evidencias:

```bash
python -m app.dbi.staging_migration_change_review --review-packet /ruta/privada/expediente.json
```

El esquema `dbi-staging-change-review.v1` exige exactamente estos campos:

| Campo | Qué representa |
|---|---|
| `schema` | `dbi-staging-change-review.v1` |
| `environment`, `database` | `staging`, `dbi_staging` |
| `current_revision` | Revisión conocida, distinta de HEAD, obtenida de auditoría E2 auténtica |
| `head_revision`, `plan_sha256` | Valores exactos emitidos por `--plan` |
| `change_ticket` | Referencia interna al cambio |
| `operator_ref`, `approver_ref` | Identificadores distintos; aprobación independiente |
| `readonly_verify_report_sha256` | SHA-256 del informe original de auditoría E2 |
| `backup_manifest_sha256` | SHA-256 de manifiesto de respaldo staging |
| `restore_test_report_sha256` | SHA-256 de informe de **restauración ensayada** |
| `rollback_runbook_sha256` | SHA-256 del plan de recuperación por restauración |
| `independent_approval_sha256` | SHA-256 de acta/aprobación del revisor independiente |
| `window_start_utc`, `window_end_utc` | Fechas UTC ISO 8601 `Z`; inicio futuro y en 30 días como máximo, duración máxima de dos horas |

El validador exige campos exactos, tamaño de archivo acotado (8 KiB),
JSON sin claves duplicadas, huellas SHA-256 hexadecimales distintas entre
documentos, referencias sencillas y plazo temporal válido. Si el código
migratorio cambia y con él la huella o HEAD, el expediente anterior queda
invalidado. Cualquier campo extra (URL, contraseña, host, ruta de S3,
token, material sensible) se rechaza.

### Interpretación de la evidencia

Un expediente aceptado responde `packet_structure=VALIDATED`,
`external_evidence=REFERENCED_NOT_AUTHENTICATED`,
`authorization=PENDING_INDEPENDENT_EXTERNAL_REVIEW`,
`migration_apply=BLOCKED` y `deployment_readiness=NOT_VERIFIED`.
El código **no lee ni autentica** los respaldos, el reporte E2, la prueba
de restauración ni el acta externa; solo registra sus huellas declaradas
y verifica la estructura. El SHA-256 del paquete permite compararlo con
el que revisó el responsable, pero no constituye una firma digital ni
acredita autorización. Nunca incluir datos reales o secretos en GitHub.

## Condiciones de una futura autorización separada (NO implementadas)

1. Aprovisionar staging DBI segregado, con PostGIS, TLS y DNS verificados;
   asignar un migrador de mínimo privilegio, distinto del auditor E2.
2. Verificar externamente y con trazabilidad el estado real de
   `dbi.alembic_version_dbi` antes de operar; confirmar revisión base
   sin dependencias desconocidas, múltiples ramas ni drift de esquema.
3. Comprobar respaldo restituible: verificar integridad, ubicación,
   cifrado, accesos, ensayar restauración en ambiente desechable y
   documentar tiempo de recuperación. El rollback no será un
   `alembic downgrade` improvisado ni `stamp`.
4. Revisar el SQL **incremental aplicable a ese estado concreto**,
   riesgos de bloqueos/tiempo de ejecución/compatibilidad de aplicación,
   y aprobar una ventana con responsable independiente.
5. Diseñar aparte un controlador de aplicación staging con barreras
   comprobables, preflight, advisory lock, postflight, auditoría y
   protección absoluta de producción; exigir autorización expresa antes
   de implementar y antes de ejecutar.
6. Mantener el worker GIS desactivado hasta validar S3 privado y
   una prueba piloto multicapa completa autorizada.

## CI

`.github/scripts/ci_dbi_staging_migration_change_review.py` prueba
plan offline sin socket, validación estructural, invalidación ante
plan/HEAD/campaña incorrectos, fuentes duplicadas, evidencia/roles
reutilizados, ventanas inválidas, archivo gigante/symlink, salida
redactada y persistencia de la prohibición de `apply` staging. Se
añade al backend del `CI modular`.

**Resultado de E3:** procedimiento y gate documental, NO deployment,
NO operador de migraciones staging, NO UAT, NO aprobación productiva.
