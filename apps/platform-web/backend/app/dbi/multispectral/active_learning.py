"""Contrato advisory para devolver prioridades MULTI a DBI-SAMPLING-001.

Este módulo no muta planes Sampling ni crea observaciones. Expresa una inferencia
versionada que el plano de control puede consumir posteriormente con autorización.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DBI_SAMPLING_PRIORITY_SCHEMA_VERSION = "dbi-sampling-priority.v1"

DBISamplingPriorityReason = Literal[
    "anomaly",
    "low_confidence",
    "underrepresented_class",
    "model_disagreement",
    "healthy_control",
    "novel_pattern",
]

_MODEL_REASONS = frozenset(
    {"anomaly", "low_confidence", "model_disagreement", "novel_pattern"}
)


class _PriorityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class DBISamplingPriorityCandidate(_PriorityModel):
    """Una prioridad inferida; nunca equivale a una observación ni mueve una UP."""

    schema_version: Literal["dbi-sampling-priority.v1"] = (
        DBI_SAMPLING_PRIORITY_SCHEMA_VERSION
    )
    tenant_ref: str = Field(min_length=1, max_length=128)
    organization_ref: str = Field(min_length=1, max_length=128)
    farm_id: UUID
    plot_id: UUID
    target_kind: Literal["up", "sampling_point"]
    target_id: UUID
    priority_score: float = Field(gt=0, le=1)
    uncertainty: float = Field(ge=0, le=1)
    reason_codes: tuple[DBISamplingPriorityReason, ...] = Field(min_length=1, max_length=6)
    source_kind: Literal["model", "dataset", "audit"]
    source_ref: str = Field(min_length=1, max_length=128)
    source_version: str = Field(min_length=1, max_length=128)
    evidence_kind: Literal["inferred"] = "inferred"
    recommendation_mode: Literal["advisory"] = "advisory"

    @field_validator(
        "tenant_ref",
        "organization_ref",
        "source_ref",
        "source_version",
    )
    @classmethod
    def require_canonical_ref(cls, value: str) -> str:
        if (
            value != value.strip()
            or "*" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("La referencia de prioridad debe ser canónica.")
        return value

    @model_validator(mode="after")
    def validate_priority_semantics(self) -> "DBISamplingPriorityCandidate":
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes no admite duplicados.")
        if _MODEL_REASONS.intersection(self.reason_codes) and self.source_kind != "model":
            raise ValueError(
                "Anomalía/confianza/discrepancia/novedad requieren provenance de modelo."
            )
        return self


class DBISamplingPriorityBatch(_PriorityModel):
    """Lote advisory homogéneo por tenant/finca/lote y perfil versionado."""

    schema_version: Literal["dbi-sampling-priority.v1"] = (
        DBI_SAMPLING_PRIORITY_SCHEMA_VERSION
    )
    tenant_ref: str = Field(min_length=1, max_length=128)
    organization_ref: str = Field(min_length=1, max_length=128)
    farm_id: UUID
    plot_id: UUID
    priority_profile_version: str = Field(min_length=1, max_length=128)
    candidates: tuple[DBISamplingPriorityCandidate, ...] = Field(min_length=1)
    evidence_kind: Literal["inferred"] = "inferred"
    recommendation_mode: Literal["advisory"] = "advisory"

    @field_validator("tenant_ref", "organization_ref", "priority_profile_version")
    @classmethod
    def require_canonical_ref(cls, value: str) -> str:
        if (
            value != value.strip()
            or "*" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("La referencia del lote de prioridades debe ser canónica.")
        return value

    @model_validator(mode="after")
    def validate_batch_scope(self) -> "DBISamplingPriorityBatch":
        expected_scope = (
            self.tenant_ref,
            self.organization_ref,
            self.farm_id,
            self.plot_id,
        )
        targets: set[tuple[str, UUID]] = set()
        for candidate in self.candidates:
            actual_scope = (
                candidate.tenant_ref,
                candidate.organization_ref,
                candidate.farm_id,
                candidate.plot_id,
            )
            if actual_scope != expected_scope:
                raise ValueError("Todas las prioridades deben pertenecer al mismo scope DBI.")
            target = (candidate.target_kind, candidate.target_id)
            if target in targets:
                raise ValueError("Un target no puede repetirse dentro del mismo lote advisory.")
            targets.add(target)
        return self


def rank_sampling_priorities(
    batch: DBISamplingPriorityBatch,
    *,
    limit: int | None = None,
) -> tuple[DBISamplingPriorityCandidate, ...]:
    """Ranking puro y determinista; no cambia estado de Sampling."""

    if not isinstance(batch, DBISamplingPriorityBatch):
        batch = DBISamplingPriorityBatch.model_validate(batch)
    if limit is not None and limit < 1:
        raise ValueError("limit debe ser positivo cuando se especifica.")

    ordered = tuple(
        sorted(
            batch.candidates,
            key=lambda item: (
                -item.priority_score,
                -item.uncertainty,
                item.target_kind,
                str(item.target_id),
            ),
        )
    )
    return ordered if limit is None else ordered[:limit]


def sampling_priority_fingerprint(batch: DBISamplingPriorityBatch) -> str:
    """Fingerprint reproducible e independiente del orden de entrada."""

    if not isinstance(batch, DBISamplingPriorityBatch):
        batch = DBISamplingPriorityBatch.model_validate(batch)
    payload = batch.model_dump(mode="json")
    payload["candidates"] = [
        item.model_dump(mode="json") for item in rank_sampling_priorities(batch)
    ]
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
