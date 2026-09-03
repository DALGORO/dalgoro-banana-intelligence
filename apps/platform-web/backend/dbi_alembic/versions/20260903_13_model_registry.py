"""Create governed model registry and tenant analysis profiles.

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


def upgrade() -> None:
    """Persist scientific lineage and explicit Champion/Challenger assignments."""

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
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_model_versions"),
        sa.UniqueConstraint("model_family", "model_version", name="uq_dbi_model_versions_family_version"),
        sa.UniqueConstraint("id", "model_family", name="uq_dbi_model_versions_id_family"),
        sa.CheckConstraint("status IN ('draft', 'validated', 'approved', 'retired')", name="ck_dbi_model_versions_status"),
        sa.CheckConstraint("model_family ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'", name="ck_dbi_model_versions_family"),
        sa.CheckConstraint("model_version ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'", name="ck_dbi_model_versions_version"),
        sa.CheckConstraint("training_dataset_version ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'", name="ck_dbi_model_versions_training_dataset"),
        sa.CheckConstraint("validation_dataset_version ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'", name="ck_dbi_model_versions_validation_dataset"),
        sa.CheckConstraint("input_contract_version ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'", name="ck_dbi_model_versions_input_contract"),
        sa.CheckConstraint("output_contract_version ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'", name="ck_dbi_model_versions_output_contract"),
        sa.CheckConstraint("artifact_ref IS NULL OR artifact_ref ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'", name="ck_dbi_model_versions_artifact_ref"),
        sa.CheckConstraint("(metrics_json IS NULL AND metrics_sha256 IS NULL) OR (metrics_json IS NOT NULL AND metrics_sha256 ~ '^[0-9a-f]{64}$' AND octet_length(metrics_json) BETWEEN 2 AND 65536)", name="ck_dbi_model_versions_metrics"),
        sa.CheckConstraint("(status IN ('draft', 'validated') AND approved_at IS NULL AND approved_by_ref IS NULL AND retired_at IS NULL) OR (status = 'approved' AND approved_at IS NOT NULL AND approved_by_ref IS NOT NULL AND retired_at IS NULL) OR (status = 'retired' AND approved_at IS NOT NULL AND approved_by_ref IS NOT NULL AND retired_at IS NOT NULL)", name="ck_dbi_model_versions_lifecycle"),
    )
    op.create_index(
        "ix_dbi_model_versions_family_status",
        "dbi_model_versions",
        ["model_family", "status"],
    )

    op.create_table(
        "dbi_analysis_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("model_family", sa.String(length=64), nullable=False),
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_config_version", sa.String(length=128), nullable=False),
        sa.Column("policy_ref", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=16), server_default="challenger", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("created_by_ref", sa.String(length=128), nullable=False),
        sa.Column("retired_by_ref", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_analysis_profiles"),
        sa.ForeignKeyConstraint(
            ["model_version_id", "model_family"],
            ["dbi_model_versions.id", "dbi_model_versions.model_family"],
            name="fk_dbi_analysis_profiles_model_family",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_ref", "policy_ref", name="uq_dbi_analysis_profiles_tenant_policy"),
        sa.CheckConstraint("role IN ('champion', 'challenger')", name="ck_dbi_analysis_profiles_role"),
        sa.CheckConstraint("status IN ('active', 'retired')", name="ck_dbi_analysis_profiles_status"),
        sa.CheckConstraint("tenant_ref ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'", name="ck_dbi_analysis_profiles_tenant"),
        sa.CheckConstraint("model_family ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'", name="ck_dbi_analysis_profiles_family"),
        sa.CheckConstraint("pipeline_config_version ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'", name="ck_dbi_analysis_profiles_pipeline"),
        sa.CheckConstraint("policy_ref ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'", name="ck_dbi_analysis_profiles_policy"),
        sa.CheckConstraint("(status = 'active' AND retired_at IS NULL AND retired_by_ref IS NULL) OR (status = 'retired' AND retired_at IS NOT NULL AND retired_by_ref IS NOT NULL)", name="ck_dbi_analysis_profiles_lifecycle"),
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


def downgrade() -> None:
    """Remove registry objects without touching Jobs, Queue or assets."""

    op.drop_table("dbi_analysis_profiles")
    op.drop_table("dbi_model_versions")
