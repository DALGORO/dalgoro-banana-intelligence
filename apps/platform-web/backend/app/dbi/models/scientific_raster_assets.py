"""H14/2H-2C: activo de entrada científico REAL en SQL, sin bytes ni upload."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKeyConstraint,
    Index, String, UniqueConstraint, Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.dbi_base import DBIBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DBIScientificRasterInputAsset(DBIBase):
    """Catálogo de activos privados registrados, nunca recepción certificada."""

    __tablename__ = "dbi_scientific_raster_input_assets"
    __table_args__ = (
        # El vínculo tiene una identidad scoped y no puede reutilizarse en otra Campaign.
        ForeignKeyConstraint(
            ["binding_id", "tenant_ref", "campaign_id", "role", "index_ref"],
            ["dbi_scientific_raster_bindings.id",
             "dbi_scientific_raster_bindings.tenant_ref",
             "dbi_scientific_raster_bindings.campaign_id",
             "dbi_scientific_raster_bindings.role",
             "dbi_scientific_raster_bindings.index_ref"],
            name="fk_dbi_scientific_raster_asset_binding_scope", ondelete="RESTRICT",
        ),
        UniqueConstraint("binding_id", name="uq_dbi_scientific_raster_asset_binding"),
        UniqueConstraint("id", "binding_id", name="uq_dbi_scientific_raster_asset_id_binding"),
        UniqueConstraint(
            "tenant_ref", "target_object_id",
            name="uq_dbi_scientific_raster_asset_target",
        ),
        CheckConstraint(
            "(role = 'rgb' AND index_ref = '_' AND asset_kind = 'orthophoto_rgb') "
            "OR (role = 'scientific_cog' AND asset_kind = 'scientific_cog' "
            "AND index_ref IN ('ndvi','ndre','gndvi','evi2','ci_red_edge','ci_green'))",
            name="ck_dbi_scientific_raster_asset_kind_role",
        ),
        CheckConstraint(
            "status = 'registered_pending_bytes' AND file_received = false "
            "AND content_verified = false AND session_started = false "
            "AND institutional_approved = false AND published = false",
            name="ck_dbi_scientific_raster_asset_no_bytes",
        ),
        CheckConstraint(
            "declared_size_bytes > 0 AND declared_size_bytes <= 10737418240",
            name="ck_dbi_scientific_raster_asset_size",
        ),
        CheckConstraint(
            "declared_sha256 ~ '^[0-9a-f]{64}$' AND content_type = 'image/tiff'",
            name="ck_dbi_scientific_raster_asset_tiff",
        ),
        Index("ix_dbi_scientific_raster_assets_scope",
              "tenant_ref", "organization_ref", "farm_id", "plot_id", "campaign_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    binding_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    farm_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    plot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    index_ref: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    target_object_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    declared_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    declared_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    file_received: Mapped[bool] = mapped_column(Boolean, nullable=False)
    content_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    session_started: Mapped[bool] = mapped_column(Boolean, nullable=False)
    institutional_approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now,
    )
