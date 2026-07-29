"""Crea el dominio mínimo de finca, lote y campaña DBI.

Revision ID: dbi_0002_agricultural_domain
Revises: dbi_0001_baseline
Create Date: 2026-07-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0002_agricultural_domain"
down_revision: Union[str, Sequence[str], None] = "dbi_0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _audit_columns() -> tuple[sa.Column, sa.Column]:
    """Construye las columnas temporales comunes sin extensiones."""

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
    """Crea únicamente las tres tablas transaccionales del dominio v1."""

    op.create_table(
        "dbi_farms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_ref", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="active",
            nullable=False,
        ),
        *_audit_columns(),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'archived')",
            name="ck_dbi_farms_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_farms"),
        sa.UniqueConstraint(
            "organization_ref",
            "code",
            name="uq_dbi_farms_organization_code",
        ),
    )
    op.create_index(
        "ix_dbi_farms_organization_ref",
        "dbi_farms",
        ["organization_ref"],
        unique=False,
    )

    op.create_table(
        "dbi_plots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("area_hectares", sa.Numeric(12, 4), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="active",
            nullable=False,
        ),
        *_audit_columns(),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'archived')",
            name="ck_dbi_plots_status",
        ),
        sa.CheckConstraint(
            "area_hectares IS NULL OR area_hectares > 0",
            name="ck_dbi_plots_positive_area",
        ),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["dbi_farms.id"],
            name="fk_dbi_plots_farm_id_dbi_farms",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_plots"),
        sa.UniqueConstraint(
            "farm_id",
            "code",
            name="uq_dbi_plots_farm_code",
        ),
    )
    op.create_index(
        "ix_dbi_plots_farm_id",
        "dbi_plots",
        ["farm_id"],
        unique=False,
    )

    op.create_table(
        "dbi_campaigns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="planned",
            nullable=False,
        ),
        *_audit_columns(),
        sa.CheckConstraint(
            "status IN ('planned', 'active', 'completed', 'cancelled')",
            name="ck_dbi_campaigns_status",
        ),
        sa.CheckConstraint(
            "ends_at IS NULL OR ends_at >= starts_at",
            name="ck_dbi_campaigns_date_order",
        ),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["dbi_farms.id"],
            name="fk_dbi_campaigns_farm_id_dbi_farms",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_campaigns"),
        sa.UniqueConstraint(
            "farm_id",
            "code",
            name="uq_dbi_campaigns_farm_code",
        ),
    )
    op.create_index(
        "ix_dbi_campaigns_farm_id",
        "dbi_campaigns",
        ["farm_id"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_campaigns_starts_at",
        "dbi_campaigns",
        ["starts_at"],
        unique=False,
    )


def downgrade() -> None:
    """Revierte el dominio en orden inverso de dependencias."""

    op.drop_table("dbi_campaigns")
    op.drop_table("dbi_plots")
    op.drop_table("dbi_farms")
