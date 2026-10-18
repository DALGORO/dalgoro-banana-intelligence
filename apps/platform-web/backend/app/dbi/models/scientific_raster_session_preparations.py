"""H14/2H-2D/1: sesión preparatoria SQL, nunca una sesión S3 real."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKeyConstraint,
    Index, Integer, String, UniqueConstraint, Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.dbi_base import DBIBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DBIScientificRasterSessionPreparation(DBIBase):
    """Un ticket durable por Asset, sin referencia del proveedor ni permisos."""

    __tablename__ = "dbi_scientific_raster_session_preparations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["asset_id", "binding_id"],
            ["dbi_scientific_raster_input_assets.id",
             "dbi_scientific_raster_input_assets.binding_id"],
            name="fk_dbi_scientific_raster_preparation_asset_binding",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("asset_id", name="uq_dbi_scientific_raster_preparation_asset"),
        UniqueConstraint(
            "tenant_ref", "idempotency_key_hash",
            name="uq_dbi_scientific_raster_preparation_key",
        ),
        CheckConstraint(
            "status IN ('prepared_no_provider','cancelled_no_provider') "
            "AND ((status='cancelled_no_provider') = (cancelled_at IS NOT NULL))",
            name="ck_dbi_scientific_raster_preparation_state",
        ),
        CheckConstraint(
            "size_bytes > 67108864 AND size_bytes <= 10737418240 "
            "AND part_size_bytes = 67108864 AND part_count BETWEEN 2 AND 10000 "
            "AND max_grants_per_window = 8 AND max_client_concurrency = 4",
            name="ck_dbi_scientific_raster_preparation_plan",
        ),
        CheckConstraint(
            "checksum_algorithm = 'SHA256' AND checksum_type = 'COMPOSITE'",
            name="ck_dbi_scientific_raster_preparation_checksum",
        ),
        CheckConstraint(
            "manifest_sha256 ~ '^[0-9a-f]{64}$' AND "
            "reservation_sha256 ~ '^[0-9a-f]{64}$' AND "
            "declared_sha256 ~ '^[0-9a-f]{64}$' AND "
            "idempotency_key_hash ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_scientific_raster_preparation_hashes",
        ),
        CheckConstraint(
            "expires_at > created_at AND updated_at >= created_at "
            "AND (cancelled_at IS NULL OR cancelled_at >= created_at)",
            name="ck_dbi_scientific_raster_preparation_times",
        ),
        Index(
            "ix_dbi_scientific_raster_preparation_scope",
            "tenant_ref", "organization_ref", "farm_id", "plot_id", "campaign_id",
        ),
        Index("ix_dbi_scientific_raster_preparation_expiry", "status", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    asset_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    binding_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    farm_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    plot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reservation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    declared_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    part_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    part_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_grants_per_window: Mapped[int] = mapped_column(Integer, nullable=False)
    max_client_concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_algorithm: Mapped[str] = mapped_column(String(12), nullable=False)
    checksum_type: Mapped[str] = mapped_column(String(12), nullable=False)
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
