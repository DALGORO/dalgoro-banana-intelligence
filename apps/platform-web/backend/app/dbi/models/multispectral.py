"""Persistencia inmutable de evidencia multiespectral derivada DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
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


class DBIMultispectralExtractionRecord(DBIBase):
    """Snapshot derivado ligado a una versión INSPECT y ráster científico exactos."""

    __tablename__ = "dbi_multispectral_extractions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plot_id", "farm_id"],
            ["dbi_plots.id", "dbi_plots.farm_id"],
            name="fk_dbi_multispectral_extractions_plot_farm",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["observation_id", "observation_version_id"],
            [
                "dbi_field_observation_versions.observation_id",
                "dbi_field_observation_versions.id",
            ],
            name="fk_dbi_multispectral_extractions_observation_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "observation_version_id",
            "source_raster_product_id",
            "support_mode",
            "support_profile_version",
            "stack_fingerprint",
            name="uq_dbi_multispectral_extractions_source_support",
        ),
        CheckConstraint(
            "schema_version = 'dbi-multispectral-extraction.v1'",
            name="ck_dbi_multispectral_extractions_schema_version",
        ),
        CheckConstraint(
            "evidence_kind = 'derived'",
            name="ck_dbi_multispectral_extractions_evidence_kind",
        ),
        CheckConstraint(
            "support_mode IN ('copa_up', 'window')",
            name="ck_dbi_multispectral_extractions_support_mode",
        ),
        CheckConstraint(
            "(support_mode = 'copa_up' AND up_id IS NOT NULL "
            "AND support_limitation IS NULL) OR "
            "(support_mode = 'window' AND support_limitation IS NOT NULL "
            "AND length(btrim(support_limitation)) BETWEEN 1 AND 500)",
            name="ck_dbi_multispectral_extractions_support_semantics",
        ),
        CheckConstraint(
            "selected_count > 0",
            name="ck_dbi_multispectral_extractions_selected_count",
        ),
        CheckConstraint(
            "stack_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_multispectral_extractions_sha256",
        ),
        CheckConstraint(
            "octet_length(payload_json) BETWEEN 2 AND 262144",
            name="ck_dbi_multispectral_extractions_payload_size",
        ),
        CheckConstraint(
            "length(tenant_ref) BETWEEN 1 AND 128 "
            "AND btrim(tenant_ref) = tenant_ref "
            "AND tenant_ref NOT LIKE '%*%' "
            "AND length(organization_ref) BETWEEN 1 AND 128 "
            "AND btrim(organization_ref) = organization_ref "
            "AND organization_ref NOT LIKE '%*%' "
            "AND length(support_profile_version) BETWEEN 1 AND 128 "
            "AND btrim(support_profile_version) = support_profile_version",
            name="ck_dbi_multispectral_extractions_canonical_refs",
        ),
        Index("ix_dbi_multispectral_extractions_tenant", "tenant_ref"),
        Index(
            "ix_dbi_multispectral_extractions_farm_plot",
            "farm_id",
            "plot_id",
        ),
        Index(
            "ix_dbi_multispectral_extractions_observation_version",
            "observation_version_id",
        ),
        Index(
            "ix_dbi_multispectral_extractions_source_raster",
            "source_raster_product_id",
        ),
        Index(
            "ix_dbi_multispectral_extractions_sampling_point",
            "sampling_point_id",
        ),
        Index("ix_dbi_multispectral_extractions_up", "up_id"),
        Index("ix_dbi_multispectral_extractions_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_farms.id", ondelete="RESTRICT"),
        nullable=False,
    )
    plot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    observation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    observation_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    source_raster_product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_raster_products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sampling_point_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("dbi_sampling_points.id", ondelete="RESTRICT"),
        nullable=True,
    )
    up_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    support_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    support_profile_version: Mapped[str] = mapped_column(String(128), nullable=False)
    support_limitation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stack_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="derived")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
