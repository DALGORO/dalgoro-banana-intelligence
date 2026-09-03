"""Persistencia de transporte durable DBI, separada del dominio de resultados."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.dbi_base import DBIBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DBIDeliveryMessage(DBIBase):
    """Envelope durable pequeño; nunca almacena binarios del pipeline."""

    __tablename__ = "dbi_delivery_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["attempt_id", "job_id"],
            [
                "dbi_analysis_job_attempts.id",
                "dbi_analysis_job_attempts.job_id",
            ],
            name="fk_dbi_delivery_messages_attempt_job",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "stream",
            "attempt_id",
            name="uq_dbi_delivery_messages_stream_attempt",
        ),
        CheckConstraint(
            "stream IN ('analysis_command', 'analysis_result')",
            name="ck_dbi_delivery_messages_stream",
        ),
        CheckConstraint(
            "status IN ('pending', 'leased', 'delivered', 'dead_letter')",
            name="ck_dbi_delivery_messages_status",
        ),
        CheckConstraint(
            "schema_version IN ('analysis-job-command.v1', 'analysis-job-result.v1')",
            name="ck_dbi_delivery_messages_schema",
        ),
        CheckConstraint(
            "(stream = 'analysis_command' AND schema_version = 'analysis-job-command.v1') "
            "OR (stream = 'analysis_result' AND schema_version = 'analysis-job-result.v1')",
            name="ck_dbi_delivery_messages_stream_schema",
        ),
        CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_delivery_messages_sha256",
        ),
        CheckConstraint(
            "octet_length(payload_json) BETWEEN 2 AND 1048576",
            name="ck_dbi_delivery_messages_payload_size",
        ),
        CheckConstraint(
            "delivery_count BETWEEN 0 AND 100 "
            "AND max_deliveries BETWEEN 1 AND 100 "
            "AND delivery_count <= max_deliveries",
            name="ck_dbi_delivery_messages_delivery_count",
        ),
        CheckConstraint(
            "(status = 'leased' AND lease_ref IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND delivered_at IS NULL) "
            "OR (status <> 'leased' AND lease_ref IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_dbi_delivery_messages_active_lease",
        ),
        CheckConstraint(
            "(status = 'delivered' AND delivered_at IS NOT NULL) "
            "OR (status <> 'delivered' AND delivered_at IS NULL)",
            name="ck_dbi_delivery_messages_delivered_at",
        ),
        CheckConstraint(
            "last_error_code IS NULL OR (length(last_error_code) BETWEEN 1 AND 64 "
            "AND btrim(last_error_code) = last_error_code "
            "AND last_error_code ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')",
            name="ck_dbi_delivery_messages_error_code",
        ),
        Index(
            "ix_dbi_delivery_messages_claim",
            "stream",
            "status",
            "available_at",
        ),
        Index(
            "ix_dbi_delivery_messages_lease_expiry",
            "lease_expires_at",
        ),
        Index("ix_dbi_delivery_messages_job", "job_id"),
        Index("ix_dbi_delivery_messages_correlation", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    stream: Mapped[str] = mapped_column(String(32), nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    attempt_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )
    delivery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_deliveries: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    lease_ref: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_lease_ref: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
