"""Contratos inmutables para planificación preoperativa de muestreo DBI."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.dbi.spatial import GeoJSONMultiPolygon

DBI_SAMPLING_SCHEMA_VERSION = "dbi-sampling-plan.v1"


class _SamplingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class DBISamplingProfile(_SamplingModel):
    """Parámetros operativos versionados; las distancias siempre están en metros."""

    profile_version: str = Field(min_length=1, max_length=64)
    field_budget_minutes: float = Field(gt=0, le=480)
    sample_minutes: float = Field(gt=0, le=30)
    travel_minutes_per_sample: float = Field(ge=0, le=30)
    fixed_overhead_minutes: float = Field(ge=0, le=240, default=0)
    edge_buffer_m: float = Field(ge=0, le=200, default=8)
    min_spacing_m: float = Field(gt=0, le=500, default=25)
    search_radius_m: float = Field(gt=0, le=100, default=12)
    candidate_multiplier: int = Field(ge=8, le=100, default=24)
    reserve_ratio: float = Field(ge=0, le=1, default=0.35)
    min_primary_target: int = Field(ge=1, le=100, default=20)
    max_primary_points: int = Field(ge=1, le=100, default=35)
    max_reserve_points: int = Field(ge=0, le=50, default=12)
    seed: int = Field(ge=0, le=2_147_483_647, default=0)

    @field_validator("profile_version")
    @classmethod
    def require_canonical_version(cls, value: str) -> str:
        if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("profile_version debe ser canónica.")
        return value

    @model_validator(mode="after")
    def validate_operational_budget(self) -> "DBISamplingProfile":
        if self.fixed_overhead_minutes >= self.field_budget_minutes:
            raise ValueError("fixed_overhead_minutes debe ser menor al presupuesto.")
        if self.min_primary_target > self.max_primary_points:
            raise ValueError("min_primary_target no puede superar max_primary_points.")
        return self


class DBISamplingPlanRequest(_SamplingModel):
    tenant_ref: str = Field(min_length=1, max_length=128)
    organization_ref: str = Field(min_length=1, max_length=128)
    farm_id: UUID
    plot_id: UUID
    boundary: GeoJSONMultiPolygon
    exclusions: tuple[GeoJSONMultiPolygon, ...] = ()
    profile: DBISamplingProfile

    @field_validator("tenant_ref", "organization_ref")
    @classmethod
    def require_canonical_scope(cls, value: str) -> str:
        if (
            value != value.strip()
            or "*" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("La referencia de ámbito debe ser canónica.")
        return value


class DBISamplingBudget(_SamplingModel):
    field_budget_minutes: float
    fixed_overhead_minutes: float
    usable_minutes: float
    minutes_per_primary: float
    capacity_points: int = Field(ge=1)
    primary_count: int = Field(ge=1)
    reserve_count: int = Field(ge=0)
    target_status: Literal["below_target", "within_target", "capped"]


class DBISamplingPoint(_SamplingModel):
    point_id: UUID
    role: Literal["primary", "reserve"]
    sequence: int = Field(ge=1)
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    route_order: int | None = Field(default=None, ge=1)
    reserve_for_sequence: int | None = Field(default=None, ge=1)
    status: Literal["planned"] = "planned"
    selection_reason: Literal["balanced", "nearby_reserve"]

    @model_validator(mode="after")
    def validate_role_fields(self) -> "DBISamplingPoint":
        if self.role == "primary":
            if self.route_order is None or self.reserve_for_sequence is not None:
                raise ValueError("Un punto principal requiere route_order y no reserva padre.")
        elif self.route_order is not None or self.reserve_for_sequence is None:
            raise ValueError("Una reserva requiere primary padre y no route_order.")
        return self


class DBISamplingPlan(_SamplingModel):
    schema_version: Literal["dbi-sampling-plan.v1"] = DBI_SAMPLING_SCHEMA_VERSION
    plan_id: UUID
    tenant_ref: str
    organization_ref: str
    farm_id: UUID
    plot_id: UUID
    profile_version: str
    boundary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    exclusions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget: DBISamplingBudget
    points: tuple[DBISamplingPoint, ...]

    @model_validator(mode="after")
    def validate_counts(self) -> "DBISamplingPlan":
        primary = sum(point.role == "primary" for point in self.points)
        reserve = sum(point.role == "reserve" for point in self.points)
        if primary != self.budget.primary_count or reserve != self.budget.reserve_count:
            raise ValueError("El conteo del plan diverge del presupuesto.")
        return self
