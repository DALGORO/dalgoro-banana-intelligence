"""Immutable GIS source upload receipts; head dbi_0022_portal_gis_imports."""
from __future__ import annotations
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0022_portal_gis_imports"
down_revision: str | None = "dbi_0021_portal_vectors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dbi_portal_gis_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("organization_ref", sa.String(length=128), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("plot_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("source_object_id", sa.Uuid(), nullable=False),
        sa.Column("source_format", sa.String(length=16), nullable=False),
        sa.Column("original_filename", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("layer_kind", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by_ref", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_portal_gis_imports"),
        sa.ForeignKeyConstraint(["farm_id"], ["dbi_farms.id"], name="fk_dbi_portal_gis_import_farm", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["plot_id", "farm_id"], ["dbi_plots.id", "dbi_plots.farm_id"],
            name="fk_dbi_portal_gis_import_plot_farm", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["dbi_campaigns.id"], name="fk_dbi_portal_gis_import_campaign", ondelete="RESTRICT"),
        sa.UniqueConstraint("source_object_id", name="uq_dbi_portal_gis_import_object"),
        sa.CheckConstraint("source_format IN ('gpkg', 'shp_zip')", name="ck_dbi_portal_gis_import_format"),
        sa.CheckConstraint("status IN ('received', 'processing', 'prepared', 'failed')", name="ck_dbi_portal_gis_import_status"),
        sa.CheckConstraint("size_bytes > 0 AND size_bytes <= 31457280", name="ck_dbi_portal_gis_import_size"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_dbi_portal_gis_import_sha"),
        sa.CheckConstraint(
            "layer_kind IN ('plants', 'density_hexagons', 'planting_candidates', 'boundaries', 'observations', 'other')",
            name="ck_dbi_portal_gis_import_kind",
        ),
    )
    op.create_index(
        "ix_dbi_portal_gis_import_scope", "dbi_portal_gis_imports",
        ["tenant_ref", "farm_id", "plot_id", "campaign_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dbi_portal_gis_import_scope", table_name="dbi_portal_gis_imports")
    op.drop_table("dbi_portal_gis_imports")
