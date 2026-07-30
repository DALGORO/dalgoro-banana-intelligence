"""Contratos HTTP estrictos y no sensibles para consultas DBI."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.dbi.spatial import GeoJSONMultiPolygon, boundary_from_database


class _DBIReadModel(BaseModel):
    """Base de solo lectura que rechaza campos no declarados."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class FarmRead(_DBIReadModel):
    id: UUID
    organization_ref: str
    code: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime


class PlotRead(_DBIReadModel):
    """Resumen de lote sin cargar ni transferir geometría completa."""

    id: UUID
    farm_id: UUID
    code: str
    name: str
    area_hectares: Decimal | None
    status: str
    created_at: datetime
    updated_at: datetime


class PlotSpatialRead(PlotRead):
    """Lote con límite GeoJSON para operaciones espaciales explícitas."""

    boundary: GeoJSONMultiPolygon | None

    @field_validator("boundary", mode="before")
    @classmethod
    def serialize_boundary(cls, value: object) -> GeoJSONMultiPolygon | None:
        return boundary_from_database(value)


class CampaignRead(_DBIReadModel):
    id: UUID
    farm_id: UUID
    code: str
    name: str
    starts_at: datetime
    ends_at: datetime | None
    status: str
    created_at: datetime
    updated_at: datetime


class AnalysisJobRead(_DBIReadModel):
    """Estado consultable sin exponer rutas, huellas o referencias de entrada."""

    id: UUID
    request_id: str
    correlation_id: str
    farm_id: UUID
    plot_id: UUID
    campaign_id: UUID | None
    model_version_ref: str
    pipeline_config_version: str
    status: str
    accepted_at: datetime
    created_at: datetime
    updated_at: datetime


class AnalysisInputAssetRead(_DBIReadModel):
    """Metadatos públicos del activo sin clave de objeto ni SHA-256."""

    id: UUID
    farm_id: UUID
    plot_id: UUID | None
    asset_kind: str
    status: str
    content_type: str
    size_bytes: int
    crs: str | None
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AnalysisArtifactRead(_DBIReadModel):
    """Manifiesto consultable sin ubicación privada ni huella criptográfica."""

    id: UUID
    job_id: UUID
    attempt_id: UUID
    manifest_schema_version: str
    role: str
    content_type: str
    size_bytes: int
    produced_by_stage: str
    crs: str | None
    created_at: datetime
