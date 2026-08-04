"""Persistencia durable y multicliente para cargas multipartes DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.dbi_base import DBIBase

if TYPE_CHECKING:
    from app.dbi.models.assets import AnalysisInputAsset


def utc_now() -> datetime:
    """Devuelve una fecha consciente de zona horaria en UTC."""

    return datetime.now(timezone.utc)


MULTIPART_SESSION_STATUS_CHECK = (
    "status IN ("
    "'initiated', 'uploading', "
    "'completed_pending_content_verification', "
    "'aborted', 'expired', 'blocked_by_policy'"
    ")"
)
MULTIPART_REASON_CHECK = (
    "reason_code IS NULL OR reason_code IN ("
    "'asset_multipart_size_exceeds_policy', "
    "'asset_multipart_part_count_exceeds_policy'"
    ")"
)
MULTIPART_PROVIDER_CONTEXT_CHECK = (
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
    "OR provider_upload_ref IS NOT NULL))"
)
MULTIPART_CHECKSUM_PAIR_CHECK = (
    "(checksum_algorithm = 'SHA256' AND checksum_type = 'COMPOSITE') "
    "OR (checksum_algorithm IN ('CRC32', 'CRC32C') "
    "AND checksum_type IN ('COMPOSITE', 'FULL_OBJECT')) "
    "OR (checksum_algorithm = 'CRC64NVME' "
    "AND checksum_type = 'FULL_OBJECT')"
)
MULTIPART_TERMINAL_TIMESTAMPS_CHECK = (
    "((status = 'completed_pending_content_verification') "
    "= (completed_at IS NOT NULL)) "
    "AND ((status = 'aborted') = (aborted_at IS NOT NULL)) "
    "AND ((status = 'expired') = (expired_at IS NOT NULL))"
)
SHA256_HEX_CHECK_TEMPLATE = "{column} ~ '^[0-9a-f]{{64}}$'"


class AssetMultipartSession(DBIBase):
    """Sesión durable separada del ciclo de vida del activo maestro."""

    __tablename__ = "dbi_asset_multipart_sessions"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "tenant_ref",
            name="uq_dbi_multipart_sessions_id_tenant",
        ),
        UniqueConstraint(
            "tenant_ref",
            "idempotency_key_hash",
            name="uq_dbi_multipart_sessions_idempotency",
        ),
        ForeignKeyConstraint(
            ["asset_id", "tenant_ref"],
            [
                "dbi_analysis_input_assets.id",
                "dbi_analysis_input_assets.tenant_ref",
            ],
            name="fk_dbi_multipart_sessions_asset_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            MULTIPART_SESSION_STATUS_CHECK,
            name="ck_dbi_multipart_sessions_status",
        ),
        CheckConstraint(
            MULTIPART_REASON_CHECK,
            name="ck_dbi_multipart_sessions_reason",
        ),
        CheckConstraint(
            MULTIPART_PROVIDER_CONTEXT_CHECK,
            name="ck_dbi_multipart_sessions_provider_context",
        ),
        CheckConstraint(
            "provider_upload_ref IS NULL "
            "OR (length(provider_upload_ref) > 0 "
            "AND btrim(provider_upload_ref) = provider_upload_ref)",
            name="ck_dbi_multipart_sessions_provider_ref",
        ),
        CheckConstraint(
            "size_bytes > 0",
            name="ck_dbi_multipart_sessions_positive_size",
        ),
        CheckConstraint(
            "part_size_bytes IS NULL OR part_size_bytes > 0",
            name="ck_dbi_multipart_sessions_positive_part_size",
        ),
        CheckConstraint(
            "part_count IS NULL OR part_count BETWEEN 1 AND 10000",
            name="ck_dbi_multipart_sessions_part_count",
        ),
        CheckConstraint(
            "max_grants_per_window IS NULL "
            "OR max_grants_per_window BETWEEN 1 AND part_count",
            name="ck_dbi_multipart_sessions_grant_window",
        ),
        CheckConstraint(
            "max_client_concurrency IS NULL "
            "OR max_client_concurrency BETWEEN 1 AND max_grants_per_window",
            name="ck_dbi_multipart_sessions_concurrency",
        ),
        CheckConstraint(
            MULTIPART_CHECKSUM_PAIR_CHECK,
            name="ck_dbi_multipart_sessions_checksum_pair",
        ),
        CheckConstraint(
            SHA256_HEX_CHECK_TEMPLATE.format(column="idempotency_key_hash"),
            name="ck_dbi_multipart_sessions_idempotency_hash",
        ),
        CheckConstraint(
            SHA256_HEX_CHECK_TEMPLATE.format(column="request_fingerprint"),
            name="ck_dbi_multipart_sessions_request_fingerprint",
        ),
        CheckConstraint(
            "version > 0",
            name="ck_dbi_multipart_sessions_positive_version",
        ),
        CheckConstraint(
            MULTIPART_TERMINAL_TIMESTAMPS_CHECK,
            name="ck_dbi_multipart_sessions_terminal_timestamps",
        ),
        CheckConstraint(
            "status NOT IN ('initiated', 'uploading') "
            "OR expires_at IS NOT NULL",
            name="ck_dbi_multipart_sessions_active_expiry",
        ),
        CheckConstraint(
            "updated_at >= created_at "
            "AND last_activity_at >= created_at "
            "AND (completed_at IS NULL OR completed_at >= created_at) "
            "AND (aborted_at IS NULL OR aborted_at >= created_at) "
            "AND (expired_at IS NULL OR expired_at >= created_at)",
            name="ck_dbi_multipart_sessions_timestamp_order",
        ),
        Index("ix_dbi_multipart_sessions_tenant_ref", "tenant_ref"),
        Index("ix_dbi_multipart_sessions_asset_id", "asset_id"),
        Index(
            "ix_dbi_multipart_sessions_cleanup",
            "status",
            "expires_at",
        ),
        Index(
            "uq_dbi_multipart_sessions_active_asset",
            "tenant_ref",
            "asset_id",
            unique=True,
            postgresql_where=text("status IN ('initiated', 'uploading')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        default="initiated",
    )
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_upload_ref: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    part_size_bytes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    part_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_grants_per_window: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    max_client_concurrency: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    checksum_algorithm: Mapped[str] = mapped_column(String(16), nullable=False)
    checksum_type: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    request_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    created_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    aborted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    asset: Mapped["AnalysisInputAsset"] = relationship()
    parts: Mapped[list["AssetMultipartPart"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AssetMultipartPart(DBIBase):
    """Evidencia exacta y ordenable de una parte transferida."""

    __tablename__ = "dbi_asset_multipart_parts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "tenant_ref"],
            [
                "dbi_asset_multipart_sessions.id",
                "dbi_asset_multipart_sessions.tenant_ref",
            ],
            name="fk_dbi_multipart_parts_session_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "part_number BETWEEN 1 AND 10000",
            name="ck_dbi_multipart_parts_number",
        ),
        CheckConstraint(
            "size_bytes > 0",
            name="ck_dbi_multipart_parts_positive_size",
        ),
        CheckConstraint(
            "checksum ~ '^[A-Za-z0-9+/]+={0,2}$'",
            name="ck_dbi_multipart_parts_checksum",
        ),
        CheckConstraint(
            "length(etag) BETWEEN 1 AND 256 "
            "AND etag !~ '[[:space:][:cntrl:]]'",
            name="ck_dbi_multipart_parts_etag",
        ),
        Index("ix_dbi_multipart_parts_tenant_ref", "tenant_ref"),
    )

    session_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    part_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    etag: Mapped[str] = mapped_column(String(256), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    session: Mapped[AssetMultipartSession] = relationship(
        back_populates="parts",
    )
