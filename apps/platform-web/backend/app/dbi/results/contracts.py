"""Contratos puros para validar y canonizar `analysis-job-result.v1`."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.dbi.delivery.contracts import prepare_delivery_payload
from app.schemas.dbi_analysis_jobs import AnalysisJobResult, ArtifactManifest


class DBIResultIngestionConflict(RuntimeError):
    """El resultado no coincide con la autoridad operacional o persistida."""


class DBIResultIngestionUnavailable(LookupError):
    """Un recurso requerido por el resultado no está disponible."""


class DBIResultAckPending(RuntimeError):
    """La ingesta ya fue confirmada pero falta ACK del transporte."""


class DBIResultFailureCode(StrEnum):
    """Códigos acotados aptos para nack/dead-letter sin datos sensibles."""

    INVALID_RESULT = "RESULT_INVALID"
    CONFLICT = "RESULT_CONFLICT"
    RESOURCE_UNAVAILABLE = "RESULT_RESOURCE_UNAVAILABLE"
    INTERNAL_FAILURE = "RESULT_INTERNAL"


@dataclass(frozen=True, slots=True)
class CanonicalJsonPayload:
    json_text: str
    sha256: str


@dataclass(frozen=True, slots=True)
class PreparedAnalysisResult:
    result: AnalysisJobResult
    result_sha256: str
    metrics: CanonicalJsonPayload
    findings: CanonicalJsonPayload
    warnings: CanonicalJsonPayload
    errors: CanonicalJsonPayload
    artifact_ids: frozenset[UUID]


class ResultIngestionEvidence(BaseModel):
    """Evidencia pequeña de una ingesta/ACK sin payloads de dominio."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: UUID
    job_id: UUID
    attempt_id: UUID
    status: str
    created: bool
    artifact_count: int
    acknowledged: bool


def canonical_uuid(value: str, *, field_name: str) -> UUID:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as error:
        raise DBIResultIngestionConflict(
            f"{field_name} debe ser UUID canónico."
        ) from error
    if value != str(parsed):
        raise DBIResultIngestionConflict(
            f"{field_name} debe ser UUID canónico."
        )
    return parsed


def canonical_json(
    value: Any,
    *,
    field_name: str,
    max_bytes: int,
) -> CanonicalJsonPayload:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise DBIResultIngestionConflict(
            f"{field_name} no puede serializarse canónicamente."
        ) from error
    raw = text.encode("utf-8")
    if not 2 <= len(raw) <= max_bytes:
        raise DBIResultIngestionConflict(
            f"{field_name} excede el tamaño permitido."
        )
    return CanonicalJsonPayload(
        json_text=text,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _artifact_id_set(artifacts: list[ArtifactManifest]) -> frozenset[UUID]:
    values: set[UUID] = set()
    roles: set[str] = set()
    for manifest in artifacts:
        artifact_id = canonical_uuid(
            manifest.artifact_id,
            field_name="artifact.artifact_id",
        )
        role = manifest.role.value
        if artifact_id in values:
            raise DBIResultIngestionConflict(
                "artifact_id duplicado dentro del resultado."
            )
        if role in roles:
            raise DBIResultIngestionConflict(
                "role de artifact duplicado dentro del resultado."
            )
        values.add(artifact_id)
        roles.add(role)
    return frozenset(values)


def prepare_analysis_result(result: AnalysisJobResult) -> PreparedAnalysisResult:
    """Aplica semántica V1 y fija JSON/huellas antes de persistencia."""

    if not isinstance(result, AnalysisJobResult):
        raise DBIResultIngestionConflict("result debe ser AnalysisJobResult.")

    artifact_ids = _artifact_id_set(result.artifacts)
    if result.status in {"failed", "canceled"}:
        if result.artifacts:
            raise DBIResultIngestionConflict(
                "failed/canceled no puede oficializar artifacts en V1."
            )
        if result.findings:
            raise DBIResultIngestionConflict(
                "failed/canceled no puede oficializar findings en V1."
            )
    elif result.errors:
        raise DBIResultIngestionConflict(
            "succeeded no puede contener errores terminales."
        )

    for finding in result.findings:
        for source_ref in finding.source_artifact_ids:
            if canonical_uuid(
                source_ref,
                field_name="finding.source_artifact_ids",
            ) not in artifact_ids:
                raise DBIResultIngestionConflict(
                    "finding referencia un artifact ajeno al resultado."
                )

    metrics = canonical_json(
        result.metrics,
        field_name="metrics",
        max_bytes=65_536,
    )
    findings = canonical_json(
        [item.model_dump(mode="json") for item in result.findings],
        field_name="findings",
        max_bytes=262_144,
    )
    warnings = canonical_json(
        result.warnings,
        field_name="warnings",
        max_bytes=65_536,
    )
    errors = canonical_json(
        result.errors,
        field_name="errors",
        max_bytes=65_536,
    )
    payload = prepare_delivery_payload(result)

    return PreparedAnalysisResult(
        result=result,
        result_sha256=payload.payload_sha256,
        metrics=metrics,
        findings=findings,
        warnings=warnings,
        errors=errors,
        artifact_ids=artifact_ids,
    )
