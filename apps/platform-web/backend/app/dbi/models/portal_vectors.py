"""Capas vectoriales de visualización del portal, independientes de las fuentes científicas."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.dbi_base import DBIBase


class DBIPortalVectorLayer(DBIBase):
    __tablename__ = "dbi_portal_vector_layers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plot_id", "farm_id"], ["dbi_plots.id", "dbi_plots.farm_id"],
            name="fk_dbi_portal_vector_plot_farm", ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_ref", "campaign_id", "layer_kind", "source_sha256",
            name="uq_dbi_portal_vector_source",
        ),
        CheckConstraint(
            "layer_kind IN ('plants', 'density_hexagons', 'planting_candidates', 'boundaries', 'observations', 'other')",
            name="ck_dbi_portal_vector_kind",
        ),
        CheckConstraint("feature_count > 0 AND feature_count <= 2500", name="ck_dbi_portal_vector_features"),
        CheckConstraint("octet_length(geojson_text) BETWEEN 20 AND 2097152", name="ck_dbi_portal_vector_size"),
        CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dbi_portal_vector_sha"),
        Index("ix_dbi_portal_vector_scope", "tenant_ref", "farm_id", "plot_id", "campaign_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    farm_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("dbi_farms.id", ondelete="RESTRICT"), nullable=False)
    plot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("dbi_campaigns.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    layer_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    crs: Mapped[str] = mapped_column(String(16), nullable=False, default="EPSG:4326")
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    geojson_text: Mapped[str] = mapped_column(Text, nullable=False)
    feature_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
