"""Create governed model, pipeline and Champion/Challenger registry.

Revision ID: dbi_0013_model_registry
Revises: dbi_0012_durable_delivery
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0013_model_registry"
down_revision: str | None = "dbi_0012_durable_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPAQUE_64 = "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
OPAQUE_128 = "^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
LIFECYCLE = "status IN ('draft', 'validated', 'approved', 'retired')"
LIFECYCLE_TIMESTAMPS = (
    "(status IN ('draft', 'validated') AND approved_at IS NULL "
    "AND approved_by_ref IS NULL AND retired_at IS NULL) OR "
    "(status = 'approved' AND approved_at IS NOT NULL "
    "AND approved_by_ref IS NOT NULL AND retired_at IS NULL) OR "
    "(status = 'retired' AND approved_at IS NOT NULL "
    "AND approved_by_ref IS NOT NULL AND retired_at IS NOT NULL)"
)


def upgrade() -> None:
    """Persist scientific lineage and explicit operational governance."""

    op.create_table(
        "dbi_model_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_family", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("training_dataset_version", sa.String(length=128), nullable=False),
        sa.Column("validation_dataset_version", sa.String(length=128), nullable=False),
        sa.Column("input_contract_version", sa.String(length=128), nullable=False),
        sa.Column("output_contract_version", sa.String(length=128), nullable=False),
        sa.Column("artifact_ref", sa.String(length=128), nullable=True),
        sa.Column("metrics_json", sa.Text(), nullable=True),
        sa.Column("metrics_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_by_ref", sa.String(length=128), nullable=False),
        sa.Column("approved_by_ref", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_model_versions"),
        sa.UniqueConstraint(
            "model_family",
            "model_version",
            name="uq_dbi_model_versions_family_version",
        ),
        sa.UniqueConstraint(
            "id",
            "model_family",
            name="uq_dbi_model_versions_id_family",
        ),
        sa.CheckConstraint(LIFECYCLE, name="ck_dbi_model_versions_status"),
        sa.CheckConstraint(
            f"model_family ~ '{OPAQUE_64}'",
            name="ck_dbi_model_versions_family",
        ),
        sa.CheckConstraint(
            f"model_version ~ '{OPAQUE_128}'",
            name="ck_dbi_model_versions_version",
        ),
        sa.CheckConstraint(
            f"training_dataset_version ~ '{OPAQUE_128}'",
            name="ck_dbi_model_versions_training_dataset",
        ),
        sa.CheckConstraint(
            f"validation_dataset_version ~ '{OPAQUE_128}'",
            name="ck_dbi_model_versions_validation_dataset",
        ),
        sa.CheckConstraint(
            f"input_contract_version ~ '{OPAQUE_128}'",
            name="ck_dbi_model_versions_input_contract",
        ),
        sa.CheckConstraint(
            f"output_contract_version ~ '{OPAQUE_128}'",
            name="ck_dbi_model_versions_output_contract",
        ),
        sa.CheckConstraint(
            f"artifact_ref IS NULL OR artifact_ref ~ '{OPAQUE_128}'",
            name="ck_dbi_model_versions_artifact_ref",
        ),
        sa.CheckConstraint(
            "(metrics_json IS NULL AND metrics_sha256 IS NULL) OR "
            "(metrics_json IS NOT NULL AND metrics_sha256 ~ '^[0-9a-f]{64}$' "
            "AND octet_length(metrics_json) BETWEEN 2 AND 65536)",
            name="ck_dbi_model_versions_metrics",
        ),
        sa.CheckConstraint(
            LIFECYCLE_TIMESTAMPS,
            name="ck_dbi_model_versions_lifecycle",
        ),
    )
    op.create_index(
        "ix_dbi_model_versions_family_status",
        "dbi_model_versions",
        ["model_family", "status"],
    )

    op.create_table(
        "dbi_pipeline_config_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_family", sa.String(length=64), nullable=False),
        sa.Column("config_version", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("config_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by_ref", sa.String(length=128), nullable=False),
        sa.Column("approved_by_ref", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_pipeline_config_versions"),
        sa.UniqueConstraint(
            "model_family",
            "config_version",
            name="uq_dbi_pipeline_configs_family_version",
        ),
        sa.UniqueConstraint(
            "id",
            "model_family",
            name="uq_dbi_pipeline_configs_id_family",
        ),
        sa.CheckConstraint(LIFECYCLE, name="ck_dbi_pipeline_configs_status"),
        sa.CheckConstraint(
            f"model_family ~ '{OPAQUE_64}'",
            name="ck_dbi_pipeline_configs_family",
        ),
        sa.CheckConstraint(
            f"config_version ~ '{OPAQUE_128}'",
            name="ck_dbi_pipeline_configs_version",
        ),
        sa.CheckConstraint(
            "config_sha256 ~ '^[0-9a-f]{64}$' "
            "AND octet_length(config_json) BETWEEN 2 AND 65536",
            name="ck_dbi_pipeline_configs_payload",
        ),
        sa.CheckConstraint(
            LIFECYCLE_TIMESTAMPS,
            name="ck_dbi_pipeline_configs_lifecycle",
        ),
    )
    op.create_index(
        "ix_dbi_pipeline_configs_family_status",
        "dbi_pipeline_config_versions",
        ["model_family", "status"],
    )

    op.create_table(
        "dbi_analysis_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("model_family", sa.String(length=64), nullable=False),
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_config_id", sa.Uuid(), nullable=False),
        sa.Column("policy_ref", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=16), server_default="challenger", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("created_by_ref", sa.String(length=128), nullable=False),
        sa.Column("retired_by_ref", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_analysis_profiles"),
        sa.ForeignKeyConstraint(
            ["model_version_id", "model_family"],
            ["dbi_model_versions.id", "dbi_model_versions.model_family"],
            name="fk_dbi_analysis_profiles_model_family",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_config_id", "model_family"],
            [
                "dbi_pipeline_config_versions.id",
                "dbi_pipeline_config_versions.model_family",
            ],
            name="fk_dbi_analysis_profiles_pipeline_family",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "policy_ref",
            name="uq_dbi_analysis_profiles_tenant_policy",
        ),
        sa.CheckConstraint(
            "role IN ('champion', 'challenger')",
            name="ck_dbi_analysis_profiles_role",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'retired')",
            name="ck_dbi_analysis_profiles_status",
        ),
        sa.CheckConstraint(
            f"tenant_ref ~ '{OPAQUE_128}'",
            name="ck_dbi_analysis_profiles_tenant",
        ),
        sa.CheckConstraint(
            f"model_family ~ '{OPAQUE_64}'",
            name="ck_dbi_analysis_profiles_family",
        ),
        sa.CheckConstraint(
            f"policy_ref ~ '{OPAQUE_128}'",
            name="ck_dbi_analysis_profiles_policy",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND retired_at IS NULL AND retired_by_ref IS NULL) OR "
            "(status = 'retired' AND retired_at IS NOT NULL AND retired_by_ref IS NOT NULL)",
            name="ck_dbi_analysis_profiles_lifecycle",
        ),
    )
    op.create_index(
        "ix_dbi_analysis_profiles_tenant_family",
        "dbi_analysis_profiles",
        ["tenant_ref", "model_family"],
    )
    op.create_index(
        "uq_dbi_analysis_profiles_active_champion",
        "dbi_analysis_profiles",
        ["tenant_ref", "model_family"],
        unique=True,
        postgresql_where=sa.text("role = 'champion' AND status = 'active'"),
    )

    op.create_table(
        "dbi_model_governance_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("model_family", sa.String(length=64), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=True),
        sa.Column("model_version_id", sa.Uuid(), nullable=True),
        sa.Column("pipeline_config_id", sa.Uuid(), nullable=True),
        sa.Column("profile_id", sa.Uuid(), nullable=True),
        sa.Column("previous_champion_profile_id", sa.Uuid(), nullable=True),
        sa.Column("actor_ref", sa.String(length=128), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_model_governance_events"),
        sa.CheckConstraint(
            "action IN ("
            "'model_registered', 'model_validated', 'model_approved', 'model_retired', "
            "'pipeline_registered', 'pipeline_validated', 'pipeline_approved', "
            "'pipeline_retired', 'profile_registered', 'champion_promoted', "
            "'profile_retired'"
            ")",
            name="ck_dbi_model_governance_events_action",
        ),
        sa.CheckConstraint(
            f"model_family ~ '{OPAQUE_64}'",
            name="ck_dbi_model_governance_events_family",
        ),
        sa.CheckConstraint(
            f"actor_ref ~ '{OPAQUE_128}'",
            name="ck_dbi_model_governance_events_actor",
        ),
        sa.CheckConstraint(
            f"tenant_ref IS NULL OR tenant_ref ~ '{OPAQUE_128}'",
            name="ck_dbi_model_governance_events_tenant",
        ),
    )
    op.create_index(
        "ix_dbi_model_governance_events_family_occurred",
        "dbi_model_governance_events",
        ["model_family", "occurred_at"],
    )
    op.create_index(
        "ix_dbi_model_governance_events_tenant_occurred",
        "dbi_model_governance_events",
        ["tenant_ref", "occurred_at"],
    )


def downgrade() -> None:
    """Remove ML governance without touching Jobs, Queue or assets."""

    op.drop_table("dbi_model_governance_events")
    op.drop_table("dbi_analysis_profiles")
    op.drop_table("dbi_pipeline_config_versions")
    op.drop_table("dbi_model_versions")
