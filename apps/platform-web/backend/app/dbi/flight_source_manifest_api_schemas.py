"""Esquemas HTTP seguros para manifiestos de fuentes de vuelo DBI."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _ManifestAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _canonical_ref(value: object, field_name: str) -> object:
    if not isinstance(value, str):
        return value
    if (
        value != value.strip()
        or "*" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{field_name} debe ser canónica.")
    return value


class DBIFlightSourceEntryRequest(_ManifestAPIModel):
    asset_id: UUID
    logical_name: str = Field(min_length=1, max_length=512)
    role: Literal["source_photo", "auxiliary"]
    sensor_camera: str | None = Field(default=None, min_length=1, max_length=160)
    captured_at: datetime | None = None

    @field_validator("logical_name", "sensor_camera", mode="before")
    @classmethod
    def canonical_text(cls, value: object, info) -> object:
        if value is None:
            return value
        return _canonical_ref(value, info.field_name)


class DBIFlightSourceManifestCreateRequest(_ManifestAPIModel):
    bundle_id: UUID
    organization_ref: str = Field(min_length=1, max_length=128)
    farm_id: UUID
    plot_id: UUID | None = None
    flight_ref: str = Field(min_length=1, max_length=128)
    entries: list[DBIFlightSourceEntryRequest] = Field(
        min_length=1,
        max_length=10_000,
    )

    @field_validator("organization_ref", "flight_ref", mode="before")
    @classmethod
    def canonical_refs(cls, value: object, info) -> object:
        return _canonical_ref(value, info.field_name)


class DBIFlightSourceManifestSummaryResponse(_ManifestAPIModel):
    bundle_id: UUID
    schema_version: Literal["flight-source-bundle.v1"]
    flight_ref: str
    master_asset_id: UUID
    farm_id: UUID
    plot_id: UUID | None
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entry_count: int = Field(ge=1, le=10_000)
    total_size_bytes: int = Field(gt=0)
    created_by_ref: str
    created_at: datetime


class DBIFlightSourceManifestCreateResponse(_ManifestAPIModel):
    created: bool
    manifest: DBIFlightSourceManifestSummaryResponse


class DBIFlightSourceEntryResponse(_ManifestAPIModel):
    asset_id: UUID
    ordinal: int = Field(ge=1, le=10_000)
    role: Literal["source_photo", "auxiliary"]
    logical_name: str
    content_type: str
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sensor_camera: str | None
    captured_at: datetime | None


class DBIFlightSourceManifestPageResponse(_ManifestAPIModel):
    manifest: DBIFlightSourceManifestSummaryResponse
    entries: list[DBIFlightSourceEntryResponse]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    has_more: bool

