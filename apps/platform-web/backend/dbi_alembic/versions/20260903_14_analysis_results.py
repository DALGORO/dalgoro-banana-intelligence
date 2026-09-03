"""Persist terminal analysis results outside durable transport.

Revision ID: dbi_0014_analysis_results
Revises: dbi_0013_model_registry
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0014_analysis_results"
down_revision: str | None = "dbi_0013_model_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SHA_CHECK = "^[0-9a-f]{64}$"


def upgrade() -> None:
    """Crea una única representación consultable por attempt."""

    op.create_table(
        "dbi_analysis_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column(
            "schema_version",
            sa.String(length=64),
            server_default="analysis-job-result.v1",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result_sha256", sa.String(length=64), nullable=False),
        sa.Column("pipeline_build_ref", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("metrics_sha256", sa.String(length=64), nullable=False),
        sa.Column("findings_json", sa.Text(), nullable=False),
        sa.Column("findings_sha256", sa.String(length=64), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("warnings_sha256", sa.String(length=64), nullable=False),
        sa.Column("errors_json", sa.Text(), nullable=False),
        sa.Column("errors_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_analysis_results"),
        sa.ForeignKeyConstraint(
            ["attempt_id", "job_id"],
            [
                "dbi_analysis_job_attempts.id",
                "dbi_analysis_job_attempts.job_id",
            ],
            name="fk_dbi_analysis_results_attempt_job",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "attempt_id",
            name="uq_dbi_analysis_results_attempt",
        ),
        sa.CheckConstraint(
            "schema_version = 'analysis-job-result.v1'",
            name="ck_dbi_analysis_results_schema",
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed', 'canceled')",
            name="ck_dbi_analysis_results_status",
        ),
        sa.CheckConstraint(
            f"result_sha256 ~ '{_SHA_CHECK}'",
            name="ck_dbi_analysis_results_sha256",
        ),
        sa.CheckConstraint(
            "length(pipeline_build_ref) BETWEEN 1 AND 128 "
            "AND btrim(pipeline_build_ref) = pipeline_build_ref",
            name="ck_dbi_analysis_results_pipeline_build",
        ),
        sa.CheckConstraint(
            "finished_at >= started_at",
            name="ck_dbi_analysis_results_time_order",
        ),
        sa.CheckConstraint(
            f"metrics_sha256 ~ '{_SHA_CHECK}' "
            "AND octet_length(metrics_json) BETWEEN 2 AND 65536",
            name="ck_dbi_analysis_results_metrics",
        ),
        sa.CheckConstraint(
            f"findings_sha256 ~ '{_SHA_CHECK}' "
            "AND octet_length(findings_json) BETWEEN 2 AND 262144",
            name="ck_dbi_analysis_results_findings",
        ),
        sa.CheckConstraint(
            f"warnings_sha256 ~ '{_SHA_CHECK}' "
            "AND octet_length(warnings_json) BETWEEN 2 AND 65536",
            name="ck_dbi_analysis_results_warnings",
        ),
        sa.CheckConstraint(
            f"errors_sha256 ~ '{_SHA_CHECK}' "
            "AND octet_length(errors_json) BETWEEN 2 AND 65536",
            name="ck_dbi_analysis_results_errors",
        ),
    )
    op.create_index(
        "ix_dbi_analysis_results_job",
        "dbi_analysis_results",
        ["job_id"],
    )
    op.create_index(
        "ix_dbi_analysis_results_status",
        "dbi_analysis_results",
        ["status"],
    )
    op.create_index(
        "ix_dbi_analysis_results_finished_at",
        "dbi_analysis_results",
        ["finished_at"],
    )


def downgrade() -> None:
    """Elimina únicamente la representación de Result."""

    op.drop_table("dbi_analysis_results")
