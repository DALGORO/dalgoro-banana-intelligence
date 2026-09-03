"""Contratos HTTP públicos para mutaciones de trabajos geoespaciales DBI."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.dbi.jobs.state_machine import AnalysisJobStatus

ANALYSIS_JOB_TRANSITION_SCHEMA_VERSION = "dbi-analysis-job-transition.v1"


class _StrictJobAPIModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
        frozen=True,
    )


class AnalysisJobTransitionResponse(_StrictJobAPIModel):
    """Respuesta acotada de cancelación o reintento."""

    schema_version: Literal["dbi-analysis-job-transition.v1"] = (
        ANALYSIS_JOB_TRANSITION_SCHEMA_VERSION
    )
    job_id: UUID
    status: AnalysisJobStatus
    accepted_at: AwareDatetime
    updated_at: AwareDatetime
    changed: bool
