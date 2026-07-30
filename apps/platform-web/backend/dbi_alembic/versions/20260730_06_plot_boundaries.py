"""Añade límites MultiPolygon EPSG:4326 a los lotes DBI.

Revision ID: dbi_0006_plot_boundaries
Revises: dbi_0005_identity_memberships
Create Date: 2026-07-30
"""

from typing import Sequence, Union

from alembic import op
from geoalchemy2 import Geometry
import sqlalchemy as sa

revision: str = "dbi_0006_plot_boundaries"
down_revision: Union[str, Sequence[str], None] = "dbi_0005_identity_memberships"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Añade geometría opcional, controles topológicos e índice GiST."""

    op.add_column(
        "dbi_plots",
        sa.Column(
            "boundary",
            Geometry(
                geometry_type="MULTIPOLYGON",
                srid=4326,
                spatial_index=False,
            ),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_dbi_plots_boundary_not_empty",
        "dbi_plots",
        "boundary IS NULL OR NOT ST_IsEmpty(boundary)",
    )
    op.create_check_constraint(
        "ck_dbi_plots_boundary_valid",
        "dbi_plots",
        "boundary IS NULL OR ST_IsValid(boundary)",
    )
    op.create_index(
        "ix_dbi_plots_boundary_gist",
        "dbi_plots",
        ["boundary"],
        unique=False,
        postgresql_using="gist",
    )


def downgrade() -> None:
    """Retira únicamente la ampliación espacial de los lotes."""

    op.drop_index("ix_dbi_plots_boundary_gist", table_name="dbi_plots")
    op.drop_constraint(
        "ck_dbi_plots_boundary_valid",
        "dbi_plots",
        type_="check",
    )
    op.drop_constraint(
        "ck_dbi_plots_boundary_not_empty",
        "dbi_plots",
        type_="check",
    )
    op.drop_column("dbi_plots", "boundary")
