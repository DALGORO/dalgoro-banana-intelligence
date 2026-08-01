#!/usr/bin/env bash
set -euo pipefail

readonly APPROVED_PINNED_REF="docker.io/chrislusf/seaweedfs:4.29@sha256:d47c7ee99fcb951351d7194915f4e3a5ea604a8e8871183d713907dec4fb9bf5"
readonly CONTAINER_NAME="dbi-seaweedfs-ci"
readonly SYNTHETIC_BUCKET="dbi-ci-synthetic"
readonly HOST_ENDPOINT="http://127.0.0.1:8333"

provided_ref="${1:-}"
if [[ "${provided_ref}" != "${APPROVED_PINNED_REF}" ]]; then
  echo "La referencia de ejecución no coincide con el digest aprobado." >&2
  exit 1
fi

cleanup() {
  docker rm --force "${CONTAINER_NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

access_key="dbici$(openssl rand -hex 8)"
secret_key="$(openssl rand -hex 32)"
printf '::add-mask::%s\n' "${access_key}"
printf '::add-mask::%s\n' "${secret_key}"
export AWS_ACCESS_KEY_ID="${access_key}"
export AWS_SECRET_ACCESS_KEY="${secret_key}"
export S3_BUCKET="${SYNTHETIC_BUCKET}"

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

docker run --detach \
  --name "${CONTAINER_NAME}" \
  --publish 127.0.0.1:8333:8333 \
  --env AWS_ACCESS_KEY_ID \
  --env AWS_SECRET_ACCESS_KEY \
  --env S3_BUCKET \
  --tmpfs /data:rw,nosuid,nodev,size=128m \
  --tmpfs /tmp:rw,nosuid,nodev,size=32m \
  --cap-drop ALL \
  --cap-add CHOWN \
  --cap-add SETGID \
  --cap-add SETUID \
  --security-opt no-new-privileges:true \
  --pids-limit 256 \
  --memory 512m \
  --cpus 1 \
  "${APPROVED_PINNED_REF}" \
  mini -dir=/data >/dev/null

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

printf 'SeaweedFS 4.29 efímero: privacidad y limpieza aprobadas.\n'

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "## DBI-STORAGE-001 · proveedor efímero"
    echo
    echo "- Imagen: \`${APPROVED_PINNED_REF}\`"
    echo "- Puerto publicado: \`127.0.0.1:8333\`"
    echo "- Capacidades efectivas: \`CHOWN\`, \`SETGID\`, \`SETUID\`"
    echo "- Acceso anónimo: denegado con HTTP 403"
    echo "- Credenciales: sintéticas, enmascaradas y no persistidas"
    echo "- Datos: ningún archivo ni activo real"
    echo "- Persistencia: sin bind mounts ni volúmenes"
    echo "- Limpieza: contenedor eliminado al finalizar"
  } >> "${GITHUB_STEP_SUMMARY}"
fi
