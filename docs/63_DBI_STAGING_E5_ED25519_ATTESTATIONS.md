# DBI-INFRA-005 · Firmas digitales de auditoría y revisión de staging (E5)

## Alcance y política de seguridad

El E5 implementa exclusivamente un **verificador local** de dos
atestaciones Ed25519: una del auditor E2 sobre los bytes de su informe
y otra del revisor independiente sobre el SHA-256 canónico del expediente
E3. Antes verifica E4 (referencias, plan SQL y archivos con SHA-256).

**No** crea usuarios o claves, no firma documentos, no se conecta a S3,
PostgreSQL ni Render, no comprueba restaurabilidad del respaldo, no
adquiere advisory locks y nunca aplica, aprueba ni programa migraciones.
El controlador de migraciones CI-test permanece sin cambios. Las firmas
no implican que la aprobación esté autorizada por una autoridad real,
salvo que la política de claves y sus custodios estén provisionados y
verificados por un mecanismo externo confiable.

## Custodia externa de claves

- El administrador independiente aprovisionará **dos pares de claves
  Ed25519 separados** mediante un mecanismo corporativo aprobado:
  una clave del auditor staging y otra del aprobador independiente.
  Se prohíbe generar, almacenar o subir claves privadas a GitHub.
- Una política JSON local, fuera del repositorio y de acceso restringido,
  contiene **solo claves públicas**. Debe ser un archivo regular,
  propiedad del operador local o root, no modificable por grupo ni otros.
- El SHA-256 de los bytes de la política debe distribuirse mediante un
  canal separado y controlado por un custodio de confianza, y se aporta
  con la variable `DBI_STAGING_TRUST_POLICY_SHA256`. Una política
  autocontenida, sin pin separado, se rechaza.
- Si un operador puede sustituir **tanto** la política como su pin,
  el verificador no garantiza origen ni independencia. La custodia,
  revocación, rotación y control de acceso requieren validación humana.
  No se admiten automáticamente claves desconocidas, y una rotación
  invalida las firmas hasta publicar un nuevo pin aprobado.

Ejemplo *de esquema*, sin claves reales:

```json
{
  "schema": "dbi-staging-trust-policy.v1",
  "environment": "staging",
  "database": "dbi_staging",
  "keys": [
    {
      "key_id": "audit_key01",
      "principal_ref": "audit_ci01",
      "role": "staging_auditor",
      "public_key_b64": "BASE64_DE_32_BYTES_DE_CLAVE_PUBLICA"
    },
    {
      "key_id": "review_key01",
      "principal_ref": "approver_ci01",
      "role": "independent_approver",
      "public_key_b64": "OTRA_CLAVE_PUBLICA_BASE64_DE_32_BYTES"
    }
  ]
}
```

Estos valores son **marcadores**, no una política operativa. El
verificador exige dos identidades y claves públicas distintas.

## Formato de cada atestación

Los firmantes generan **fuera del repositorio** un JSON UTF-8 con todos
los campos siguientes: `schema=dbi-staging-attestation.v1`,
`purpose` (`audit_report` o `change_approval`), `signer_ref`,
`key_id`, `environment=staging`, `database=dbi_staging`,
`artifact_sha256`, `head_revision`, `current_revision`,
`plan_sha256`, `change_ticket`, `window_start_utc`,
`window_end_utc`, `issued_at_utc`, `expires_at_utc` y
`signature_b64`.

El payload firmado **excluye solo** `signature_b64`: JSON de los
campos restantes con claves ordenadas, separadores `,` y `:`,
`ensure_ascii=true`, UTF-8; la firma Ed25519 de 64 bytes se
codifica en base64 estándar. No se permiten campos adicionales,
alias de algoritmo, algoritmos alternativos ni tokens arbitrarios.

El auditor firma el SHA-256 de **los bytes originales** del informe E2;
el revisor firma el `packet_sha256` canónico generado por E3. Ambas
atestaciones quedan ligadas al mismo cambio, ventana, revisión de
origen, HEAD y plan SQL. La identidad del aprobador debe coincidir con
`approver_ref` de E3; auditor, aprobador y operador deben ser
diferentes. Los límites de antigüedad y vigencia son 15 minutos para
el auditor y 24 horas para el aprobador, con expiración anterior al
final de la ventana E3. El reloj usado es el del host local, no un
sello de tiempo emitido por un tercero.

## Entrada de verificación

Desde la carpeta `apps/platform-web/backend`, en un equipo confiable
y con todos los archivos bajo custodia local:

```bash
python -m app.dbi.staging_migration_signed_evidence --verify-signatures \
  --packet /ruta/privada/packet.json \
  --audit /ruta/privada/e2-audit.json \
  --backup-manifest /ruta/privada/backup.json \
  --restore-report /ruta/privada/restore.txt \
  --rollback-runbook /ruta/privada/rollback.txt \
  --approval-document /ruta/privada/approval.txt \
  --trust-policy /ruta/privada/trust-policy.json \
  --audit-attestation /ruta/privada/audit-attestation.json \
  --approval-attestation /ruta/privada/approval-attestation.json
```

Se requiere `DBI_STAGING_TRUST_POLICY_SHA256` configurada
independientemente. El resultado exitoso informa
`verified_signature_count=2`,
`signature_scope=PINNED_POLICY_KEYS_ONLY`,
`trust_policy_pin=MATCHED_UNVERIFIED_CUSTODY`,
`approval_authority=NOT_EXTERNALLY_VERIFIED`,
`audit_freshness=SIGNATURE_TIME_ONLY` y
`evidence_authenticity=OTHER_EVIDENCE_NOT_ATTESTED`.

**Siempre** informa `migration_apply=BLOCKED`,
`authorization=PENDING_INDEPENDENT_EXTERNAL_REVIEW`,
`backup_restorability=NOT_VERIFIED` y
`deployment_readiness=NOT_VERIFIED`, aunque las firmas validen.
El script no incorpora ninguna operación para firmar ni un `apply`.

## CI, amenazas residuales y próximo microhito

La prueba `.github/scripts/ci_dbi_staging_signed_evidence.py` usa
claves privadas **efímeras y solo sintéticas** dentro del proceso CI;
no guarda ni distribuye archivos privados de claves. Comprueba firmas
válidas, firmas falsificadas, claves intercambiadas, roles duplicados,
alteración de ticket/HEAD/huella, caducidad, claves desconocidas,
política modificada, permisos inseguros, documentos mutados y bloqueo
de red/`--apply`.

Estas firmas **no prueban** que un backup fue restaurado realmente,
que el contenido documental sea verdadero, que el custodio de la
política sea confiable, que el firmante mantenga su autoridad ni que
staging siga en la misma revisión en el instante de un futuro cambio.
Por ello aún no hay base operativa para activar migraciones. El próximo
microhito debe abordar evidencia verificable de respaldo/restauración
y custodia de claves desde una fuente independiente, antes de diseñar
cualquier ejecutor staging.
