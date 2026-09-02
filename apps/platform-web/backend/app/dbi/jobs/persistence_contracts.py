"""Contratos internos inmutables para persistencia de trabajos DBI."""

from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.dbi.jobs.state_machine import AnalysisJobStatus
from app.schemas.dbi_analysis_jobs import OpaqueReference


class AnalysisJobPersistenceConflict(RuntimeError):
    """La intención o el estado persistido entra en conflicto."""


class AnalysisJobResourceUnavailable(LookupError):
    """Un recurso necesario no está disponible en el ámbito exacto."""


class _StrictPersistenceModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
        frozen=True,
    )


class AnalysisJobSnapshot(_StrictPersistenceModel):
    """Vista interna completa necesaria para idempotencia y transiciones."""

    job_id: UUID
    tenant_ref: OpaqueReference
    request_id: OpaqueReference
    correlation_id: OpaqueReference
    farm_id: UUID
    plot_id: UUID
    campaign_id: UUID | None = None
    orthophoto_asset_id: UUID
    boundary_asset_id: UUID
    exclusions_asset_id: UUID | None = None
    model_version_id: OpaqueReference
    pipeline_config_version: OpaqueReference
    requested_by_ref: OpaqueReference
    command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: AnalysisJobStatus
    accepted_at: AwareDatetime
    updated_at: AwareDatetime
