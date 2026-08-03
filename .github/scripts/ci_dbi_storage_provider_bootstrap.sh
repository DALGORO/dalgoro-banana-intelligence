#!/usr/bin/env bash
set -euo pipefail

readonly APPROVED_PINNED_REF="docker.io/chrislusf/seaweedfs:4.29@sha256:d47c7ee99fcb951351d7194915f4e3a5ea604a8e8871183d713907dec4fb9bf5"
readonly CONTAINER_NAME="dbi-seaweedfs-ci"
readonly SYNTHETIC_BUCKET="dbi-ci-synthetic"
readonly FORBIDDEN_BUCKET="dbi-ci-forbidden"
readonly HOST_ENDPOINT="http://127.0.0.1:8333"

provided_ref="${1:-}"
if [[ "${provided_ref}" != "${APPROVED_PINNED_REF}" ]]; then
  echo "La referencia de ejecución no coincide con el digest aprobado." >&2
  exit 1
fi

storage_integration_enabled="${DBI_STORAGE_RUN_S3_INTEGRATION:-0}"
asset_integration_enabled="${DBI_ASSET_RUN_INTEGRATION:-0}"
integration_enabled="0"
if [[ "${storage_integration_enabled}" == "1" || "${asset_integration_enabled}" == "1" ]]; then
  integration_enabled="1"
fi
data_tmpfs_size="128m"
tmp_tmpfs_size="32m"
memory_limit="512m"
mini_extra_args=()
iam_config_file=""

if [[ "${integration_enabled}" == "1" ]]; then
  # SeaweedFS mini reserva varios volúmenes para una colección S3. El mínimo
  # oficial es 64 MiB por volumen; 1 GiB temporal permite la prueba sintética
  # sin recurrir a bind mounts o volúmenes persistentes.
  data_tmpfs_size="1024m"
  tmp_tmpfs_size="64m"
  memory_limit="1536m"
  mini_extra_args+=("-master.volumeSizeLimitMB=64")
fi

cleanup() {
  docker rm --force "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  if [[ -n "${iam_config_file}" ]]; then
    rm -f "${iam_config_file}"
  fi
}
trap cleanup EXIT
cleanup

access_key="dbici$(openssl rand -hex 8)"
secret_key="$(openssl rand -hex 32)"
printf '::add-mask::%s\n' "${access_key}"
printf '::add-mask::%s\n' "${secret_key}"
export AWS_ACCESS_KEY_ID="${access_key}"
export AWS_SECRET_ACCESS_KEY="${secret_key}"
export DBI_STORAGE_S3_ENDPOINT_URL="${HOST_ENDPOINT}"
export DBI_STORAGE_S3_BUCKET="${SYNTHETIC_BUCKET}"
export DBI_STORAGE_S3_FORBIDDEN_BUCKET="${FORBIDDEN_BUCKET}"

iam_config_file="$(mktemp)"
chmod 600 "${iam_config_file}"
DBI_STORAGE_IAM_CONFIG_FILE="${iam_config_file}" python - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

bucket = os.environ["DBI_STORAGE_S3_BUCKET"]
access_key = os.environ["AWS_ACCESS_KEY_ID"]
secret_key = os.environ["AWS_SECRET_ACCESS_KEY"]
config_path = Path(os.environ["DBI_STORAGE_IAM_CONFIG_FILE"])
actions = [
    f"Read:{bucket}",
    f"List:{bucket}",
    f"Tagging:{bucket}",
    f"Write:{bucket}",
]
assert "Admin" not in actions
assert all("*" not in action for action in actions)
config = {
    "identities": [
        {
            "name": "dbi-ci-bucket-user",
            "credentials": [
                {
                    "accessKey": access_key,
                    "secretKey": secret_key,
                }
            ],
            "actions": actions,
        }
    ]
}
config_path.write_text(
    json.dumps(config, separators=(",", ":")),
    encoding="utf-8",
)
PY

diagnose_container() {
  if ! docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    echo "Diagnóstico: el contenedor ya no existe." >&2
    return
  fi

  docker inspect "${CONTAINER_NAME}" \
    --format 'Diagnóstico: status={{.State.Status}} exit_code={{.State.ExitCode}} oom_killed={{.State.OOMKilled}} error={{printf "%q" .State.Error}}' \
    >&2 || true

  raw_logs="$(docker logs "${CONTAINER_NAME}" 2>&1 || true)"
  sanitized_logs="${raw_logs//${access_key}/[REDACTED_ACCESS_KEY]}"
  sanitized_logs="${sanitized_logs//${secret_key}/[REDACTED_SECRET_KEY]}"
  if [[ -n "${sanitized_logs}" ]]; then
    echo "Diagnóstico: primeras líneas sanitizadas del proveedor:" >&2
    printf '%s\n' "${sanitized_logs}" | head -n 80 >&2
    echo "Diagnóstico: últimas líneas sanitizadas del proveedor:" >&2
    printf '%s\n' "${sanitized_logs}" | tail -n 200 >&2
  fi
}

docker pull "${APPROVED_PINNED_REF}" >/dev/null

repo_digests="$(docker image inspect "${APPROVED_PINNED_REF}" --format '{{join .RepoDigests "\n"}}')"
if ! grep -F 'sha256:d47c7ee99fcb951351d7194915f4e3a5ea604a8e8871183d713907dec4fb9bf5' <<<"${repo_digests}" >/dev/null; then
  echo "La imagen descargada no conserva el digest aprobado." >&2
  exit 1
fi

docker create \
  --name "${CONTAINER_NAME}" \
  --publish 127.0.0.1:8333:8333 \
  --env "S3_BUCKET=${SYNTHETIC_BUCKET},${FORBIDDEN_BUCKET}" \
  --tmpfs "/data:rw,nosuid,nodev,size=${data_tmpfs_size}" \
  --tmpfs "/tmp:rw,nosuid,nodev,size=${tmp_tmpfs_size}" \
  --cap-drop ALL \
  --cap-add CHOWN \
  --cap-add SETGID \
  --cap-add SETUID \
  --security-opt no-new-privileges:true \
  --pids-limit 256 \
  --memory "${memory_limit}" \
  --cpus 1 \
  "${APPROVED_PINNED_REF}" \
  mini -dir=/data -s3.config=/dbi-s3.json "${mini_extra_args[@]}" >/dev/null

# La credencial es sintética y vive en un runner aislado. Se hace legible solo
# para que el usuario interno elegido por el entrypoint pueda abrirla; el archivo
# del host se elimina inmediatamente después de la copia y el contenedor es
# destruido al finalizar el job.
chmod 644 "${iam_config_file}"
docker cp "${iam_config_file}" "${CONTAINER_NAME}:/dbi-s3.json"
rm -f "${iam_config_file}"
iam_config_file=""

container_environment="$(docker inspect "${CONTAINER_NAME}" --format '{{range .Config.Env}}{{println .}}{{end}}')"
if grep -F "${access_key}" <<<"${container_environment}" >/dev/null \
  || grep -F "${secret_key}" <<<"${container_environment}" >/dev/null; then
  echo "Las credenciales sintéticas no pueden persistir en el entorno del contenedor." >&2
  exit 1
fi

docker start "${CONTAINER_NAME}" >/dev/null

for _ in $(seq 1 60); do
  if ! docker inspect "${CONTAINER_NAME}" --format '{{.State.Running}}' 2>/dev/null | grep -Fx true >/dev/null; then
    echo "SeaweedFS terminó antes de quedar disponible." >&2
    diagnose_container
    exit 1
  fi

  http_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --connect-timeout 1 --max-time 2 "${HOST_ENDPOINT}/" || true)"
  if [[ "${http_code}" != "000" ]]; then
    break
  fi
  sleep 1
done

if [[ "${http_code:-000}" != "403" ]]; then
  echo "El endpoint anónimo debía responder 403 y respondió ${http_code:-000}." >&2
  diagnose_container
  exit 1
fi

port_binding="$(docker port "${CONTAINER_NAME}" 8333/tcp)"
if [[ "${port_binding}" != "127.0.0.1:8333" ]]; then
  echo "El puerto S3 no quedó limitado a loopback: ${port_binding}" >&2
  diagnose_container
  exit 1
fi

persistent_mounts="$(docker inspect "${CONTAINER_NAME}" \
  --format '{{range .Mounts}}{{if or (eq .Type "bind") (eq .Type "volume")}}{{println .Type .Source .Destination}}{{end}}{{end}}')"
if [[ -n "${persistent_mounts}" ]]; then
  echo "El contenedor efímero no puede usar bind mounts o volúmenes persistentes." >&2
  diagnose_container
  exit 1
fi

version_output="$(docker exec "${CONTAINER_NAME}" weed version 2>&1)"
if [[ "${version_output}" != *"4.29"* ]]; then
  echo "La imagen fijada no reportó SeaweedFS 4.29." >&2
  diagnose_container
  exit 1
fi

if [[ "${storage_integration_enabled}" == "1" ]]; then
  if ! python .github/scripts/ci_dbi_storage_s3_integration.py; then
    diagnose_container
    exit 1
  fi
fi

if [[ "${asset_integration_enabled}" == "1" ]]; then
  if ! python .github/scripts/ci_dbi_asset_integration.py; then
    diagnose_container
    exit 1
  fi
fi

container_logs="$(docker logs "${CONTAINER_NAME}" 2>&1 || true)"
if grep -F "${access_key}" <<<"${container_logs}" >/dev/null \
  || grep -F "${secret_key}" <<<"${container_logs}" >/dev/null; then
  echo "Las credenciales sintéticas aparecieron en los logs del proveedor." >&2
  diagnose_container
  exit 1
fi

cleanup
trap - EXIT

if docker ps --all --format '{{.Names}}' | grep -Fx "${CONTAINER_NAME}" >/dev/null; then
  echo "El contenedor efímero no fue eliminado." >&2
  exit 1
fi

printf 'SeaweedFS 4.29 efímero: privacidad, mínimo privilegio y limpieza aprobados.\n'

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "## DBI-STORAGE-001 · proveedor efímero"
    echo
    echo "- Imagen: \`${APPROVED_PINNED_REF}\`"
    echo "- Puerto publicado: \`127.0.0.1:8333\`"
    echo "- Capacidades efectivas: \`CHOWN\`, \`SETGID\`, \`SETUID\`"
    echo "- Identidad S3: limitada a \`${SYNTHETIC_BUCKET}\`; sin acción \`Admin\`"
    echo "- Acceso transversal: \`${FORBIDDEN_BUCKET}\` reservado para prueba negativa"
    echo "- Acceso anónimo: denegado con HTTP 403"
    echo "- Credenciales: ausentes del entorno y los logs del contenedor"
    echo "- Configuración IAM: archivo sintético copiado y eliminado del runner antes del arranque"
    echo "- Datos: exclusivamente objetos sintéticos cuando se activa la integración"
    echo "- Integración de activos DBI: `${asset_integration_enabled}`"
    echo "- Persistencia: tmpfs; sin bind mounts ni volúmenes"
    echo "- Capacidad temporal de integración: \`${data_tmpfs_size}\`"
    echo "- Limpieza: contenedor eliminado al finalizar"
  } >> "${GITHUB_STEP_SUMMARY}"
fi
