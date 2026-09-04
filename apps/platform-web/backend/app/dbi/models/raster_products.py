"""Persistencia auditable de COG/BigTIFF privados DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.dbi_base import DBIBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


_SHA_CHECK = "^[0-9a-f]{64}$"
_OBJECT_KEY_CHECK = (
    "object_key ~ '^[A-Za-z0-9][A-Za-z0-9._/-]*$' "
    "AND object_key !~ '(^|/)\\.\\.?(/|$)' "
    "AND object_key NOT LIKE '%//%' "
    "AND object_key NOT LIKE '/%' "
    "AND object_key NOT LIKE '%\\\\%' "
    "AND length(object_key) BETWEEN 1 AND 512"
)


class DBIRasterProduct(DBIBase):
    """Producto COG persistente separado del master y de la caché de tiles."""

    __tablename__ = "dbi_raster_products"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plot_id", "farm_id"],
            ["dbi_plots.id", "dbi_plots.farm_id"],
            name="fk_dbi_raster_products_plot_farm",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_ref",
            "source_kind",
            "source_ref",
            "source_sha256",
            "product_kind",
            "profile_version",
            name="uq_dbi_raster_products_source_profile",
        ),
        UniqueConstraint("object_key", name="uq_dbi_raster_products_object_key"),
        CheckConstraint(
            "source_kind IN ('input_asset', 'analysis_artifact')",
            name="ck_dbi_raster_products_source_kind",
        ),
        CheckConstraint(
            "product_kind IN ('rgb_visual', 'scientific')",
            name="ck_dbi_raster_products_product_kind",
        ),
        CheckConstraint(
            "status IN ('ready', 'retired')",
            name="ck_dbi_raster_products_status",
        ),
        CheckConstraint(
            f"source_sha256 ~ '{_SHA_CHECK}' AND sha256 ~ '{_SHA_CHECK}'",
            name="ck_dbi_raster_products_sha256",
        ),
        CheckConstraint(
            "content_type = 'image/tiff'",
            name="ck_dbi_raster_products_content_type",
        ),
        CheckConstraint(
            _OBJECT_KEY_CHECK,
            name="ck_dbi_raster_products_object_key",
        ),
        CheckConstraint(
            "size_bytes > 0 AND width > 0 AND height > 0 AND band_count > 0",
            name="ck_dbi_raster_products_positive_shape",
        ),
        CheckConstraint(
            "block_width BETWEEN 64 AND 4096 AND block_height BETWEEN 64 AND 4096",
            name="ck_dbi_raster_products_block_shape",
        ),
        CheckConstraint(
            "length(profile_version) BETWEEN 1 AND 128 "
            "AND btrim(profile_version) = profile_version "
            "AND length(generator_version) BETWEEN 1 AND 128 "
            "AND btrim(generator_version) = generator_version",
            name="ck_dbi_raster_products_versions",
        ),
        CheckConstraint(
            "octet_length(transform_json) BETWEEN 2 AND 4096 "
            "AND octet_length(bounds_json) BETWEEN 2 AND 4096 "
            "AND octet_length(nodata_json) BETWEEN 2 AND 4096 "
            "AND octet_length(scales_json) BETWEEN 2 AND 4096 "
            "AND octet_length(offsets_json) BETWEEN 2 AND 4096 "
            "AND octet_length(overview_levels_json) BETWEEN 2 AND 4096",
            name="ck_dbi_raster_products_metadata_size",
        ),
        CheckConstraint(
            "(status = 'ready' AND retired_at IS NULL) OR "
            "(status = 'retired' AND retired_at IS NOT NULL AND retired_at >= created_at)",
            name="ck_dbi_raster_products_retirement",
        ),
        Index("ix_dbi_raster_products_tenant", "tenant_ref"),
        Index("ix_dbi_raster_products_farm_plot", "farm_id", "plot_id"),
        Index("ix_dbi_raster_products_source", "source_kind", "source_ref"),
        Index("ix_dbi_raster_products_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_farms.id", ondelete="RESTRICT"),
        nullable=False,
    )
    plot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    product_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(128), nullable=False)
    generator_version: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    crs: Mapped[str] = mapped_column(String(80), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    band_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dtype: Mapped[str] = mapped_column(String(64), nullable=False)
    transform_json: Mapped[str] = mapped_column(Text, nullable=False)
    bounds_json: Mapped[str] = mapped_column(Text, nullable=False)
    nodata_json: Mapped[str] = mapped_column(Text, nullable=False)
    scales_json: Mapped[str] = mapped_column(Text, nullable=False)
    offsets_json: Mapped[str] = mapped_column(Text, nullable=False)
    block_width: Mapped[int] = mapped_column(Integer, nullable=False)
    block_height: Mapped[int] = mapped_column(Integer, nullable=False)
    compression: Mapped[str] = mapped_column(String(32), nullable=False)
    overview_levels_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
