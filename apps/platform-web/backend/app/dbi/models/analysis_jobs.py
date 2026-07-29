"""Persistencia transaccional de trabajos e intentos geoespaciales DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.dbi_base import DBIBase

if TYPE_CHECKING:
    from app.dbi.models.agriculture import Campaign, Farm, Plot


def utc_now() -> datetime:
    """Devuelve una fecha consciente de zona horaria en UTC."""

    return datetime.now(timezone.utc)


class AnalysisJob(DBIBase):
    """Trabajo geoespacial idempotente solicitado por un tenant."""

    __tablename__ = "dbi_analysis_jobs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "request_id",
            name="uq_dbi_analysis_jobs_tenant_request",
        ),
        CheckConstraint(
            "status IN ("
            "'accepted', 'queued', 'running', 'succeeded', 'failed', "
            "'cancel_requested', 'canceled'"
            ")",
            name="ck_dbi_analysis_jobs_status",
        ),
        CheckConstraint(
            "command_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_analysis_jobs_command_sha256",
        ),
        Index("ix_dbi_analysis_jobs_tenant_ref", "tenant_ref"),
        Index("ix_dbi_analysis_jobs_farm_id", "farm_id"),
        Index("ix_dbi_analysis_jobs_status", "status"),
        Index("ix_dbi_analysis_jobs_correlation_id", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_farms.id", ondelete="RESTRICT"),
        nullable=False,
    )
    plot_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_plots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    campaign_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("dbi_campaigns.id", ondelete="RESTRICT"),
        nullable=True,
    )
    orthophoto_asset_ref: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    boundary_asset_ref: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    exclusions_asset_ref: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    model_version_ref: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    pipeline_config_version: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    requested_by_ref: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    command_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="accepted",
    )
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
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

    farm: Mapped["Farm"] = relationship()
    plot: Mapped["Plot"] = relationship()
    campaign: Mapped["Campaign | None"] = relationship()
    attempts: Mapped[list["AnalysisJobAttempt"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AnalysisJobAttempt.attempt_number",
    )


class AnalysisJobAttempt(DBIBase):
    """Intento inmutable en número dentro de un trabajo geoespacial."""

    __tablename__ = "dbi_analysis_job_attempts"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "job_id",
            name="uq_dbi_analysis_job_attempts_id_job",
        ),
        UniqueConstraint(
            "job_id",
            "attempt_number",
            name="uq_dbi_analysis_job_attempts_job_number",
        ),
        CheckConstraint(
            "attempt_number > 0",
            name="ck_dbi_analysis_job_attempts_positive_number",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'canceled')",
            name="ck_dbi_analysis_job_attempts_status",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= queued_at",
            name="ck_dbi_analysis_job_attempts_start_order",
        ),
        CheckConstraint(
            "finished_at IS NULL OR "
            "(started_at IS NOT NULL AND finished_at >= started_at)",
            name="ck_dbi_analysis_job_attempts_finish_order",
        ),
        CheckConstraint(
            "result_sha256 IS NULL OR "
            "result_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_analysis_job_attempts_result_sha256",
        ),
        Index("ix_dbi_analysis_job_attempts_job_id", "job_id"),
        Index("ix_dbi_analysis_job_attempts_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_analysis_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="queued",
    )
    worker_ref: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    pipeline_build_ref: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    result_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    failure_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
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

    job: Mapped[AnalysisJob] = relationship(back_populates="attempts")
