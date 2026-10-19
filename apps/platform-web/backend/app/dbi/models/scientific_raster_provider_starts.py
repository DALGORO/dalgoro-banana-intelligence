"""H14/2H-2D/2: inicio S3 loopback sin grants ni partes.

La referencia remota está cifrada solo por perímetro DB, nunca en respuesta.
No habilita ningún transporte desde cliente y no valida bytes originales.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKeyConstraint, Index,
    String, UniqueConstraint, Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.dbi_base import DBIBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DBIScientificRasterProviderStart(DBIBase):
    __tablename__ = "dbi_scientific_raster_provider_starts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["preparation_id"],
            ["dbi_scientific_raster_session_preparations.id"],
            name="fk_dbi_raster_provider_start_preparation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["asset_id", "binding_id"],
            ["dbi_scientific_raster_input_assets.id",
             "dbi_scientific_raster_input_assets.binding_id"],
            name="fk_dbi_raster_provider_start_asset_binding",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("preparation_id", name="uq_dbi_raster_provider_start_ticket"),
        UniqueConstraint("asset_id", name="uq_dbi_raster_provider_start_asset"),
        UniqueConstraint(
            "tenant_ref", "target_object_id",
            name="uq_dbi_raster_provider_start_target",
        ),
        CheckConstraint(
            "status IN ('initiated_no_grants','aborted_no_grants') AND "
            "((status='aborted_no_grants') = (aborted_at IS NOT NULL))",
            name="ck_dbi_raster_provider_start_state",
        ),
        CheckConstraint(
            "length(provider_upload_ref) BETWEEN 1 AND 1024 "
            "AND btrim(provider_upload_ref) = provider_upload_ref",
            name="ck_dbi_raster_provider_start_remote",
        ),
        CheckConstraint(
            "declared_sha256 ~ '^[0-9a-f]{64}$' "
            "AND size_bytes > 67108864 AND size_bytes <= 10737418240",
            name="ck_dbi_raster_provider_start_content",
        ),
        CheckConstraint(
            "created_at <= updated_at AND "
            "(aborted_at IS NULL OR aborted_at >= created_at)",
            name="ck_dbi_raster_provider_start_times",
        ),
        Index(
            "ix_dbi_raster_provider_start_scope",
            "tenant_ref", "organization_ref", "farm_id", "plot_id", "campaign_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    preparation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    binding_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    farm_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    plot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    target_object_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    declared_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider_upload_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now,
    )
    aborted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
