"""Schemas HTTP del dominio técnico Campaign DBI."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.dbi.campaigns.contracts import (
    DBICampaignAnalysisType,
    DBICampaignCreate,
    DBICampaignSnapshot,
    DBICampaignStatus,
)


class _CampaignAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DBICampaignCreateRequest(_CampaignAPIModel):
    campaign_id: UUID
    analysis_type: DBICampaignAnalysisType = DBICampaignAnalysisType.DENSITY
    captured_at: datetime

    def to_contract(self) -> DBICampaignCreate:
        return DBICampaignCreate.model_validate(self.model_dump())


class DBICampaignTransitionRequest(_CampaignAPIModel):
    status: DBICampaignStatus


class DBICampaignResponse(_CampaignAPIModel):
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
    created: bool | None = None

    @classmethod
    def from_snapshot(
        cls,
        snapshot: DBICampaignSnapshot,
        *,
        created: bool | None = None,
    ) -> "DBICampaignResponse":
        return cls(**snapshot.model_dump(), created=created)
