"""Persistencia versionada de planes y puntos de muestreo de campo DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.dbi_base import DBIBase
from app.dbi.spatial import DBI_SPATIAL_SRID


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DBISamplingPlanRecord(DBIBase):
    """Snapshot reproducible del plan generado para un lote autorizado."""

    __tablename__ = "dbi_sampling_plans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plot_id", "farm_id"],
            ["dbi_plots.id", "dbi_plots.farm_id"],
            name="fk_dbi_sampling_plans_plot_farm",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_ref",
            "farm_id",
            "plot_id",
            "boundary_sha256",
            "exclusions_sha256",
            "profile_sha256",
            name="uq_dbi_sampling_plans_scope_snapshot_profile",
        ),
        CheckConstraint(
            "status IN ('planned', 'in_field', 'completed', 'retired')",
            name="ck_dbi_sampling_plans_status",
        ),
        CheckConstraint(
            "boundary_sha256 ~ '^[0-9a-f]{64}$' "
            "AND exclusions_sha256 ~ '^[0-9a-f]{64}$' "
            "AND profile_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_sampling_plans_sha256",
        ),
        CheckConstraint(
            "octet_length(profile_json) BETWEEN 2 AND 65536 "
            "AND octet_length(budget_json) BETWEEN 2 AND 16384",
            name="ck_dbi_sampling_plans_json_size",
        ),
        CheckConstraint(
            "NOT ST_IsEmpty(boundary_snapshot) AND ST_IsValid(boundary_snapshot)",
            name="ck_dbi_sampling_plans_boundary",
        ),
        CheckConstraint(
            "(exclusions_snapshot IS NULL) OR "
            "(NOT ST_IsEmpty(exclusions_snapshot) AND ST_IsValid(exclusions_snapshot))",
            name="ck_dbi_sampling_plans_exclusions",
        ),
        CheckConstraint(
            "(status = 'retired' AND retired_at IS NOT NULL) OR "
            "(status <> 'retired' AND retired_at IS NULL)",
            name="ck_dbi_sampling_plans_retirement",
        ),
        Index("ix_dbi_sampling_plans_tenant", "tenant_ref"),
        Index("ix_dbi_sampling_plans_farm_plot", "farm_id", "plot_id"),
        Index("ix_dbi_sampling_plans_status", "status"),
        Index(
            "ix_dbi_sampling_plans_boundary_gist",
            "boundary_snapshot",
            postgresql_using="gist",
        ),
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
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_json: Mapped[str] = mapped_column(Text, nullable=False)
    profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    boundary_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    exclusions_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    budget_json: Mapped[str] = mapped_column(Text, nullable=False)
    boundary_snapshot: Mapped[WKBElement] = mapped_column(
        Geometry("MULTIPOLYGON", srid=DBI_SPATIAL_SRID, spatial_index=False),
        nullable=False,
    )
    exclusions_snapshot: Mapped[WKBElement | None] = mapped_column(
        Geometry("MULTIPOLYGON", srid=DBI_SPATIAL_SRID, spatial_index=False),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planned")
    created_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    points: Mapped[list["DBISamplingPointRecord"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DBISamplingPointRecord(DBIBase):
    """Candidato planificado; nunca equivale por sí solo a una UP."""

    __tablename__ = "dbi_sampling_points"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "role",
            "sequence",
            name="uq_dbi_sampling_points_plan_role_sequence",
        ),
        UniqueConstraint(
            "plan_id",
            "route_order",
            name="uq_dbi_sampling_points_plan_route_order",
        ),
        CheckConstraint(
            "role IN ('primary', 'reserve')",
            name="ck_dbi_sampling_points_role",
        ),
        CheckConstraint(
            "status IN ('planned', 'validated', 'rejected', 'substituted')",
            name="ck_dbi_sampling_points_status",
        ),
        CheckConstraint(
            "rejection_reason IS NULL OR rejection_reason IN "
            "('road','infrastructure','canal_or_drain','non_banana','missing_plant',"
            "'inaccessible','unsafe','other')",
            name="ck_dbi_sampling_points_rejection_reason",
        ),
        CheckConstraint(
            "sequence > 0 AND (route_order IS NULL OR route_order > 0) "
            "AND (reserve_for_sequence IS NULL OR reserve_for_sequence > 0)",
            name="ck_dbi_sampling_points_positive_order",
        ),
        CheckConstraint(
            "(role = 'primary' AND route_order IS NOT NULL AND reserve_for_sequence IS NULL) "
            "OR (role = 'reserve' AND route_order IS NULL AND reserve_for_sequence IS NOT NULL)",
            name="ck_dbi_sampling_points_role_fields",
        ),
        CheckConstraint(
            "NOT ST_IsEmpty(planned_point) AND ST_IsValid(planned_point) "
            "AND (observed_point IS NULL OR (NOT ST_IsEmpty(observed_point) AND ST_IsValid(observed_point)))",
            name="ck_dbi_sampling_points_geometry",
        ),
        CheckConstraint(
            "(status = 'planned' AND observed_point IS NULL AND rejection_reason IS NULL) "
            "OR (status = 'validated' AND observed_point IS NOT NULL AND rejection_reason IS NULL) "
            "OR (status IN ('rejected', 'substituted') AND rejection_reason IS NOT NULL)",
            name="ck_dbi_sampling_points_state_fields",
        ),
        Index("ix_dbi_sampling_points_plan", "plan_id"),
        Index("ix_dbi_sampling_points_status", "status"),
        Index(
            "ix_dbi_sampling_points_planned_gist",
            "planned_point",
            postgresql_using="gist",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    plan_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_sampling_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    route_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reserve_for_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selection_reason: Mapped[str] = mapped_column(String(32), nullable=False)
    planned_point: Mapped[WKBElement] = mapped_column(
        Geometry("POINT", srid=DBI_SPATIAL_SRID, spatial_index=False),
        nullable=False,
    )
    observed_point: Mapped[WKBElement | None] = mapped_column(
        Geometry("POINT", srid=DBI_SPATIAL_SRID, spatial_index=False),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planned")
    rejection_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    plan: Mapped[DBISamplingPlanRecord] = relationship(back_populates="points")
