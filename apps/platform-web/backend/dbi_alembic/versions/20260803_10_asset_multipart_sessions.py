"""Persist multipart asset sessions and exact part evidence.

Revision ID: dbi_0010_asset_multipart
Revises: dbi_0009_object_key_check
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "dbi_0010_asset_multipart"
down_revision: str | None = "dbi_0009_object_key_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create tenant-safe multipart sessions and their exact parts."""

    op.create_unique_constraint(
        "uq_dbi_analysis_input_assets_id_tenant",
        "dbi_analysis_input_assets",
        ["id", "tenant_ref"],
    )

    op.create_table(
        "dbi_asset_multipart_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=48),
            server_default="initiated",
            nullable=False,
        ),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column(
            "provider_upload_ref",
            sa.String(length=1024),
            nullable=True,
        ),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("part_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("part_count", sa.Integer(), nullable=True),
        sa.Column("max_grants_per_window", sa.Integer(), nullable=True),
        sa.Column("max_client_concurrency", sa.Integer(), nullable=True),
        sa.Column(
            "checksum_algorithm",
            sa.String(length=16),
            nullable=False,
        ),
        sa.Column("checksum_type", sa.String(length=16), nullable=False),
        sa.Column(
            "idempotency_key_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "request_fingerprint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("created_by_ref", sa.String(length=128), nullable=False),
        sa.Column(
            "version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aborted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "status IN ("
            "'initiated', 'uploading', "
            "'completed_pending_content_verification', "
            "'aborted', 'expired', 'blocked_by_policy'"
            ")",
            name="ck_dbi_multipart_sessions_status",
        ),
        sa.CheckConstraint(
            "reason_code IS NULL OR reason_code IN ("
            "'asset_multipart_size_exceeds_policy', "
            "'asset_multipart_part_count_exceeds_policy'"
            ")",
            name="ck_dbi_multipart_sessions_reason",
        ),
        sa.CheckConstraint(
            "(status = 'blocked_by_policy' "
            "AND reason_code IS NOT NULL "
            "AND provider_upload_ref IS NULL "
            "AND part_size_bytes IS NULL "
            "AND part_count IS NULL "
            "AND max_grants_per_window IS NULL "
            "AND max_client_concurrency IS NULL) "
            "OR "
            "(status <> 'blocked_by_policy' "
            "AND reason_code IS NULL "
            "AND part_size_bytes IS NOT NULL "
            "AND part_count IS NOT NULL "
            "AND max_grants_per_window IS NOT NULL "
            "AND max_client_concurrency IS NOT NULL "
            "AND (status IN ('initiated', 'aborted', 'expired') "
            "OR provider_upload_ref IS NOT NULL))",
            name="ck_dbi_multipart_sessions_provider_context",
        ),
        sa.CheckConstraint(
            "provider_upload_ref IS NULL "
            "OR (length(provider_upload_ref) > 0 "
            "AND btrim(provider_upload_ref) = provider_upload_ref)",
            name="ck_dbi_multipart_sessions_provider_ref",
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_dbi_multipart_sessions_positive_size",
        ),
        sa.CheckConstraint(
            "part_size_bytes IS NULL OR part_size_bytes > 0",
            name="ck_dbi_multipart_sessions_positive_part_size",
        ),
        sa.CheckConstraint(
            "part_count IS NULL OR part_count BETWEEN 1 AND 10000",
            name="ck_dbi_multipart_sessions_part_count",
        ),
        sa.CheckConstraint(
            "max_grants_per_window IS NULL "
            "OR max_grants_per_window BETWEEN 1 AND part_count",
            name="ck_dbi_multipart_sessions_grant_window",
        ),
        sa.CheckConstraint(
            "max_client_concurrency IS NULL "
            "OR max_client_concurrency BETWEEN 1 AND max_grants_per_window",
            name="ck_dbi_multipart_sessions_concurrency",
        ),
        sa.CheckConstraint(
            "(checksum_algorithm = 'SHA256' "
            "AND checksum_type = 'COMPOSITE') "
            "OR (checksum_algorithm IN ('CRC32', 'CRC32C') "
            "AND checksum_type IN ('COMPOSITE', 'FULL_OBJECT')) "
            "OR (checksum_algorithm = 'CRC64NVME' "
            "AND checksum_type = 'FULL_OBJECT')",
            name="ck_dbi_multipart_sessions_checksum_pair",
        ),
        sa.CheckConstraint(
            "idempotency_key_hash ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_multipart_sessions_idempotency_hash",
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_multipart_sessions_request_fingerprint",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_dbi_multipart_sessions_positive_version",
        ),
        sa.CheckConstraint(
            "((status = 'completed_pending_content_verification') "
            "= (completed_at IS NOT NULL)) "
            "AND ((status = 'aborted') = (aborted_at IS NOT NULL)) "
            "AND ((status = 'expired') = (expired_at IS NOT NULL))",
            name="ck_dbi_multipart_sessions_terminal_timestamps",
        ),
        sa.CheckConstraint(
            "status NOT IN ('initiated', 'uploading') "
            "OR expires_at IS NOT NULL",
            name="ck_dbi_multipart_sessions_active_expiry",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at "
            "AND last_activity_at >= created_at "
            "AND (completed_at IS NULL OR completed_at >= created_at) "
            "AND (aborted_at IS NULL OR aborted_at >= created_at) "
            "AND (expired_at IS NULL OR expired_at >= created_at)",
            name="ck_dbi_multipart_sessions_timestamp_order",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "tenant_ref"],
            [
                "dbi_analysis_input_assets.id",
                "dbi_analysis_input_assets.tenant_ref",
            ],
            name="fk_dbi_multipart_sessions_asset_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_dbi_asset_multipart_sessions",
        ),
        sa.UniqueConstraint(
            "id",
            "tenant_ref",
            name="uq_dbi_multipart_sessions_id_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "idempotency_key_hash",
            name="uq_dbi_multipart_sessions_idempotency",
        ),
    )
    op.create_index(
        "ix_dbi_multipart_sessions_tenant_ref",
        "dbi_asset_multipart_sessions",
        ["tenant_ref"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_multipart_sessions_asset_id",
        "dbi_asset_multipart_sessions",
        ["asset_id"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_multipart_sessions_cleanup",
        "dbi_asset_multipart_sessions",
        ["status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "uq_dbi_multipart_sessions_active_asset",
        "dbi_asset_multipart_sessions",
        ["tenant_ref", "asset_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('initiated', 'uploading')"),
    )

    op.create_table(
        "dbi_asset_multipart_parts",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("part_number", sa.Integer(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("etag", sa.String(length=256), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "part_number BETWEEN 1 AND 10000",
            name="ck_dbi_multipart_parts_number",
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_dbi_multipart_parts_positive_size",
        ),
        sa.CheckConstraint(
            "checksum ~ '^[A-Za-z0-9+/]+={0,2}$'",
            name="ck_dbi_multipart_parts_checksum",
        ),
        sa.CheckConstraint(
            "length(etag) BETWEEN 1 AND 256 "
            "AND etag !~ '[[:space:][:cntrl:]]'",
            name="ck_dbi_multipart_parts_etag",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "tenant_ref"],
            [
                "dbi_asset_multipart_sessions.id",
                "dbi_asset_multipart_sessions.tenant_ref",
            ],
            name="fk_dbi_multipart_parts_session_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "session_id",
            "part_number",
            name="pk_dbi_asset_multipart_parts",
        ),
    )
    op.create_index(
        "ix_dbi_multipart_parts_tenant_ref",
        "dbi_asset_multipart_parts",
        ["tenant_ref"],
        unique=False,
    )


def downgrade() -> None:
    """Remove multipart persistence before its supporting asset key."""

    op.drop_table("dbi_asset_multipart_parts")
    op.drop_table("dbi_asset_multipart_sessions")
    op.drop_constraint(
        "uq_dbi_analysis_input_assets_id_tenant",
        "dbi_analysis_input_assets",
        type_="unique",
    )
