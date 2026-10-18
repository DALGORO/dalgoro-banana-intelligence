"""H14: reservación transaccional scoped de TIFF científico, NO uploader.

Revision ID: dbi_0030_scientific_raster_binding
Revises: dbi_0029_staff_approval_guard

Esta revisión solo define el esquema. NO ejecutar sobre Render/producción.
"""
from __future__ import annotations

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0030_scientific_raster_binding"
down_revision: str | None = "dbi_0029_staff_approval_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dbi_scientific_raster_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("organization_ref", sa.String(length=128), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("plot_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_type", sa.String(length=16), nullable=False),
        sa.Column("manifest_object_id", sa.Uuid(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("slot_object_id", sa.Uuid(), nullable=False),
        sa.Column("slot_sha256", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("index_ref", sa.String(length=32), nullable=False),
        sa.Column("target_object_id", sa.Uuid(), nullable=False),
        sa.Column("declared_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("declared_sha256", sa.String(length=64), nullable=False),
        sa.Column("reserved_by", sa.String(length=128), nullable=False),
        sa.Column("created_by_ref", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_scientific_raster_bindings"),
        sa.ForeignKeyConstraint(
            ["campaign_id", "tenant_ref", "organization_ref", "farm_id", "plot_id", "analysis_type"],
            ["dbi_campaigns.id", "dbi_campaigns.tenant_ref",
             "dbi_campaigns.organization_ref", "dbi_campaigns.farm_id",
             "dbi_campaigns.plot_id", "dbi_campaigns.analysis_type"],
            name="fk_dbi_scientific_raster_binding_campaign_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_ref", "campaign_id", "role", "index_ref",
            name="uq_dbi_scientific_raster_binding_slot",
        ),
        sa.UniqueConstraint(
            "tenant_ref", "target_object_id",
            name="uq_dbi_scientific_raster_binding_target",
        ),
        sa.UniqueConstraint(
            "tenant_ref", "slot_object_id",
            name="uq_dbi_scientific_raster_binding_slot_object",
        ),
        sa.CheckConstraint(
            "analysis_type = 'multispectral'",
            name="ck_dbi_scientific_raster_binding_multispectral",
        ),
        sa.CheckConstraint(
            "(role = 'rgb' AND index_ref = '_') OR "
            "(role = 'scientific_cog' AND index_ref IN "
            "('ndvi','ndre','gndvi','evi2','ci_red_edge','ci_green'))",
            name="ck_dbi_scientific_raster_binding_role",
        ),
        sa.CheckConstraint(
            "status = 'reserved_no_asset' AND asset_id IS NULL",
            name="ck_dbi_scientific_raster_binding_not_ready",
        ),
        sa.CheckConstraint(
            "declared_size_bytes > 0 AND declared_size_bytes <= 10737418240",
            name="ck_dbi_scientific_raster_binding_size",
        ),
        sa.CheckConstraint(
            "manifest_sha256 ~ '^[0-9a-f]{64}$' AND "
            "slot_sha256 ~ '^[0-9a-f]{64}$' AND "
            "declared_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_scientific_raster_binding_hashes",
        ),
        sa.CheckConstraint(
            "length(tenant_ref) BETWEEN 1 AND 128 AND btrim(tenant_ref) = tenant_ref "
            "AND length(organization_ref) BETWEEN 1 AND 128 AND "
            "btrim(organization_ref) = organization_ref AND "
            "length(reserved_by) BETWEEN 1 AND 128 AND "
            "length(created_by_ref) BETWEEN 1 AND 128",
            name="ck_dbi_scientific_raster_binding_refs",
        ),
    )
    op.create_index(
        "ix_dbi_scientific_raster_bindings_scope", "dbi_scientific_raster_bindings",
        ["tenant_ref", "organization_ref", "farm_id", "plot_id", "campaign_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dbi_scientific_raster_bindings_scope",
                  table_name="dbi_scientific_raster_bindings")
    op.drop_table("dbi_scientific_raster_bindings")
