"""Contratos estrictos para registrar activos de entrada DBI."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AssetKind = Literal[
    "orthophoto",
    "boundary",
    "exclusions",
    "flight_photo",
    "flight_auxiliary",
    "field_photo",
]


class _AssetWriteModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AnalysisInputAssetRegister(_AssetWriteModel):
    """Metadata declarada por el cliente para un activo estable e idempotente."""

    asset_id: UUID
    plot_id: UUID | None = None
    asset_kind: AssetKind
    content_type: str = Field(min_length=3, max_length=128)
    size_bytes: int = Field(
        strict=True,
        gt=0,
        le=9_223_372_036_854_775_807,
    )
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    crs: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("content_type", mode="before")
    @classmethod
    def require_canonical_content_type(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        if (
            value != value.strip()
            or value != value.lower()
            or ";" in value
            or any(character.isspace() for character in value)
        ):
            raise ValueError("content_type debe ser MIME canónico en minúsculas.")
        return value

    @field_validator("crs", mode="before")
    @classmethod
    def require_canonical_crs(cls, value: object) -> object:
        if value is None or not isinstance(value, str):
            return value
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("crs debe ser texto canónico.")
        return value

    @model_validator(mode="after")
    def validate_field_photo_metadata(self) -> "AnalysisInputAssetRegister":
        if self.asset_kind != "field_photo":
            return self
        if self.plot_id is None:
            raise ValueError("field_photo requiere plot_id explícito.")
        if not self.content_type.startswith("image/"):
            raise ValueError("field_photo requiere content_type de imagen.")
        if self.crs is not None:
            raise ValueError("field_photo no debe declarar CRS raster/vectorial.")
        return self
