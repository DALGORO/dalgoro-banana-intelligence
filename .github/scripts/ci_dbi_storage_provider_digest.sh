#!/usr/bin/env bash
set -euo pipefail

readonly APPROVED_IMAGE="docker.io/chrislusf/seaweedfs"
readonly APPROVED_TAG="4.29"
readonly IMAGE_REF="${APPROVED_IMAGE}:${APPROVED_TAG}"

if [[ "${APPROVED_TAG}" == "latest" ]]; then
  echo "El proveedor DBI no puede usar la etiqueta latest." >&2
  exit 1
fi

inspect_output="$(docker buildx imagetools inspect "${IMAGE_REF}")"
digest="$(printf '%s\n' "${inspect_output}" | awk '$1 == "Digest:" {print $2; exit}')"

if [[ ! "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "No se pudo resolver un digest OCI válido para ${IMAGE_REF}." >&2
  exit 1
fi

printf 'SeaweedFS image tag: %s\n' "${IMAGE_REF}"
printf 'SeaweedFS image digest: %s\n' "${digest}"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  printf 'image_ref=%s\n' "${IMAGE_REF}" >> "${GITHUB_OUTPUT}"
  printf 'image_digest=%s\n' "${digest}" >> "${GITHUB_OUTPUT}"
fi

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "## DBI-STORAGE-001 · digest de proveedor"
    echo
    echo "- Imagen aprobada: \`${IMAGE_REF}\`"
    echo "- Digest resuelto: \`${digest}\`"
    echo "- Operación: inspección del manifiesto OCI; la imagen no fue ejecutada."
    echo "- Datos utilizados: ninguno."
  } >> "${GITHUB_STEP_SUMMARY}"
fi
