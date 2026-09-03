"""Persistencia gobernada de modelos, configuraciones y perfiles ML DBI."""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.dbi_base import DBIBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


MODEL_LIFECYCLE_CHECK = "status IN ('draft', 'validated', 'approved', 'retired')"
MODEL_LIFECYCLE_TIMESTAMPS_CHECK = (
    "(status IN ('draft', 'validated') AND approved_at IS NULL "
    "AND approved_by_ref IS NULL AND retired_at IS NULL) OR "
    "(status = 'approved' AND approved_at IS NOT NULL "
    "AND approved_by_ref IS NOT NULL AND retired_at IS NULL) OR "
    "(status = 'retired' AND approved_at IS NOT NULL "
    "AND approved_by_ref IS NOT NULL AND retired_at IS NOT NULL)"
)
OPAQUE_64_CHECK = "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
OPAQUE_128_CHECK = "^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"


class DBIModelVersion(DBIBase):
    """Versión científica inmutable; los pesos viven fuera de PostgreSQL."""

    __tablename__ = "dbi_model_versions"
    __table_args__ = (
        UniqueConstraint(
            "model_family",
            "model_version",
            name="uq_dbi_model_versions_family_version",
        ),
        UniqueConstraint(
            "id",
            "model_family",
            name="uq_dbi_model_versions_id_family",
        ),
        CheckConstraint(
            MODEL_LIFECYCLE_CHECK,
            name="ck_dbi_model_versions_status",
        ),
        CheckConstraint(
            f"model_family ~ '{OPAQUE_64_CHECK}'",
            name="ck_dbi_model_versions_family",
        ),
        CheckConstraint(
            f"model_version ~ '{OPAQUE_128_CHECK}'",
            name="ck_dbi_model_versions_version",
        ),
        CheckConstraint(
            f"training_dataset_version ~ '{OPAQUE_128_CHECK}'",
            name="ck_dbi_model_versions_training_dataset",
        ),
        CheckConstraint(
            f"validation_dataset_version ~ '{OPAQUE_128_CHECK}'",
            name="ck_dbi_model_versions_validation_dataset",
        ),
        CheckConstraint(
            f"input_contract_version ~ '{OPAQUE_128_CHECK}'",
            name="ck_dbi_model_versions_input_contract",
        ),
        CheckConstraint(
            f"output_contract_version ~ '{OPAQUE_128_CHECK}'",
            name="ck_dbi_model_versions_output_contract",
        ),
        CheckConstraint(
            f"artifact_ref IS NULL OR artifact_ref ~ '{OPAQUE_128_CHECK}'",
            name="ck_dbi_model_versions_artifact_ref",
        ),
        CheckConstraint(
            "(metrics_json IS NULL AND metrics_sha256 IS NULL) OR "
            "(metrics_json IS NOT NULL AND metrics_sha256 ~ '^[0-9a-f]{64}$' "
            "AND octet_length(metrics_json) BETWEEN 2 AND 65536)",
            name="ck_dbi_model_versions_metrics",
        ),
        CheckConstraint(
            MODEL_LIFECYCLE_TIMESTAMPS_CHECK,
            name="ck_dbi_model_versions_lifecycle",
        ),
        Index(
            "ix_dbi_model_versions_family_status",
            "model_family",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    model_family: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    training_dataset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    validation_dataset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    input_contract_version: Mapped[str] = mapped_column(String(128), nullable=False)
    output_contract_version: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_by_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DBIPipelineConfigVersion(DBIBase):
    """Configuración canónica y aprobable del pipeline, sin secretos ni rutas."""

    __tablename__ = "dbi_pipeline_config_versions"
    __table_args__ = (
        UniqueConstraint(
            "model_family",
            "config_version",
            name="uq_dbi_pipeline_configs_family_version",
        ),
        UniqueConstraint(
            "id",
            "model_family",
            name="uq_dbi_pipeline_configs_id_family",
        ),
        CheckConstraint(
            MODEL_LIFECYCLE_CHECK,
            name="ck_dbi_pipeline_configs_status",
        ),
        CheckConstraint(
            f"model_family ~ '{OPAQUE_64_CHECK}'",
            name="ck_dbi_pipeline_configs_family",
        ),
        CheckConstraint(
            f"config_version ~ '{OPAQUE_128_CHECK}'",
            name="ck_dbi_pipeline_configs_version",
        ),
        CheckConstraint(
            "config_sha256 ~ '^[0-9a-f]{64}$' "
            "AND octet_length(config_json) BETWEEN 2 AND 65536",
            name="ck_dbi_pipeline_configs_payload",
        ),
        CheckConstraint(
            MODEL_LIFECYCLE_TIMESTAMPS_CHECK,
            name="ck_dbi_pipeline_configs_lifecycle",
        ),
        Index(
            "ix_dbi_pipeline_configs_family_status",
            "model_family",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    model_family: Mapped[str] = mapped_column(String(64), nullable=False)
    config_version: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_by_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DBIAnalysisProfile(DBIBase):
    """Asignación operativa de modelo + configuración a un tenant y familia."""

    __tablename__ = "dbi_analysis_profiles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["model_version_id", "model_family"],
            ["dbi_model_versions.id", "dbi_model_versions.model_family"],
            name="fk_dbi_analysis_profiles_model_family",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["pipeline_config_id", "model_family"],
            [
                "dbi_pipeline_config_versions.id",
                "dbi_pipeline_config_versions.model_family",
            ],
            name="fk_dbi_analysis_profiles_pipeline_family",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_ref",
            "policy_ref",
            name="uq_dbi_analysis_profiles_tenant_policy",
        ),
        CheckConstraint(
            "role IN ('champion', 'challenger')",
            name="ck_dbi_analysis_profiles_role",
        ),
        CheckConstraint(
            "status IN ('active', 'retired')",
            name="ck_dbi_analysis_profiles_status",
        ),
        CheckConstraint(
            f"tenant_ref ~ '{OPAQUE_128_CHECK}'",
            name="ck_dbi_analysis_profiles_tenant",
        ),
        CheckConstraint(
            f"model_family ~ '{OPAQUE_64_CHECK}'",
            name="ck_dbi_analysis_profiles_family",
        ),
        CheckConstraint(
            f"policy_ref ~ '{OPAQUE_128_CHECK}'",
            name="ck_dbi_analysis_profiles_policy",
        ),
        CheckConstraint(
            "(status = 'active' AND retired_at IS NULL AND retired_by_ref IS NULL) OR "
            "(status = 'retired' AND retired_at IS NOT NULL AND retired_by_ref IS NOT NULL)",
            name="ck_dbi_analysis_profiles_lifecycle",
        ),
        Index(
            "ix_dbi_analysis_profiles_tenant_family",
            "tenant_ref",
            "model_family",
        ),
        Index(
            "uq_dbi_analysis_profiles_active_champion",
            "tenant_ref",
            "model_family",
            unique=True,
            postgresql_where=text("role = 'champion' AND status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    model_family: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    pipeline_config_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    policy_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="challenger")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    retired_by_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DBIModelGovernanceEvent(DBIBase):
    """Evidencia append-only de cambios de gobernanza ML."""

    __tablename__ = "dbi_model_governance_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ("
            "'model_registered', 'model_validated', 'model_approved', 'model_retired', "
            "'pipeline_registered', 'pipeline_validated', 'pipeline_approved', "
            "'pipeline_retired', 'profile_registered', 'champion_promoted', "
            "'profile_retired'"
            ")",
            name="ck_dbi_model_governance_events_action",
        ),
        CheckConstraint(
            f"model_family ~ '{OPAQUE_64_CHECK}'",
            name="ck_dbi_model_governance_events_family",
        ),
        CheckConstraint(
            f"actor_ref ~ '{OPAQUE_128_CHECK}'",
            name="ck_dbi_model_governance_events_actor",
        ),
        CheckConstraint(
            f"tenant_ref IS NULL OR tenant_ref ~ '{OPAQUE_128_CHECK}'",
            name="ck_dbi_model_governance_events_tenant",
        ),
        Index(
            "ix_dbi_model_governance_events_family_occurred",
            "model_family",
            "occurred_at",
        ),
        Index(
            "ix_dbi_model_governance_events_tenant_occurred",
            "tenant_ref",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    model_family: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_version_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    pipeline_config_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    profile_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    previous_champion_profile_id: Mapped[UUID | None] = mapped_column(
        Uuid, nullable=True
    )
    actor_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
