"""Persistencia consultable e inmutable de resultados terminales DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.dbi_base import DBIBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


_SHA_CHECK = "^[0-9a-f]{64}$"


class DBIAnalysisResult(DBIBase):
    """Resultado terminal ingerido; Queue deja de ser su única representación."""

    __tablename__ = "dbi_analysis_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["attempt_id", "job_id"],
            [
                "dbi_analysis_job_attempts.id",
                "dbi_analysis_job_attempts.job_id",
            ],
            name="fk_dbi_analysis_results_attempt_job",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "attempt_id",
            name="uq_dbi_analysis_results_attempt",
        ),
        CheckConstraint(
            "schema_version = 'analysis-job-result.v1'",
            name="ck_dbi_analysis_results_schema",
        ),
        CheckConstraint(
            "status IN ('succeeded', 'failed', 'canceled')",
            name="ck_dbi_analysis_results_status",
        ),
        CheckConstraint(
            f"result_sha256 ~ '{_SHA_CHECK}'",
            name="ck_dbi_analysis_results_sha256",
        ),
        CheckConstraint(
            "length(pipeline_build_ref) BETWEEN 1 AND 128 "
            "AND btrim(pipeline_build_ref) = pipeline_build_ref",
            name="ck_dbi_analysis_results_pipeline_build",
        ),
        CheckConstraint(
            "finished_at >= started_at",
            name="ck_dbi_analysis_results_time_order",
        ),
        CheckConstraint(
            f"metrics_sha256 ~ '{_SHA_CHECK}' "
            "AND octet_length(metrics_json) BETWEEN 2 AND 65536",
            name="ck_dbi_analysis_results_metrics",
        ),
        CheckConstraint(
            f"findings_sha256 ~ '{_SHA_CHECK}' "
            "AND octet_length(findings_json) BETWEEN 2 AND 262144",
            name="ck_dbi_analysis_results_findings",
        ),
        CheckConstraint(
            f"warnings_sha256 ~ '{_SHA_CHECK}' "
            "AND octet_length(warnings_json) BETWEEN 2 AND 65536",
            name="ck_dbi_analysis_results_warnings",
        ),
        CheckConstraint(
            f"errors_sha256 ~ '{_SHA_CHECK}' "
            "AND octet_length(errors_json) BETWEEN 2 AND 65536",
            name="ck_dbi_analysis_results_errors",
        ),
        Index("ix_dbi_analysis_results_job", "job_id"),
        Index("ix_dbi_analysis_results_status", "status"),
        Index("ix_dbi_analysis_results_finished_at", "finished_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    attempt_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="analysis-job-result.v1",
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_build_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    metrics_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    findings_json: Mapped[str] = mapped_column(Text, nullable=False)
    findings_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False)
    warnings_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    errors_json: Mapped[str] = mapped_column(Text, nullable=False)
    errors_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
