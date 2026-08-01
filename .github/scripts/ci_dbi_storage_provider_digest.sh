#!/usr/bin/env bash
set -euo pipefail

readonly APPROVED_IMAGE="docker.io/chrislusf/seaweedfs"
readonly APPROVED_TAG="4.29"
readonly APPROVED_DIGEST="sha256:d47c7ee99fcb951351d7194915f4e3a5ea604a8e8871183d713907dec4fb9bf5"
readonly TAGGED_REF="${APPROVED_IMAGE}:${APPROVED_TAG}"
readonly PINNED_REF="${TAGGED_REF}@${APPROVED_DIGEST}"

if [[ "${APPROVED_TAG}" == "latest" ]]; then
  echo "El proveedor DBI no puede usar la etiqueta latest." >&2
  exit 1
fi

inspect_output="$(docker buildx imagetools inspect "${TAGGED_REF}")"
resolved_digest="$(printf '%s\n' "${inspect_output}" | awk '$1 == "Digest:" {print $2; exit}')"

if [[ ! "${resolved_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "No se pudo resolver un digest OCI válido para ${TAGGED_REF}." >&2
  exit 1
fi

if [[ "${resolved_digest}" != "${APPROVED_DIGEST}" ]]; then
  echo "El tag aprobado cambió de digest; se requiere una nueva auditoría." >&2
  echo "Esperado: ${APPROVED_DIGEST}" >&2
  echo "Resuelto: ${resolved_digest}" >&2
  exit 1
fi

# Verifica además que el registro acepte directamente la referencia inmutable.
docker buildx imagetools inspect "${PINNED_REF}" >/dev/null

printf 'SeaweedFS image tag: %s\n' "${TAGGED_REF}"
printf 'SeaweedFS approved digest: %s\n' "${APPROVED_DIGEST}"
printf 'SeaweedFS pinned reference: %s\n' "${PINNED_REF}"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  printf 'tagged_ref=%s\n' "${TAGGED_REF}" >> "${GITHUB_OUTPUT}"
  printf 'image_digest=%s\n' "${APPROVED_DIGEST}" >> "${GITHUB_OUTPUT}"
  printf 'pinned_ref=%s\n' "${PINNED_REF}" >> "${GITHUB_OUTPUT}"
fi

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "## DBI-STORAGE-001 · imagen fijada"
    echo
    echo "- Tag auditado: \`${TAGGED_REF}\`"
    echo "- Digest aprobado: \`${APPROVED_DIGEST}\`"
    echo "- Referencia inmutable: \`${PINNED_REF}\`"
    echo "- Datos utilizados: ninguno."
  } >> "${GITHUB_STEP_SUMMARY}"
fi
