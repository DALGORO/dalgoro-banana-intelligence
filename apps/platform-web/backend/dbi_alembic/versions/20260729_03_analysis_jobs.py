"""Crea persistencia de trabajos e intentos geoespaciales DBI.

Revision ID: dbi_0003_analysis_jobs
Revises: dbi_0002_agricultural_domain
Create Date: 2026-07-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0003_analysis_jobs"
down_revision: Union[str, Sequence[str], None] = (
    "dbi_0002_agricultural_domain"
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
    """Crea únicamente trabajos e intentos sobre el dominio DBI."""

    op.create_table(
        "dbi_analysis_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("plot_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column(
            "orthophoto_asset_ref",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "boundary_asset_ref",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "exclusions_asset_ref",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "model_version_ref",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "pipeline_config_version",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "requested_by_ref",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column("command_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="accepted",
            nullable=False,
        ),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        *_audit_columns(),
        sa.CheckConstraint(
            "status IN ("
            "'accepted', 'queued', 'running', 'succeeded', 'failed', "
            "'cancel_requested', 'canceled'"
            ")",
            name="ck_dbi_analysis_jobs_status",
        ),
        sa.CheckConstraint(
            "command_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_analysis_jobs_command_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["dbi_farms.id"],
            name="fk_dbi_analysis_jobs_farm_id_dbi_farms",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plot_id"],
            ["dbi_plots.id"],
            name="fk_dbi_analysis_jobs_plot_id_dbi_plots",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["dbi_campaigns.id"],
            name="fk_dbi_analysis_jobs_campaign_id_dbi_campaigns",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_analysis_jobs"),
        sa.UniqueConstraint(
            "tenant_ref",
            "request_id",
            name="uq_dbi_analysis_jobs_tenant_request",
        ),
    )
    op.create_index(
        "ix_dbi_analysis_jobs_tenant_ref",
        "dbi_analysis_jobs",
        ["tenant_ref"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_analysis_jobs_farm_id",
        "dbi_analysis_jobs",
        ["farm_id"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_analysis_jobs_status",
        "dbi_analysis_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_analysis_jobs_correlation_id",
        "dbi_analysis_jobs",
        ["correlation_id"],
        unique=False,
    )

    op.create_table(
        "dbi_analysis_job_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("worker_ref", sa.String(length=128), nullable=True),
        sa.Column(
            "pipeline_build_ref",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column("result_sha256", sa.String(length=64), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column(
            "queued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_dbi_analysis_job_attempts_positive_number",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'canceled')",
            name="ck_dbi_analysis_job_attempts_status",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= queued_at",
            name="ck_dbi_analysis_job_attempts_start_order",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR "
            "(started_at IS NOT NULL AND finished_at >= started_at)",
            name="ck_dbi_analysis_job_attempts_finish_order",
        ),
        sa.CheckConstraint(
            "result_sha256 IS NULL OR "
            "result_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_analysis_job_attempts_result_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["dbi_analysis_jobs.id"],
            name=(
                "fk_dbi_analysis_job_attempts_job_id_"
                "dbi_analysis_jobs"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_dbi_analysis_job_attempts",
        ),
        sa.UniqueConstraint(
            "job_id",
            "attempt_number",
            name="uq_dbi_analysis_job_attempts_job_number",
        ),
    )
    op.create_index(
        "ix_dbi_analysis_job_attempts_job_id",
        "dbi_analysis_job_attempts",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_analysis_job_attempts_status",
        "dbi_analysis_job_attempts",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Revierte trabajos e intentos en orden inverso."""

    op.drop_table("dbi_analysis_job_attempts")
    op.drop_table("dbi_analysis_jobs")
