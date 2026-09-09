"""Catálogo versionado de productos técnicos vinculados a Campaign DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.dbi_base import DBIBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


_SHA_CHECK = "sha256 ~ '^[0-9a-f]{64}$'"
_ARTIFACT_TYPES = (
    "'orthophoto_source', 'boundary', 'validated_inventory', "
    "'density_hexagons', 'planting_candidates', 'operational_priority', "
    "'kde', 'exclusions', 'technical_report', 'sampling_plan', "
    "'sampling_points', 'field_observations'"
)


class DBICampaignArtifact(DBIBase):
    """Referencia técnica versionada; no duplica los bytes del activo fuente."""

    __tablename__ = "dbi_campaign_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "artifact_type",
            "version",
            name="uq_dbi_campaign_artifacts_type_version",
        ),
        UniqueConstraint(
            "campaign_id",
            "artifact_type",
            "source_kind",
            "source_ref",
            name="uq_dbi_campaign_artifacts_source",
        ),
        CheckConstraint(
            f"artifact_type IN ({_ARTIFACT_TYPES})",
            name="ck_dbi_campaign_artifacts_type",
        ),
        CheckConstraint(
            "source_kind IN ('input_asset', 'analysis_artifact', 'domain_record')",
            name="ck_dbi_campaign_artifacts_source_kind",
        ),
        CheckConstraint(
            "technical_status IN ('current', 'superseded')",
            name="ck_dbi_campaign_artifacts_technical_status",
        ),
        CheckConstraint(
            "version > 0",
            name="ck_dbi_campaign_artifacts_positive_version",
        ),
        CheckConstraint(
            _SHA_CHECK,
            name="ck_dbi_campaign_artifacts_sha256",
        ),
        Index("ix_dbi_campaign_artifacts_campaign", "campaign_id"),
        Index("ix_dbi_campaign_artifacts_type", "artifact_type"),
        Index("ix_dbi_campaign_artifacts_source_ref", "source_kind", "source_ref"),
        Index("ix_dbi_campaign_artifacts_published", "published"),
        Index(
            "uq_dbi_campaign_artifacts_current_type",
            "campaign_id",
            "artifact_type",
            unique=True,
            postgresql_where=text("technical_status = 'current'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    technical_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="current",
    )
    published: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    source_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
