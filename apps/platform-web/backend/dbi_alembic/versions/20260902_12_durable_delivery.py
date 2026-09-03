"""Create durable command/result delivery messages.

Revision ID: dbi_0012_durable_delivery
Revises: dbi_0011_flight_manifest
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0012_durable_delivery"
down_revision: str | None = "dbi_0011_flight_manifest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add an isolated durable transport table without storing binaries."""

    # Algunos fixtures de verificación construyen el esquema final desde metadata
    # antes de recorrer Alembic. La constraint es obligatoria, pero su creación debe
    # converger tanto desde el linaje histórico como desde ese esquema final.
    op.execute(
        """
        DO $dbi$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_dbi_analysis_job_attempts_id_job'
                  AND conrelid = 'dbi_analysis_job_attempts'::regclass
            ) THEN
                ALTER TABLE dbi_analysis_job_attempts
                ADD CONSTRAINT uq_dbi_analysis_job_attempts_id_job
                UNIQUE (id, job_id);
            END IF;
        END
        $dbi$;
        """
    )

    op.create_table(
        "dbi_delivery_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("stream", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "delivery_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "max_deliveries",
            sa.Integer(),
            server_default="5",
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("lease_ref", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_lease_ref", sa.Uuid(), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_dbi_delivery_messages"),
        sa.ForeignKeyConstraint(
            ["attempt_id", "job_id"],
            ["dbi_analysis_job_attempts.id", "dbi_analysis_job_attempts.job_id"],
            name="fk_dbi_delivery_messages_attempt_job",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "stream",
            "attempt_id",
            name="uq_dbi_delivery_messages_stream_attempt",
        ),
        sa.CheckConstraint(
            "stream IN ('analysis_command', 'analysis_result')",
            name="ck_dbi_delivery_messages_stream",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'leased', 'delivered', 'dead_letter')",
            name="ck_dbi_delivery_messages_status",
        ),
        sa.CheckConstraint(
            "schema_version IN ('analysis-job-command.v1', 'analysis-job-result.v1')",
            name="ck_dbi_delivery_messages_schema",
        ),
        sa.CheckConstraint(
            "(stream = 'analysis_command' AND schema_version = 'analysis-job-command.v1') "
            "OR (stream = 'analysis_result' AND schema_version = 'analysis-job-result.v1')",
            name="ck_dbi_delivery_messages_stream_schema",
        ),
        sa.CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_delivery_messages_sha256",
        ),
        sa.CheckConstraint(
            "octet_length(payload_json) BETWEEN 2 AND 1048576",
            name="ck_dbi_delivery_messages_payload_size",
        ),
        sa.CheckConstraint(
            "delivery_count BETWEEN 0 AND 100 "
            "AND max_deliveries BETWEEN 1 AND 100 "
            "AND delivery_count <= max_deliveries",
            name="ck_dbi_delivery_messages_delivery_count",
        ),
        sa.CheckConstraint(
            "(status = 'leased' AND lease_ref IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND delivered_at IS NULL) "
            "OR (status <> 'leased' AND lease_ref IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_dbi_delivery_messages_active_lease",
        ),
        sa.CheckConstraint(
            "(status = 'delivered' AND delivered_at IS NOT NULL) "
            "OR (status <> 'delivered' AND delivered_at IS NULL)",
            name="ck_dbi_delivery_messages_delivered_at",
        ),
        sa.CheckConstraint(
            "last_error_code IS NULL OR (length(last_error_code) BETWEEN 1 AND 64 "
            "AND btrim(last_error_code) = last_error_code "
            "AND last_error_code ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')",
            name="ck_dbi_delivery_messages_error_code",
        ),
    )
    op.create_index(
        "ix_dbi_delivery_messages_claim",
        "dbi_delivery_messages",
        ["stream", "status", "available_at"],
    )
    op.create_index(
        "ix_dbi_delivery_messages_lease_expiry",
        "dbi_delivery_messages",
        ["lease_expires_at"],
    )
    op.create_index(
        "ix_dbi_delivery_messages_job",
        "dbi_delivery_messages",
        ["job_id"],
    )
    op.create_index(
        "ix_dbi_delivery_messages_correlation",
        "dbi_delivery_messages",
        ["correlation_id"],
    )


def downgrade() -> None:
    """Remove only delivery persistence and its supporting uniqueness."""

    op.drop_table("dbi_delivery_messages")
    op.execute(
        """
        ALTER TABLE dbi_analysis_job_attempts
        DROP CONSTRAINT IF EXISTS uq_dbi_analysis_job_attempts_id_job
        """
    )
