"""Explicit MANAGE approval of GIS previews.

Revision ID: dbi_0024_gis_approval
Revises: dbi_0023_gis_previews
"""
from __future__ import annotations
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0024_gis_approval"
down_revision: str | None = "dbi_0023_gis_previews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dbi_portal_gis_imports", sa.Column("published_layer_id", sa.Uuid(), nullable=True))
    op.add_column("dbi_portal_gis_imports", sa.Column("approved_by_ref", sa.String(length=128), nullable=True))
    op.add_column("dbi_portal_gis_imports", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("ck_dbi_portal_gis_import_status", "dbi_portal_gis_imports", type_="check")
    op.create_check_constraint(
        "ck_dbi_portal_gis_import_status", "dbi_portal_gis_imports",
        "status IN ('received', 'processing', 'prepared', 'published', 'failed')",
    )
    op.create_foreign_key(
        "fk_dbi_portal_gis_import_published_layer",
        "dbi_portal_gis_imports", "dbi_portal_vector_layers",
        ["published_layer_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_dbi_portal_gis_import_published", "dbi_portal_gis_imports",
        "status != 'published' OR published_layer_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_dbi_portal_gis_import_published", "dbi_portal_gis_imports", type_="check")
    op.drop_constraint("fk_dbi_portal_gis_import_published_layer", "dbi_portal_gis_imports", type_="foreignkey")
    op.drop_constraint("ck_dbi_portal_gis_import_status", "dbi_portal_gis_imports", type_="check")
    op.create_check_constraint(
        "ck_dbi_portal_gis_import_status", "dbi_portal_gis_imports",
        "status IN ('received', 'processing', 'prepared', 'failed')",
    )
    op.drop_column("dbi_portal_gis_imports", "approved_at")
    op.drop_column("dbi_portal_gis_imports", "approved_by_ref")
    op.drop_column("dbi_portal_gis_imports", "published_layer_id")
