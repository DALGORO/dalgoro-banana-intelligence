"""Archivo GIS original recibido para una Campaign, todavía NO publicado."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.db.dbi_base import DBIBase


class DBIPortalGISImport(DBIBase):
    __tablename__ = "dbi_portal_gis_imports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plot_id", "farm_id"], ["dbi_plots.id", "dbi_plots.farm_id"],
            name="fk_dbi_portal_gis_import_plot_farm", ondelete="RESTRICT",
        ),
        UniqueConstraint("source_object_id", name="uq_dbi_portal_gis_import_object"),
        CheckConstraint("source_format IN ('gpkg', 'shp_zip')", name="ck_dbi_portal_gis_import_format"),
        CheckConstraint("status IN ('received', 'processing', 'prepared', 'failed')", name="ck_dbi_portal_gis_import_status"),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 31457280", name="ck_dbi_portal_gis_import_size"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_dbi_portal_gis_import_sha"),
        CheckConstraint(
            "layer_kind IN ('plants', 'density_hexagons', 'planting_candidates', 'boundaries', 'observations', 'other')",
            name="ck_dbi_portal_gis_import_kind",
        ),
        Index("ix_dbi_portal_gis_import_scope", "tenant_ref", "farm_id", "plot_id", "campaign_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    farm_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("dbi_farms.id", ondelete="RESTRICT"), nullable=False)
    plot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("dbi_campaigns.id", ondelete="RESTRICT"), nullable=False)
    source_object_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    source_format: Mapped[str] = mapped_column(String(16), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    layer_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="received")
    created_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
