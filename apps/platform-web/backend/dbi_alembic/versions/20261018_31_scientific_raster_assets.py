"""H14/2H-2C: logical scientific raster asset with no bytes or sessions.

Revision ID: dbi_0031_raster_asset
Revises: dbi_0030_raster_binding

Only code review and ephemeral CI, NOT migration on Render/production.
"""
from __future__ import annotations

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0031_raster_asset"
down_revision: str | None = "dbi_0030_raster_binding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_dbi_scientific_raster_binding_identity_scope",
        "dbi_scientific_raster_bindings",
        ["id", "tenant_ref", "campaign_id", "role", "index_ref"],
    )
    op.create_table(
        "dbi_scientific_raster_input_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(128), nullable=False),
        sa.Column("organization_ref", sa.String(128), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("plot_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("index_ref", sa.String(32), nullable=False),
        sa.Column("asset_kind", sa.String(24), nullable=False),
        sa.Column("target_object_id", sa.Uuid(), nullable=False),
        sa.Column("declared_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("declared_sha256", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("file_received", sa.Boolean(), nullable=False),
        sa.Column("content_verified", sa.Boolean(), nullable=False),
        sa.Column("session_started", sa.Boolean(), nullable=False),
        sa.Column("institutional_approved", sa.Boolean(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("created_by_ref", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_scientific_raster_input_assets"),
        sa.ForeignKeyConstraint(
            ["binding_id", "tenant_ref", "campaign_id", "role", "index_ref"],
            ["dbi_scientific_raster_bindings.id",
             "dbi_scientific_raster_bindings.tenant_ref",
             "dbi_scientific_raster_bindings.campaign_id",
             "dbi_scientific_raster_bindings.role",
             "dbi_scientific_raster_bindings.index_ref"],
            name="fk_dbi_scientific_raster_asset_binding_scope", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "binding_id", name="uq_dbi_scientific_raster_asset_binding",
        ),
        sa.UniqueConstraint(
            "id", "binding_id", name="uq_dbi_scientific_raster_asset_id_binding",
        ),
        sa.UniqueConstraint(
            "tenant_ref", "target_object_id",
            name="uq_dbi_scientific_raster_asset_target",
        ),
        sa.CheckConstraint(
            "(role = 'rgb' AND index_ref = '_' AND asset_kind = 'orthophoto_rgb') "
            "OR (role = 'scientific_cog' AND asset_kind = 'scientific_cog' "
            "AND index_ref IN ('ndvi','ndre','gndvi','evi2','ci_red_edge','ci_green'))",
            name="ck_dbi_scientific_raster_asset_kind_role",
        ),
        sa.CheckConstraint(
            "status = 'registered_pending_bytes' AND file_received = false "
            "AND content_verified = false AND session_started = false "
            "AND institutional_approved = false AND published = false",
            name="ck_dbi_scientific_raster_asset_no_bytes",
        ),
        sa.CheckConstraint(
            "declared_size_bytes > 0 AND declared_size_bytes <= 10737418240",
            name="ck_dbi_scientific_raster_asset_size",
        ),
        sa.CheckConstraint(
            "declared_sha256 ~ '^[0-9a-f]{64}$' AND content_type = 'image/tiff'",
            name="ck_dbi_scientific_raster_asset_tiff",
        ),
    )
    op.create_index(
        "ix_dbi_scientific_raster_assets_scope", "dbi_scientific_raster_input_assets",
        ["tenant_ref", "organization_ref", "farm_id", "plot_id", "campaign_id"],
    )
    op.drop_constraint(
        "ck_dbi_scientific_raster_binding_not_ready",
        "dbi_scientific_raster_bindings", type_="check",
    )
    op.create_check_constraint(
        "ck_dbi_scientific_raster_binding_not_ready",
        "dbi_scientific_raster_bindings",
        "(status = 'reserved_no_asset' AND asset_id IS NULL) OR "
        "(status = 'asset_registered_pending_bytes' AND asset_id IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_dbi_scientific_raster_binding_asset_exact",
        "dbi_scientific_raster_bindings",
        "dbi_scientific_raster_input_assets",
        ["asset_id", "id"], ["id", "binding_id"], ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_dbi_scientific_raster_binding_asset_exact",
        "dbi_scientific_raster_bindings", type_="foreignkey",
    )
    # Fail rather than silently erase asset associations on downgrade.
    op.execute(sa.text(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM dbi_scientific_raster_bindings "
        "WHERE asset_id IS NOT NULL) THEN "
        "RAISE EXCEPTION 'Cannot downgrade DBI raster assets with registrations'; "
        "END IF; END $$"
    ))
    op.drop_constraint(
        "ck_dbi_scientific_raster_binding_not_ready",
        "dbi_scientific_raster_bindings", type_="check",
    )
    op.create_check_constraint(
        "ck_dbi_scientific_raster_binding_not_ready",
        "dbi_scientific_raster_bindings",
        "status = 'reserved_no_asset' AND asset_id IS NULL",
    )
    op.drop_index(
        "ix_dbi_scientific_raster_assets_scope",
        table_name="dbi_scientific_raster_input_assets",
    )
    op.drop_table("dbi_scientific_raster_input_assets")
    op.drop_constraint(
        "uq_dbi_scientific_raster_binding_identity_scope",
        "dbi_scientific_raster_bindings", type_="unique",
    )
