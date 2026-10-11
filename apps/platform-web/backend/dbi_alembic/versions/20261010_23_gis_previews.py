"""GIS previews remain private until a separate MANAGE review.

Revision ID: dbi_0023_gis_previews
Revises: dbi_0022_portal_gis_imports
"""
from __future__ import annotations
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0023_gis_previews"
down_revision: str | None = "dbi_0022_portal_gis_imports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dbi_portal_gis_imports", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("dbi_portal_gis_imports", sa.Column("processing_ref", sa.Uuid(), nullable=True))
    op.add_column("dbi_portal_gis_imports", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint(
        "ck_dbi_portal_gis_import_attempts", "dbi_portal_gis_imports",
        "attempt_count BETWEEN 0 AND 3",
    )
    op.create_table(
        "dbi_portal_gis_previews",
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("feature_count", sa.Integer(), nullable=False),
        sa.Column("geojson_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("import_id", name="pk_dbi_portal_gis_previews"),
        sa.ForeignKeyConstraint(["import_id"], ["dbi_portal_gis_imports.id"], name="fk_dbi_portal_gis_preview_import", ondelete="CASCADE"),
        sa.CheckConstraint("feature_count > 0 AND feature_count <= 2500", name="ck_dbi_portal_gis_preview_features"),
        sa.CheckConstraint("octet_length(geojson_text) BETWEEN 20 AND 2097152", name="ck_dbi_portal_gis_preview_size"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_dbi_portal_gis_preview_sha"),
    )


def downgrade() -> None:
    op.drop_table("dbi_portal_gis_previews")
    op.drop_constraint("ck_dbi_portal_gis_import_attempts", "dbi_portal_gis_imports", type_="check")
    op.drop_column("dbi_portal_gis_imports", "attempt_count")
    op.drop_column("dbi_portal_gis_imports", "processing_ref")
    op.drop_column("dbi_portal_gis_imports", "processing_started_at")
