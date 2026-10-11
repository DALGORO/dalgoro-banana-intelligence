"""One-time MANAGE layer choice for a private discovered GeoPackage.

Revision ID: dbi_0026_gpkg_layer_choice
Revises: dbi_0025_gpkg_layer_options
"""
from __future__ import annotations

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0026_gpkg_layer_choice"
down_revision: str | None = "dbi_0025_gpkg_layer_options"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dbi_portal_gis_imports",
        sa.Column("selected_layer", sa.String(length=100), nullable=True),
    )
    op.create_check_constraint(
        "ck_dbi_portal_gis_import_selected_layer", "dbi_portal_gis_imports",
        "selected_layer IS NULL OR (source_format = 'gpkg' "
        "AND available_layers IS NOT NULL AND char_length(selected_layer) BETWEEN 1 AND 100 "
        "AND available_layers ? selected_layer)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_dbi_portal_gis_import_selected_layer",
        "dbi_portal_gis_imports", type_="check",
    )
    op.drop_column("dbi_portal_gis_imports", "selected_layer")
