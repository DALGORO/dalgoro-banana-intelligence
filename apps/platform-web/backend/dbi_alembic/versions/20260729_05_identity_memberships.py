"""Crea autoridad canónica de identidad y membresías DBI.

Revision ID: dbi_0005_identity_memberships
Revises: dbi_0004_assets_artifacts
Create Date: 2026-07-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0005_identity_memberships"
down_revision: Union[str, Sequence[str], None] = (
    "dbi_0004_assets_artifacts"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _audit_columns() -> tuple[sa.Column, sa.Column]:
    """Construye columnas temporales comunes sin extensiones."""

    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    """Crea principal, membresía, permisos y ámbitos DBI."""

    op.create_table(
        "dbi_principals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "legacy_identity_ref",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="active",
            nullable=False,
        ),
        *_audit_columns(),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_dbi_principals_status",
        ),
        sa.CheckConstraint(
            "legacy_identity_ref = btrim(legacy_identity_ref) "
            "AND length(legacy_identity_ref) > 0 "
            "AND position('*' in legacy_identity_ref) = 0 "
            "AND lower(legacy_identity_ref) NOT IN ('all', 'any')",
            name="ck_dbi_principals_legacy_identity_ref",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_principals"),
        sa.UniqueConstraint(
            "legacy_identity_ref",
            name="uq_dbi_principals_legacy_identity_ref",
        ),
    )

    op.create_table(
        "dbi_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="active",
            nullable=False,
        ),
        *_audit_columns(),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'revoked')",
            name="ck_dbi_memberships_status",
        ),
        sa.CheckConstraint(
            "tenant_ref = btrim(tenant_ref) "
            "AND length(tenant_ref) > 0 "
            "AND position('*' in tenant_ref) = 0 "
            "AND lower(tenant_ref) NOT IN ('all', 'any')",
            name="ck_dbi_memberships_tenant_ref",
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["dbi_principals.id"],
            name="fk_dbi_memberships_principal_id_dbi_principals",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_memberships"),
        sa.UniqueConstraint(
            "principal_id",
            "tenant_ref",
            name="uq_dbi_memberships_principal_tenant",
        ),
    )
    op.create_index(
        "ix_dbi_memberships_principal_id",
        "dbi_memberships",
        ["principal_id"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_memberships_tenant_ref",
        "dbi_memberships",
        ["tenant_ref"],
        unique=False,
    )

    op.create_table(
        "dbi_membership_permissions",
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("permission", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "permission IN ("
            "'read', 'write', 'submit_analysis', "
            "'approve_agronomic', 'manage'"
            ")",
            name="ck_dbi_membership_permissions_permission",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["dbi_memberships.id"],
            name=(
                "fk_dbi_membership_permissions_membership_id_"
                "dbi_memberships"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "membership_id",
            "permission",
            name="pk_dbi_membership_permissions",
        ),
    )

    op.create_table(
        "dbi_membership_scopes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column(
            "organization_ref",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column("farm_id", sa.Uuid(), nullable=True),
        sa.Column("plot_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "scope_type IN ('organization', 'farm', 'plot')",
            name="ck_dbi_membership_scopes_type",
        ),
        sa.CheckConstraint(
            "("
            "scope_type = 'organization' "
            "AND farm_id IS NULL AND plot_id IS NULL"
            ") OR ("
            "scope_type = 'farm' "
            "AND farm_id IS NOT NULL AND plot_id IS NULL"
            ") OR ("
            "scope_type = 'plot' "
            "AND farm_id IS NOT NULL AND plot_id IS NOT NULL"
            ")",
            name="ck_dbi_membership_scopes_hierarchy",
        ),
        sa.CheckConstraint(
            "organization_ref = btrim(organization_ref) "
            "AND length(organization_ref) > 0 "
            "AND position('*' in organization_ref) = 0 "
            "AND lower(organization_ref) NOT IN ('all', 'any')",
            name="ck_dbi_membership_scopes_organization_ref",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["dbi_memberships.id"],
            name=(
                "fk_dbi_membership_scopes_membership_id_"
                "dbi_memberships"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["dbi_farms.id"],
            name="fk_dbi_membership_scopes_farm_id_dbi_farms",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plot_id"],
            ["dbi_plots.id"],
            name="fk_dbi_membership_scopes_plot_id_dbi_plots",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_membership_scopes"),
    )
    op.create_index(
        "uq_dbi_membership_scopes_organization",
        "dbi_membership_scopes",
        ["membership_id", "organization_ref"],
        unique=True,
        postgresql_where=sa.text("scope_type = 'organization'"),
    )
    op.create_index(
        "uq_dbi_membership_scopes_farm",
        "dbi_membership_scopes",
        ["membership_id", "organization_ref", "farm_id"],
        unique=True,
        postgresql_where=sa.text("scope_type = 'farm'"),
    )
    op.create_index(
        "uq_dbi_membership_scopes_plot",
        "dbi_membership_scopes",
        ["membership_id", "organization_ref", "farm_id", "plot_id"],
        unique=True,
        postgresql_where=sa.text("scope_type = 'plot'"),
    )
    op.create_index(
        "ix_dbi_membership_scopes_membership_id",
        "dbi_membership_scopes",
        ["membership_id"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_membership_scopes_farm_id",
        "dbi_membership_scopes",
        ["farm_id"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_membership_scopes_plot_id",
        "dbi_membership_scopes",
        ["plot_id"],
        unique=False,
    )


def downgrade() -> None:
    """Revierte autoridad de identidad en orden inverso."""

    op.drop_table("dbi_membership_scopes")
    op.drop_table("dbi_membership_permissions")
    op.drop_table("dbi_memberships")
    op.drop_table("dbi_principals")
