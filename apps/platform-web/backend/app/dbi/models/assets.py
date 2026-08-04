"""Metadatos verificables de activos y artefactos geoespaciales DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.dbi_base import DBIBase

if TYPE_CHECKING:
    from app.dbi.models.agriculture import Farm, Plot
    from app.dbi.models.analysis_jobs import AnalysisJobAttempt


def utc_now() -> datetime:
    """Devuelve una fecha consciente de zona horaria en UTC."""

    return datetime.now(timezone.utc)


OBJECT_KEY_CHECK = (
    "object_key ~ '^[A-Za-z0-9][A-Za-z0-9._/-]*$' "
    "AND object_key !~ '(^|/)\\.{1,2}(/|$)' "
    "AND object_key NOT LIKE '%//%'"
)
CONTENT_TYPE_CHECK = (
    "content_type ~ '^[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+$'"
)
SHA256_CHECK = "sha256 ~ '^[0-9a-f]{64}$'"


class AnalysisInputAsset(DBIBase):
    """Activo privado de entrada registrado para un análisis futuro."""

    __tablename__ = "dbi_analysis_input_assets"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "tenant_ref",
            name="uq_dbi_analysis_input_assets_id_tenant",
        ),
        UniqueConstraint(
            "tenant_ref",
            "object_key",
            name="uq_dbi_analysis_input_assets_tenant_object",
        ),
        CheckConstraint(
            "asset_kind IN ("
            "'orthophoto', 'boundary', 'exclusions', "
            "'flight_photo', 'flight_auxiliary'"
            ")",
            name="ck_dbi_analysis_input_assets_kind",
        ),
        CheckConstraint(
            "status IN ('registered', 'verified', 'quarantined', 'retired')",
            name="ck_dbi_analysis_input_assets_status",
        ),
        CheckConstraint(
            "size_bytes > 0",
            name="ck_dbi_analysis_input_assets_positive_size",
        ),
        CheckConstraint(
            SHA256_CHECK,
            name="ck_dbi_analysis_input_assets_sha256",
        ),
        CheckConstraint(
            CONTENT_TYPE_CHECK,
            name="ck_dbi_analysis_input_assets_content_type",
        ),
        CheckConstraint(
            OBJECT_KEY_CHECK,
            name="ck_dbi_analysis_input_assets_object_key",
        ),
        CheckConstraint(
            "status <> 'verified' OR verified_at IS NOT NULL",
            name="ck_dbi_analysis_input_assets_verification",
        ),
        Index(
            "ix_dbi_analysis_input_assets_tenant_ref",
            "tenant_ref",
        ),
        Index("ix_dbi_analysis_input_assets_farm_id", "farm_id"),
        Index("ix_dbi_analysis_input_assets_status", "status"),
        Index("ix_dbi_analysis_input_assets_sha256", "sha256"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_farms.id", ondelete="RESTRICT"),
        nullable=False,
    )
    plot_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("dbi_plots.id", ondelete="RESTRICT"),
        nullable=True,
    )
    asset_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="registered",
    )
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    crs: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(
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

    farm: Mapped["Farm"] = relationship()
    plot: Mapped["Plot | None"] = relationship()


class AnalysisArtifact(DBIBase):
    """Manifiesto inmutable de un artefacto producido por un intento."""

    __tablename__ = "dbi_analysis_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "object_key",
            name="uq_dbi_analysis_artifacts_object_key",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "job_id"],
            [
                "dbi_analysis_job_attempts.id",
                "dbi_analysis_job_attempts.job_id",
            ],
            name=(
                "fk_dbi_analysis_artifacts_attempt_job_"
                "dbi_analysis_job_attempts"
            ),
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "manifest_schema_version = 'artifact-manifest.v1'",
            name="ck_dbi_analysis_artifacts_schema_version",
        ),
        CheckConstraint(
            "role IN ("
            "'validated_inventory', 'analysis_boundary', 'hex_density', "
            "'planting_priority', 'kde_density', 'cartographic_package', "
            "'technical_report', 'pipeline_state', 'pipeline_manifest'"
            ")",
            name="ck_dbi_analysis_artifacts_role",
        ),
        CheckConstraint(
            "produced_by_stage IN ("
            "'validate_environment', 'validate_raster', "
            "'validate_boundary', 'clip_raster', 'generate_tiles', "
            "'run_yolo', 'georeference_detections', 'export_raw_gis', "
            "'deduplicate_detections', 'calculate_statistics', "
            "'analyze_spatial_pattern', 'generate_hex_density', "
            "'detect_planting_opportunities', "
            "'prioritize_planting_opportunities', "
            "'generate_kde_density', "
            "'generate_cartographic_package', "
            "'generate_technical_report'"
            ")",
            name="ck_dbi_analysis_artifacts_stage",
        ),
        CheckConstraint(
            "size_bytes > 0",
            name="ck_dbi_analysis_artifacts_positive_size",
        ),
        CheckConstraint(
            SHA256_CHECK,
            name="ck_dbi_analysis_artifacts_sha256",
        ),
        CheckConstraint(
            CONTENT_TYPE_CHECK,
            name="ck_dbi_analysis_artifacts_content_type",
        ),
        CheckConstraint(
            OBJECT_KEY_CHECK,
            name="ck_dbi_analysis_artifacts_object_key",
        ),
        Index("ix_dbi_analysis_artifacts_job_id", "job_id"),
        Index("ix_dbi_analysis_artifacts_attempt_id", "attempt_id"),
        Index("ix_dbi_analysis_artifacts_role", "role"),
        Index("ix_dbi_analysis_artifacts_sha256", "sha256"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    attempt_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    manifest_schema_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="artifact-manifest.v1",
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    produced_by_stage: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    crs: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    attempt: Mapped["AnalysisJobAttempt"] = relationship()
