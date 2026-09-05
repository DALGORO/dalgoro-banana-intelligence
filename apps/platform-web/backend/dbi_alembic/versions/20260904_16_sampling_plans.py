"""Persist sampling plans and field points.

Revision ID: dbi_0016_sampling_plans
Revises: dbi_0015_raster_products
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from geoalchemy2 import Geometry
import sqlalchemy as sa

revision: str = "dbi_0016_sampling_plans"
down_revision: str | None = "dbi_0015_raster_products"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SHA_CHECK = "^[0-9a-f]{64}$"


def upgrade() -> None:
    op.create_table(
        "dbi_sampling_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("organization_ref", sa.String(length=128), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("plot_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("profile_version", sa.String(length=64), nullable=False),
        sa.Column("profile_json", sa.Text(), nullable=False),
        sa.Column("profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("boundary_sha256", sa.String(length=64), nullable=False),
        sa.Column("exclusions_sha256", sa.String(length=64), nullable=False),
        sa.Column("budget_json", sa.Text(), nullable=False),
        sa.Column(
            "boundary_snapshot",
            Geometry("MULTIPOLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "exclusions_snapshot",
            Geometry("MULTIPOLYGON", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=16), server_default="planned", nullable=False),
        sa.Column("created_by_ref", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_sampling_plans"),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["dbi_farms.id"],
            name="fk_dbi_sampling_plans_farm",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plot_id", "farm_id"],
            ["dbi_plots.id", "dbi_plots.farm_id"],
            name="fk_dbi_sampling_plans_plot_farm",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "farm_id",
            "plot_id",
            "boundary_sha256",
            "exclusions_sha256",
            "profile_sha256",
            name="uq_dbi_sampling_plans_scope_snapshot_profile",
        ),
        sa.CheckConstraint(
            "status IN ('planned','in_field','completed','retired')",
            name="ck_dbi_sampling_plans_status",
        ),
        sa.CheckConstraint(
            f"boundary_sha256 ~ '{_SHA_CHECK}' "
            f"AND exclusions_sha256 ~ '{_SHA_CHECK}' "
            f"AND profile_sha256 ~ '{_SHA_CHECK}'",
            name="ck_dbi_sampling_plans_sha256",
        ),
        sa.CheckConstraint(
            "octet_length(profile_json) BETWEEN 2 AND 65536 "
            "AND octet_length(budget_json) BETWEEN 2 AND 16384",
            name="ck_dbi_sampling_plans_json_size",
        ),
        sa.CheckConstraint(
            "length(schema_version) BETWEEN 1 AND 64 "
            "AND btrim(schema_version) = schema_version "
            "AND length(profile_version) BETWEEN 1 AND 64 "
            "AND btrim(profile_version) = profile_version "
            "AND length(created_by_ref) BETWEEN 1 AND 128 "
            "AND btrim(created_by_ref) = created_by_ref",
            name="ck_dbi_sampling_plans_canonical_refs",
        ),
        sa.CheckConstraint(
            "NOT ST_IsEmpty(boundary_snapshot) AND ST_IsValid(boundary_snapshot)",
            name="ck_dbi_sampling_plans_boundary",
        ),
        sa.CheckConstraint(
            "exclusions_snapshot IS NULL OR "
            "(NOT ST_IsEmpty(exclusions_snapshot) AND ST_IsValid(exclusions_snapshot))",
            name="ck_dbi_sampling_plans_exclusions",
        ),
        sa.CheckConstraint(
            "(status = 'retired' AND retired_at IS NOT NULL AND retired_at >= created_at) OR "
            "(status <> 'retired' AND retired_at IS NULL)",
            name="ck_dbi_sampling_plans_retirement",
        ),
    )
    op.create_index("ix_dbi_sampling_plans_tenant", "dbi_sampling_plans", ["tenant_ref"])
    op.create_index(
        "ix_dbi_sampling_plans_farm_plot",
        "dbi_sampling_plans",
        ["farm_id", "plot_id"],
    )
    op.create_index("ix_dbi_sampling_plans_status", "dbi_sampling_plans", ["status"])
    op.create_index(
        "ix_dbi_sampling_plans_boundary_gist",
        "dbi_sampling_plans",
        ["boundary_snapshot"],
        postgresql_using="gist",
    )

    op.create_table(
        "dbi_sampling_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("route_order", sa.Integer(), nullable=True),
        sa.Column("reserve_for_sequence", sa.Integer(), nullable=True),
        sa.Column("selection_reason", sa.String(length=32), nullable=False),
        sa.Column(
            "planned_point",
            Geometry("POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "observed_point",
            Geometry("POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=16), server_default="planned", nullable=False),
        sa.Column("rejection_reason", sa.String(length=32), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_sampling_points"),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["dbi_sampling_plans.id"],
            name="fk_dbi_sampling_points_plan",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "plan_id",
            "role",
            "sequence",
            name="uq_dbi_sampling_points_plan_role_sequence",
        ),
        sa.UniqueConstraint(
            "plan_id",
            "route_order",
            name="uq_dbi_sampling_points_plan_route_order",
        ),
        sa.CheckConstraint(
            "role IN ('primary','reserve')",
            name="ck_dbi_sampling_points_role",
        ),
        sa.CheckConstraint(
            "status IN ('planned','validated','rejected','substituted')",
            name="ck_dbi_sampling_points_status",
        ),
        sa.CheckConstraint(
            "rejection_reason IS NULL OR rejection_reason IN "
            "('road','infrastructure','canal_or_drain','non_banana','missing_plant',"
            "'inaccessible','unsafe','other')",
            name="ck_dbi_sampling_points_rejection_reason",
        ),
        sa.CheckConstraint(
            "selection_reason IN ('balanced','nearby_reserve')",
            name="ck_dbi_sampling_points_selection_reason",
        ),
        sa.CheckConstraint(
            "sequence > 0 AND (route_order IS NULL OR route_order > 0) "
            "AND (reserve_for_sequence IS NULL OR reserve_for_sequence > 0)",
            name="ck_dbi_sampling_points_positive_order",
        ),
        sa.CheckConstraint(
            "(role = 'primary' AND route_order IS NOT NULL AND reserve_for_sequence IS NULL) OR "
            "(role = 'reserve' AND route_order IS NULL AND reserve_for_sequence IS NOT NULL)",
            name="ck_dbi_sampling_points_role_fields",
        ),
        sa.CheckConstraint(
            "NOT ST_IsEmpty(planned_point) AND ST_IsValid(planned_point) "
            "AND (observed_point IS NULL OR "
            "(NOT ST_IsEmpty(observed_point) AND ST_IsValid(observed_point)))",
            name="ck_dbi_sampling_points_geometry",
        ),
        sa.CheckConstraint(
            "(status = 'planned' AND observed_point IS NULL AND rejection_reason IS NULL AND observed_at IS NULL) OR "
            "(status = 'validated' AND observed_point IS NOT NULL AND rejection_reason IS NULL AND observed_at IS NOT NULL) OR "
            "(status IN ('rejected','substituted') AND rejection_reason IS NOT NULL AND observed_at IS NOT NULL)",
            name="ck_dbi_sampling_points_state_fields",
        ),
    )
    op.create_index("ix_dbi_sampling_points_plan", "dbi_sampling_points", ["plan_id"])
    op.create_index("ix_dbi_sampling_points_status", "dbi_sampling_points", ["status"])
    op.create_index(
        "ix_dbi_sampling_points_planned_gist",
        "dbi_sampling_points",
        ["planned_point"],
        postgresql_using="gist",
    )
    op.create_index(
        "ix_dbi_sampling_points_observed_gist",
        "dbi_sampling_points",
        ["observed_point"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_table("dbi_sampling_points")
    op.drop_table("dbi_sampling_plans")
