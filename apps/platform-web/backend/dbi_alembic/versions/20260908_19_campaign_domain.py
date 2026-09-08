"""Evoluciona campaign al levantamiento técnico scoped sin romper legacy.

Revision ID: dbi_0019_campaign_domain
Revises: dbi_0018_multi_extractions
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0019_campaign_domain"
down_revision: str | None = "dbi_0018_multi_extractions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TECHNICAL_STATUS_CHECK = (
    "(analysis_type IS NULL AND status IN "
    "('planned', 'active', 'completed', 'cancelled')) OR "
    "(analysis_type IS NOT NULL AND status IN "
    "('DRAFT', 'PROCESSING', 'ANALYZED', 'TECHNICAL_REVIEW', "
    "'SAMPLING_READY', 'FIELD_WORK', 'FIELD_COMPLETED', 'APPROVED', 'PUBLISHED'))"
)


def upgrade() -> None:
    """Añade scope y ciclo técnico conservando filas legacy existentes."""

    for column in (
        sa.Column("tenant_ref", sa.String(length=128), nullable=True),
        sa.Column("organization_ref", sa.String(length=128), nullable=True),
        sa.Column("plot_id", sa.Uuid(), nullable=True),
        sa.Column("analysis_type", sa.String(length=16), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("field_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("field_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_revision_id", sa.Uuid(), nullable=True),
        sa.Column("source_job_id", sa.Uuid(), nullable=True),
    ):
        op.add_column("dbi_campaigns", column)

    op.drop_constraint(
        "ck_dbi_campaigns_status",
        "dbi_campaigns",
        type_="check",
    )
    op.create_check_constraint(
        "ck_dbi_campaigns_status",
        "dbi_campaigns",
        TECHNICAL_STATUS_CHECK,
    )
    op.create_check_constraint(
        "ck_dbi_campaigns_analysis_type",
        "dbi_campaigns",
        "analysis_type IS NULL OR analysis_type IN ('density', 'multispectral')",
    )
    op.create_check_constraint(
        "ck_dbi_campaigns_technical_scope_complete",
        "dbi_campaigns",
        "(analysis_type IS NULL AND tenant_ref IS NULL AND "
        "organization_ref IS NULL AND plot_id IS NULL AND captured_at IS NULL) "
        "OR (analysis_type IS NOT NULL AND tenant_ref IS NOT NULL AND "
        "organization_ref IS NOT NULL AND plot_id IS NOT NULL AND "
        "captured_at IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_dbi_campaigns_plot_farm",
        "dbi_campaigns",
        "dbi_plots",
        ["plot_id", "farm_id"],
        ["id", "farm_id"],
        ondelete="RESTRICT",
    )

    for index_name, columns in (
        ("ix_dbi_campaigns_tenant_ref", ["tenant_ref"]),
        ("ix_dbi_campaigns_organization_ref", ["organization_ref"]),
        ("ix_dbi_campaigns_plot_id", ["plot_id"]),
        ("ix_dbi_campaigns_captured_at", ["captured_at"]),
        ("ix_dbi_campaigns_status", ["status"]),
    ):
        op.create_index(index_name, "dbi_campaigns", columns, unique=False)


def downgrade() -> None:
    """Retira el dominio técnico y conserva las campañas como legacy planned."""

    for index_name in (
        "ix_dbi_campaigns_status",
        "ix_dbi_campaigns_captured_at",
        "ix_dbi_campaigns_plot_id",
        "ix_dbi_campaigns_organization_ref",
        "ix_dbi_campaigns_tenant_ref",
    ):
        op.drop_index(index_name, table_name="dbi_campaigns")

    op.drop_constraint(
        "fk_dbi_campaigns_plot_farm",
        "dbi_campaigns",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_dbi_campaigns_status",
        "dbi_campaigns",
        type_="check",
    )
    op.execute(
        "UPDATE dbi_campaigns SET status = 'planned' WHERE analysis_type IS NOT NULL"
    )
    op.drop_constraint(
        "ck_dbi_campaigns_technical_scope_complete",
        "dbi_campaigns",
        type_="check",
    )
    op.drop_constraint(
        "ck_dbi_campaigns_analysis_type",
        "dbi_campaigns",
        type_="check",
    )

    for column_name in (
        "source_job_id",
        "current_revision_id",
        "published_at",
        "approved_at",
        "field_completed_at",
        "field_started_at",
        "reviewed_at",
        "processed_at",
        "captured_at",
        "analysis_type",
        "plot_id",
        "organization_ref",
        "tenant_ref",
    ):
        op.drop_column("dbi_campaigns", column_name)

    op.create_check_constraint(
        "ck_dbi_campaigns_status",
        "dbi_campaigns",
        "status IN ('planned', 'active', 'completed', 'cancelled')",
    )
