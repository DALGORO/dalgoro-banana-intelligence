"""Contratos HTTP no sensibles para carga, confirmación y retiro de activos DBI."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dbi.asset_schemas import AnalysisInputAssetRegister


class _AssetAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _canonical_organization_ref(value: object) -> object:
    if not isinstance(value, str):
        return value
    if (
        value != value.strip()
        or "*" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("organization_ref debe ser canónica.")
    return value


class DBIAssetUploadRequest(_AssetAPIModel):
    organization_ref: str = Field(min_length=1, max_length=128)
    farm_id: UUID
    asset: AnalysisInputAssetRegister

    @field_validator("organization_ref", mode="before")
    @classmethod
    def require_canonical_organization(cls, value: object) -> object:
        return _canonical_organization_ref(value)


class DBIAssetConfirmRequest(_AssetAPIModel):
    organization_ref: str = Field(min_length=1, max_length=128)
    farm_id: UUID

    @field_validator("organization_ref", mode="before")
    @classmethod
    def require_canonical_organization(cls, value: object) -> object:
        return _canonical_organization_ref(value)


class DBIAssetRetireRequest(_AssetAPIModel):
    organization_ref: str = Field(min_length=1, max_length=128)
    farm_id: UUID

    @field_validator("organization_ref", mode="before")
    @classmethod
    def require_canonical_organization(cls, value: object) -> object:
        return _canonical_organization_ref(value)


class DBIAssetUploadAccessResponse(_AssetAPIModel):
    method: Literal["PUT"]
    url: str = Field(min_length=1, repr=False)
    headers: dict[str, str] = Field(default_factory=dict, repr=False)
    expires_at: datetime


class DBIAssetUploadResponse(_AssetAPIModel):
    asset_id: UUID
    status: Literal["registered"]
    created: bool
    upload: DBIAssetUploadAccessResponse


class DBIAssetConfirmResponse(_AssetAPIModel):
    asset_id: UUID
    status: Literal["verified", "quarantined"]
    changed: bool
    reason: Literal["verified", "integrity_mismatch"]


class DBIAssetRetireResponse(_AssetAPIModel):
    asset_id: UUID
    status: Literal["retired"]
    changed: bool
