"""Persist geometric GeoPackage layer options without selecting or publishing.

Revision ID: dbi_0025_gpkg_layer_options
Revises: dbi_0024_gis_approval
"""
from __future__ import annotations
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "dbi_0025_gpkg_layer_options"
down_revision: str | None = "dbi_0024_gis_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dbi_portal_gis_imports",
        sa.Column("available_layers", postgresql.JSONB(), nullable=True),
    )
    op.drop_constraint("ck_dbi_portal_gis_import_status", "dbi_portal_gis_imports", type_="check")
    op.create_check_constraint(
        "ck_dbi_portal_gis_import_status", "dbi_portal_gis_imports",
        "status IN ('received', 'processing', 'prepared', 'published', 'failed', 'needs_selection')",
    )
    op.create_check_constraint(
        "ck_dbi_portal_gis_import_options", "dbi_portal_gis_imports",
        "(available_layers IS NULL OR (source_format = 'gpkg' "
        "AND jsonb_typeof(available_layers) = 'array' "
        "AND jsonb_array_length(available_layers) BETWEEN 2 AND 20)) "
        "AND (status != 'needs_selection' OR available_layers IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_dbi_portal_gis_import_options", "dbi_portal_gis_imports", type_="check")
    op.drop_constraint("ck_dbi_portal_gis_import_status", "dbi_portal_gis_imports", type_="check")
    op.create_check_constraint(
        "ck_dbi_portal_gis_import_status", "dbi_portal_gis_imports",
        "status IN ('received', 'processing', 'prepared', 'published', 'failed')",
    )
    op.drop_column("dbi_portal_gis_imports", "available_layers")
