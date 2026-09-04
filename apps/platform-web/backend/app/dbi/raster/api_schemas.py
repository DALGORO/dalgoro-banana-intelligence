"""Contratos HTTP no sensibles para productos ráster DBI."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _RasterAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DBIRasterProductMetadataResponse(_RasterAPIModel):
    product_id: UUID
    product_kind: Literal["rgb_visual", "scientific"]
    profile_version: str = Field(min_length=1, max_length=64)
    content_type: Literal["image/tiff"]
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    crs: str = Field(min_length=1, max_length=128)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    band_count: int = Field(gt=0, le=32)
    dtype: str = Field(min_length=1, max_length=32)
    transform: tuple[float, float, float, float, float, float]
    bounds: tuple[float, float, float, float]
    nodata: tuple[float | None, ...]
    scales: tuple[float, ...]
    offsets: tuple[float, ...]
    block_width: int = Field(gt=0)
    block_height: int = Field(gt=0)
    compression: str = Field(min_length=1, max_length=32)
    overview_levels: tuple[int, ...]


class DBIRasterProductRetireResponse(_RasterAPIModel):
    product_id: UUID
    status: Literal["retired"]
    changed: bool
    retired_at: datetime


class DBIRasterRangeErrorResponse(_RasterAPIModel):
    detail: str
