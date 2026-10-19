"""H14/2H-2D/2: S3 loopback provider start register, no client grants.

Revision ID: dbi_0033_raster_provider_start
Revises: dbi_0032_raster_session_prep

Only ephemeral CI database migration. NEVER execute in Render/production.
"""
from __future__ import annotations
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0033_raster_provider_start"
down_revision: str | None = "dbi_0032_raster_session_prep"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dbi_scientific_raster_provider_starts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("preparation_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(128), nullable=False),
        sa.Column("organization_ref", sa.String(128), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("plot_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("target_object_id", sa.Uuid(), nullable=False),
        sa.Column("declared_sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("provider_upload_ref", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by_ref", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aborted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_scientific_raster_provider_starts"),
        sa.ForeignKeyConstraint(
            ["preparation_id"], ["dbi_scientific_raster_session_preparations.id"],
            name="fk_dbi_raster_provider_start_preparation", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "binding_id"],
            ["dbi_scientific_raster_input_assets.id",
             "dbi_scientific_raster_input_assets.binding_id"],
            name="fk_dbi_raster_provider_start_asset_binding", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("preparation_id", name="uq_dbi_raster_provider_start_ticket"),
        sa.UniqueConstraint("asset_id", name="uq_dbi_raster_provider_start_asset"),
        sa.UniqueConstraint(
            "tenant_ref", "target_object_id",
            name="uq_dbi_raster_provider_start_target",
        ),
        sa.CheckConstraint(
            "status IN ('initiated_no_grants','aborted_no_grants') AND "
            "((status='aborted_no_grants') = (aborted_at IS NOT NULL))",
            name="ck_dbi_raster_provider_start_state",
        ),
        sa.CheckConstraint(
            "length(provider_upload_ref) BETWEEN 1 AND 1024 "
            "AND btrim(provider_upload_ref) = provider_upload_ref",
            name="ck_dbi_raster_provider_start_remote",
        ),
        sa.CheckConstraint(
            "declared_sha256 ~ '^[0-9a-f]{64}$' "
            "AND size_bytes > 67108864 AND size_bytes <= 10737418240",
            name="ck_dbi_raster_provider_start_content",
        ),
        sa.CheckConstraint(
            "created_at <= updated_at AND "
            "(aborted_at IS NULL OR aborted_at >= created_at)",
            name="ck_dbi_raster_provider_start_times",
        ),
    )
    op.create_index(
        "ix_dbi_raster_provider_start_scope", "dbi_scientific_raster_provider_starts",
        ["tenant_ref", "organization_ref", "farm_id", "plot_id", "campaign_id"],
    )


def downgrade() -> None:
    op.execute(sa.text(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM dbi_scientific_raster_provider_starts) "
        "THEN RAISE EXCEPTION "
        "'DBI provider starts exist; institutional cleanup required'; "
        "END IF; END $$"
    ))
    op.drop_index(
        "ix_dbi_raster_provider_start_scope",
        table_name="dbi_scientific_raster_provider_starts",
    )
    op.drop_table("dbi_scientific_raster_provider_starts")
