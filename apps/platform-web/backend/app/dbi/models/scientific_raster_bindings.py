"""H14/2H-2B: vínculo SQL privado de una ranura científica (sin Asset aún).

La identidad SQL es scoped por Campaign y manifiesto. Ningún estado permite
iniciar multipart ni acreditar bytes, aprobación o publicación.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKeyConstraint,
    Index, String, UniqueConstraint, Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.dbi_base import DBIBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DBIScientificRasterBinding(DBIBase):
    """Vínculo transaccional *planificado*, no un activo registrado o verificado."""

    __tablename__ = "dbi_scientific_raster_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["campaign_id", "tenant_ref", "organization_ref", "farm_id", "plot_id", "analysis_type"],
            ["dbi_campaigns.id", "dbi_campaigns.tenant_ref",
             "dbi_campaigns.organization_ref", "dbi_campaigns.farm_id",
             "dbi_campaigns.plot_id", "dbi_campaigns.analysis_type"],
            name="fk_dbi_scientific_raster_binding_campaign_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_ref", "campaign_id", "role", "index_ref",
            name="uq_dbi_scientific_raster_binding_slot",
        ),
        UniqueConstraint(
            "tenant_ref", "target_object_id",
            name="uq_dbi_scientific_raster_binding_target",
        ),
        UniqueConstraint(
            "tenant_ref", "slot_object_id",
            name="uq_dbi_scientific_raster_binding_slot_object",
        ),
        CheckConstraint(
            "analysis_type = 'multispectral'",
            name="ck_dbi_scientific_raster_binding_multispectral",
        ),
        CheckConstraint(
            "(role = 'rgb' AND index_ref = '_') OR "
            "(role = 'scientific_cog' AND index_ref IN "
            "('ndvi','ndre','gndvi','evi2','ci_red_edge','ci_green'))",
            name="ck_dbi_scientific_raster_binding_role",
        ),
        CheckConstraint(
            "status = 'reserved_no_asset' AND asset_id IS NULL",
            name="ck_dbi_scientific_raster_binding_not_ready",
        ),
        CheckConstraint(
            "declared_size_bytes > 0 AND declared_size_bytes <= 10737418240",
            name="ck_dbi_scientific_raster_binding_size",
        ),
        CheckConstraint(
            "manifest_sha256 ~ '^[0-9a-f]{64}$' AND "
            "slot_sha256 ~ '^[0-9a-f]{64}$' AND "
            "declared_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_scientific_raster_binding_hashes",
        ),
        CheckConstraint(
            "length(tenant_ref) BETWEEN 1 AND 128 AND btrim(tenant_ref) = tenant_ref "
            "AND length(organization_ref) BETWEEN 1 AND 128 AND "
            "btrim(organization_ref) = organization_ref AND "
            "length(reserved_by) BETWEEN 1 AND 128 AND "
            "length(created_by_ref) BETWEEN 1 AND 128",
            name="ck_dbi_scientific_raster_binding_refs",
        ),
        Index(
            "ix_dbi_scientific_raster_bindings_scope",
            "tenant_ref", "organization_ref", "farm_id", "plot_id", "campaign_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    farm_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    plot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    analysis_type: Mapped[str] = mapped_column(String(16), nullable=False)
    manifest_object_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    slot_object_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    slot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    index_ref: Mapped[str] = mapped_column(String(32), nullable=False)
    target_object_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    declared_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    declared_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reserved_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now,
    )
