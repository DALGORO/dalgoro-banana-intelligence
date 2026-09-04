"""Schemas HTTP estrictos para Sampling DBI."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dbi.sampling.contracts import DBISamplingBudget, DBISamplingProfile
from app.dbi.spatial import GeoJSONMultiPolygon

RejectionReason = Literal[
    "road",
    "infrastructure",
    "canal_or_drain",
    "non_banana",
    "missing_plant",
    "inaccessible",
    "unsafe",
    "other",
]


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DBISamplingPlanCreateRequest(_Schema):
    profile: DBISamplingProfile
    exclusions: tuple[GeoJSONMultiPolygon, ...] = ()


class DBISamplingPointResponse(_Schema):
    point_id: UUID
    role: Literal["primary", "reserve"]
    sequence: int
    route_order: int | None
    reserve_for_sequence: int | None
    selection_reason: Literal["balanced", "nearby_reserve"]
    planned_longitude: float
    planned_latitude: float
    observed_longitude: float | None
    observed_latitude: float | None
    status: Literal["planned", "validated", "rejected", "substituted"]
    rejection_reason: RejectionReason | None
    observed_at: datetime | None


class DBISamplingPlanResponse(_Schema):
    plan_id: UUID
    schema_version: str
    profile_version: str
    profile: DBISamplingProfile
    budget: DBISamplingBudget
    boundary_sha256: str
    exclusions_sha256: str
    boundary: GeoJSONMultiPolygon
    exclusions: GeoJSONMultiPolygon | None
    status: Literal["planned", "in_field", "completed", "retired"]
    created_at: datetime
    points: tuple[DBISamplingPointResponse, ...]


class DBISamplingObservationRequest(_Schema):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at debe incluir zona horaria.")
        return value


class DBISamplingRejectRequest(_Schema):
    rejection_reason: RejectionReason
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at debe incluir zona horaria.")
        return value


class DBISamplingSubstituteRequest(DBISamplingObservationRequest):
    reserve_point_id: UUID
    rejection_reason: RejectionReason


class DBISamplingPointMutationResponse(_Schema):
    plan_id: UUID
    point_id: UUID
    reserve_point_id: UUID | None = None
    status: Literal["validated", "rejected", "substituted"]
    changed: bool
    observed_at: datetime


class DBISamplingPlanCompletionResponse(_Schema):
    plan_id: UUID
    status: Literal["completed"]
    changed: bool
