"""Contratos estrictos del ciclo técnico de campañas DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class DBICampaignConflict(RuntimeError):
    """La campaña solicitada diverge de la identidad o estado persistido."""


class DBICampaignUnavailable(LookupError):
    """La campaña o su ámbito autoritativo no está disponible."""


class DBICampaignAnalysisType(StrEnum):
    """Tipos de análisis previstos por el contrato de campaña."""

    DENSITY = "density"
    MULTISPECTRAL = "multispectral"


class DBICampaignStatus(StrEnum):
    """Estados canónicos del levantamiento técnico."""

    DRAFT = "DRAFT"
    PROCESSING = "PROCESSING"
    ANALYZED = "ANALYZED"
    TECHNICAL_REVIEW = "TECHNICAL_REVIEW"
    SAMPLING_READY = "SAMPLING_READY"
    FIELD_WORK = "FIELD_WORK"
    FIELD_COMPLETED = "FIELD_COMPLETED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"


DBI_CAMPAIGN_TRANSITIONS = MappingProxyType(
    {
        DBICampaignStatus.DRAFT: frozenset({DBICampaignStatus.PROCESSING}),
        DBICampaignStatus.PROCESSING: frozenset({DBICampaignStatus.ANALYZED}),
        DBICampaignStatus.ANALYZED: frozenset(
            {
                DBICampaignStatus.TECHNICAL_REVIEW,
                DBICampaignStatus.SAMPLING_READY,
            }
        ),
        DBICampaignStatus.TECHNICAL_REVIEW: frozenset(
            {DBICampaignStatus.SAMPLING_READY}
        ),
        DBICampaignStatus.SAMPLING_READY: frozenset(
            {DBICampaignStatus.FIELD_WORK}
        ),
        DBICampaignStatus.FIELD_WORK: frozenset(
            {DBICampaignStatus.FIELD_COMPLETED}
        ),
        DBICampaignStatus.FIELD_COMPLETED: frozenset(
            {DBICampaignStatus.APPROVED}
        ),
        DBICampaignStatus.APPROVED: frozenset({DBICampaignStatus.PUBLISHED}),
        DBICampaignStatus.PUBLISHED: frozenset(),
    }
)


def require_campaign_transition(
    current: DBICampaignStatus,
    target: DBICampaignStatus,
) -> None:
    """Acepta replay idempotente y bloquea saltos/regresiones de estado."""

    if target == current:
        return
    if target not in DBI_CAMPAIGN_TRANSITIONS[current]:
        raise DBICampaignConflict(
            f"Transición de campaña no permitida: {current.value} -> {target.value}."
        )


class _CampaignModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class DBICampaignCreate(_CampaignModel):
    """Identidad idempotente y momento real de una nueva campaña."""

    campaign_id: UUID
    analysis_type: DBICampaignAnalysisType = DBICampaignAnalysisType.DENSITY
    captured_at: datetime

    @field_validator("captured_at")
    @classmethod
    def require_aware_capture(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at debe incluir zona horaria.")
        return value.astimezone(timezone.utc)


class DBICampaignSnapshot(_CampaignModel):
    """Vista pública del estado persistido de una campaña técnica."""

    campaign_id: UUID
    tenant_ref: str
    organization_ref: str
    farm_id: UUID
    plot_id: UUID
    analysis_type: DBICampaignAnalysisType
    captured_at: datetime
    processed_at: datetime | None
    status: DBICampaignStatus
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None
    field_started_at: datetime | None
    field_completed_at: datetime | None
    approved_at: datetime | None
    published_at: datetime | None
    current_revision_id: UUID | None
    source_job_id: UUID | None
