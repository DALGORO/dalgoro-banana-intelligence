"""Refuerza la integridad organizacional de ámbitos agrícolas DBI.

Revision ID: dbi_0008_scope_hierarchy
Revises: dbi_0007_admin_audit
Create Date: 2026-08-01
"""

from typing import Sequence, Union

from alembic import op

revision: str = "dbi_0008_scope_hierarchy"
down_revision: Union[str, Sequence[str], None] = "dbi_0007_admin_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Impide asociar ámbitos con organizaciones o fincas divergentes."""

    op.create_unique_constraint(
        "uq_dbi_farms_id_organization",
        "dbi_farms",
        ["id", "organization_ref"],
    )
    op.create_unique_constraint(
        "uq_dbi_plots_id_farm",
        "dbi_plots",
        ["id", "farm_id"],
    )
    op.create_foreign_key(
        "fk_dbi_membership_scopes_farm_organization",
        "dbi_membership_scopes",
        "dbi_farms",
        ["farm_id", "organization_ref"],
        ["id", "organization_ref"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_dbi_membership_scopes_plot_farm",
        "dbi_membership_scopes",
        "dbi_plots",
        ["plot_id", "farm_id"],
        ["id", "farm_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Retira solo las restricciones compuestas añadidas por esta revisión."""

    op.drop_constraint(
        "fk_dbi_membership_scopes_plot_farm",
        "dbi_membership_scopes",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_dbi_membership_scopes_farm_organization",
        "dbi_membership_scopes",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_dbi_plots_id_farm",
        "dbi_plots",
        type_="unique",
    )
    op.drop_constraint(
        "uq_dbi_farms_id_organization",
        "dbi_farms",
        type_="unique",
    )
