"""Portal GeoJSON layers scoped by Campaign.

Revision ID: dbi_0021_portal_vectors
Revises: dbi_0020_campaign_artifacts
"""
from __future__ import annotations

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0021_portal_vectors"
down_revision: str | None = "dbi_0020_campaign_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dbi_portal_vector_layers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("organization_ref", sa.String(length=128), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("plot_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("layer_kind", sa.String(length=32), nullable=False),
        sa.Column("crs", sa.String(length=16), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("geojson_text", sa.Text(), nullable=False),
        sa.Column("source_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("feature_count", sa.Integer(), nullable=False),
        sa.Column("created_by_ref", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_portal_vector_layers"),
        sa.ForeignKeyConstraint(["farm_id"], ["dbi_farms.id"], name="fk_dbi_portal_vectors_farm", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plot_id", "farm_id"], ["dbi_plots.id", "dbi_plots.farm_id"], name="fk_dbi_portal_vector_plot_farm", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["campaign_id"], ["dbi_campaigns.id"], name="fk_dbi_portal_vectors_campaign", ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "tenant_ref", "campaign_id", "layer_kind", "source_sha256",
            name="uq_dbi_portal_vector_source",
        ),
        sa.CheckConstraint(
            "layer_kind IN ('plants', 'density_hexagons', 'planting_candidates', 'boundaries', 'observations', 'other')",
            name="ck_dbi_portal_vector_kind",
        ),
        sa.CheckConstraint("feature_count > 0 AND feature_count <= 2500", name="ck_dbi_portal_vector_features"),
        sa.CheckConstraint("octet_length(geojson_text) BETWEEN 20 AND 2097152", name="ck_dbi_portal_vector_size"),
        sa.CheckConstraint("octet_length(source_bytes) BETWEEN 20 AND 2097152", name="ck_dbi_portal_vector_source_size"),
        sa.CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dbi_portal_vector_sha"),
    )
    op.create_index(
        "ix_dbi_portal_vector_scope", "dbi_portal_vector_layers",
        ["tenant_ref", "farm_id", "plot_id", "campaign_id"],
    )


def downgrade() -> None:
    op.drop_table("dbi_portal_vector_layers")
