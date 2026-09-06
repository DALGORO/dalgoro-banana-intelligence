"""Esquemas HTTP de INSPECT sin autoridad de tenant/alcance en el cliente."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.dbi.inspection.contracts import (
    DBICoreObservation,
    DBIDiagnosticObservation,
    DBIGPSFix,
    DBIStructuralObservation,
)


class _InspectionAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class DBIFieldObservationBody(_InspectionAPIModel):
    """Dato observado enviado por campo; el servidor fija identidad y alcance."""

    observed_at: datetime
    gps_fix: DBIGPSFix | None = None
    sampling_point_id: UUID | None = None
    up_id: UUID | None = None
    core: DBICoreObservation
    structural: DBIStructuralObservation | None = None
    diagnostic: DBIDiagnosticObservation | None = None


class DBIFieldObservationCreateRequest(_InspectionAPIModel):
    observation: DBIFieldObservationBody


class DBIFieldObservationCorrectionRequest(_InspectionAPIModel):
    base_version_id: UUID
    correction_reason: str = Field(min_length=1, max_length=500)
    observation: DBIFieldObservationBody


class DBIFieldObservationUPAssociationRequest(_InspectionAPIModel):
    """Asocia una UP confirmada sin reescribir la evidencia observada."""

    base_version_id: UUID
    up_id: UUID
    confirmation: Literal["unequivocal"]
    association_reason: str = Field(min_length=1, max_length=450)
