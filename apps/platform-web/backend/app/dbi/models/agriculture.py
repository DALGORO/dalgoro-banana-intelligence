"""Modelos mínimos de finca, lote y campaña para DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.dbi_base import DBIBase
from app.dbi.spatial import DBI_SPATIAL_SRID


def utc_now() -> datetime:
    """Devuelve una fecha consciente de zona horaria en UTC."""

    return datetime.now(timezone.utc)


class Farm(DBIBase):
    """Unidad agrícola propiedad de una organización referenciada."""

    __tablename__ = "dbi_farms"
    __table_args__ = (
        UniqueConstraint(
            "organization_ref",
            "code",
            name="uq_dbi_farms_organization_code",
        ),
        UniqueConstraint(
            "id",
            "organization_ref",
            name="uq_dbi_farms_id_organization",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'archived')",
            name="ck_dbi_farms_status",
        ),
        Index("ix_dbi_farms_organization_ref", "organization_ref"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    plots: Mapped[list["Plot"]] = relationship(
        back_populates="farm",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    campaigns: Mapped[list["Campaign"]] = relationship(
        back_populates="farm",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Plot(DBIBase):
    """Lote operativo perteneciente a una finca."""

    __tablename__ = "dbi_plots"
    __table_args__ = (
        UniqueConstraint(
            "farm_id",
            "code",
            name="uq_dbi_plots_farm_code",
        ),
        UniqueConstraint(
            "id",
            "farm_id",
            name="uq_dbi_plots_id_farm",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'archived')",
            name="ck_dbi_plots_status",
        ),
        CheckConstraint(
            "area_hectares IS NULL OR area_hectares > 0",
            name="ck_dbi_plots_positive_area",
        ),
        CheckConstraint(
            "boundary IS NULL OR NOT ST_IsEmpty(boundary)",
            name="ck_dbi_plots_boundary_not_empty",
        ),
        CheckConstraint(
            "boundary IS NULL OR ST_IsValid(boundary)",
            name="ck_dbi_plots_boundary_valid",
        ),
        Index("ix_dbi_plots_farm_id", "farm_id"),
        Index(
            "ix_dbi_plots_boundary_gist",
            "boundary",
            postgresql_using="gist",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    area_hectares: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    boundary: Mapped[WKBElement | None] = mapped_column(
        Geometry(
            geometry_type="MULTIPOLYGON",
            srid=DBI_SPATIAL_SRID,
            spatial_index=False,
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    farm: Mapped[Farm] = relationship(back_populates="plots")


class Campaign(DBIBase):
    """Campaña agrícola legacy o levantamiento técnico DBI scoped por lote."""

    __tablename__ = "dbi_campaigns"
    __table_args__ = (
        UniqueConstraint(
            "farm_id",
            "code",
            name="uq_dbi_campaigns_farm_code",
        ),
        CheckConstraint(
            "(analysis_type IS NULL AND status IN "
            "('planned', 'active', 'completed', 'cancelled')) OR "
            "(analysis_type IS NOT NULL AND status IN "
            "('DRAFT', 'PROCESSING', 'ANALYZED', 'TECHNICAL_REVIEW', "
            "'SAMPLING_READY', 'FIELD_WORK', 'FIELD_COMPLETED', "
            "'APPROVED', 'PUBLISHED'))",
            name="ck_dbi_campaigns_status",
        ),
        CheckConstraint(
            "ends_at IS NULL OR ends_at >= starts_at",
            name="ck_dbi_campaigns_date_order",
        ),
        CheckConstraint(
            "analysis_type IS NULL OR analysis_type IN ('density', 'multispectral')",
            name="ck_dbi_campaigns_analysis_type",
        ),
        CheckConstraint(
            "(analysis_type IS NULL AND tenant_ref IS NULL AND "
            "organization_ref IS NULL AND plot_id IS NULL AND captured_at IS NULL) "
            "OR (analysis_type IS NOT NULL AND tenant_ref IS NOT NULL AND "
            "organization_ref IS NOT NULL AND plot_id IS NOT NULL AND "
            "captured_at IS NOT NULL)",
            name="ck_dbi_campaigns_technical_scope_complete",
        ),
        ForeignKeyConstraint(
            ["plot_id", "farm_id"],
            ["dbi_plots.id", "dbi_plots.farm_id"],
            name="fk_dbi_campaigns_plot_farm",
            ondelete="RESTRICT",
        ),
        Index("ix_dbi_campaigns_farm_id", "farm_id"),
        Index("ix_dbi_campaigns_starts_at", "starts_at"),
        Index("ix_dbi_campaigns_tenant_ref", "tenant_ref"),
        Index("ix_dbi_campaigns_organization_ref", "organization_ref"),
        Index("ix_dbi_campaigns_plot_id", "plot_id"),
        Index("ix_dbi_campaigns_captured_at", "captured_at"),
        Index("ix_dbi_campaigns_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    organization_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    plot_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    analysis_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="planned",
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    field_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    field_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    current_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    source_job_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    farm: Mapped[Farm] = relationship(back_populates="campaigns")
