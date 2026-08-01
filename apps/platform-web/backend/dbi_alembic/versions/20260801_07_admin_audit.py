"""Crea evidencia administrativa DBI append-only.

Revision ID: dbi_0007_admin_audit
Revises: dbi_0006_plot_boundaries
Create Date: 2026-08-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0007_admin_audit"
down_revision: Union[str, Sequence[str], None] = "dbi_0006_plot_boundaries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crea el registro administrativo mínimo y no sensible."""

    op.create_table(
        "dbi_admin_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_principal_id", sa.Uuid(), nullable=False),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("organization_ref", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("resource_type", sa.String(length=24), nullable=False),
        sa.Column("resource_ref", sa.String(length=128), nullable=False),
        sa.Column(
            "outcome",
            sa.String(length=16),
            server_default="succeeded",
            nullable=False,
        ),
        sa.Column("correlation_ref", sa.String(length=128), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ("
            "'principal_registered', 'membership_created', "
            "'membership_activated', 'membership_inactivated', "
            "'membership_revoked', 'membership_permissions_replaced', "
            "'membership_scopes_replaced'"
            ")",
            name="ck_dbi_admin_audit_action",
        ),
        sa.CheckConstraint(
            "resource_type IN ('principal', 'membership')",
            name="ck_dbi_admin_audit_resource_type",
        ),
        sa.CheckConstraint(
            "outcome = 'succeeded'",
            name="ck_dbi_admin_audit_outcome",
        ),
        sa.CheckConstraint(
            "tenant_ref = btrim(tenant_ref) "
            "AND length(tenant_ref) > 0 "
            "AND position('*' in tenant_ref) = 0 "
            "AND lower(tenant_ref) NOT IN ('all', 'any')",
            name="ck_dbi_admin_audit_tenant_ref",
        ),
        sa.CheckConstraint(
            "organization_ref = btrim(organization_ref) "
            "AND length(organization_ref) > 0 "
            "AND position('*' in organization_ref) = 0 "
            "AND lower(organization_ref) NOT IN ('all', 'any')",
            name="ck_dbi_admin_audit_organization_ref",
        ),
        sa.CheckConstraint(
            "resource_ref = btrim(resource_ref) "
            "AND length(resource_ref) > 0 "
            "AND position('*' in resource_ref) = 0 "
            "AND lower(resource_ref) NOT IN ('all', 'any')",
            name="ck_dbi_admin_audit_resource_ref",
        ),
        sa.CheckConstraint(
            "correlation_ref = btrim(correlation_ref) "
            "AND length(correlation_ref) > 0 "
            "AND position('*' in correlation_ref) = 0 "
            "AND lower(correlation_ref) NOT IN ('all', 'any')",
            name="ck_dbi_admin_audit_correlation_ref",
        ),
        sa.ForeignKeyConstraint(
            ["actor_principal_id"],
            ["dbi_principals.id"],
            name=(
                "fk_dbi_admin_audit_actor_principal_id_"
                "dbi_principals"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_id"],
            ["dbi_memberships.id"],
            name=(
                "fk_dbi_admin_audit_actor_membership_id_"
                "dbi_memberships"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_admin_audit_events"),
        sa.UniqueConstraint(
            "tenant_ref",
            "organization_ref",
            "correlation_ref",
            "action",
            "resource_type",
            "resource_ref",
            name="uq_dbi_admin_audit_correlation_resource",
        ),
    )
    op.create_index(
        "ix_dbi_admin_audit_tenant_occurred",
        "dbi_admin_audit_events",
        ["tenant_ref", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_admin_audit_organization_occurred",
        "dbi_admin_audit_events",
        ["tenant_ref", "organization_ref", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_admin_audit_actor_occurred",
        "dbi_admin_audit_events",
        ["actor_principal_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_admin_audit_resource",
        "dbi_admin_audit_events",
        ["resource_type", "resource_ref"],
        unique=False,
    )


def downgrade() -> None:
    """Retira únicamente la tabla de auditoría administrativa DBI."""

    op.drop_table("dbi_admin_audit_events")
