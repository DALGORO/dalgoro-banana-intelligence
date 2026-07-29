"""Crea metadatos DBI de activos y artefactos.

Revision ID: dbi_0004_assets_artifacts
Revises: dbi_0003_analysis_jobs
Create Date: 2026-07-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0004_assets_artifacts"
down_revision: Union[str, Sequence[str], None] = "dbi_0003_analysis_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OBJECT_KEY_CHECK = (
    "object_key ~ '^[A-Za-z0-9][A-Za-z0-9._/-]{0,511}$' "
    "AND object_key !~ '(^|/)\\.{1,2}(/|$)' "
    "AND object_key NOT LIKE '%//%'"
)
CONTENT_TYPE_CHECK = (
    "content_type ~ '^[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+$'"
)
SHA256_CHECK = "sha256 ~ '^[0-9a-f]{64}$'"


def _audit_columns() -> tuple[sa.Column, sa.Column]:
    """Construye columnas temporales comunes sin extensiones."""

    return (
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
    )


def upgrade() -> None:
    """Crea únicamente metadatos de objetos, sin conectar almacenamiento."""

    op.create_unique_constraint(
        "uq_dbi_analysis_job_attempts_id_job",
        "dbi_analysis_job_attempts",
        ["id", "job_id"],
    )

    op.create_table(
        "dbi_analysis_input_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("plot_id", sa.Uuid(), nullable=True),
        sa.Column("asset_kind", sa.String(length=24), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="registered",
            nullable=False,
        ),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("crs", sa.String(length=80), nullable=True),
        sa.Column("created_by_ref", sa.String(length=128), nullable=False),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        *_audit_columns(),
        sa.CheckConstraint(
            "asset_kind IN ('orthophoto', 'boundary', 'exclusions')",
            name="ck_dbi_analysis_input_assets_kind",
        ),
        sa.CheckConstraint(
            "status IN ('registered', 'verified', 'quarantined', 'retired')",
            name="ck_dbi_analysis_input_assets_status",
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_dbi_analysis_input_assets_positive_size",
        ),
        sa.CheckConstraint(
            SHA256_CHECK,
            name="ck_dbi_analysis_input_assets_sha256",
        ),
        sa.CheckConstraint(
            CONTENT_TYPE_CHECK,
            name="ck_dbi_analysis_input_assets_content_type",
        ),
        sa.CheckConstraint(
            OBJECT_KEY_CHECK,
            name="ck_dbi_analysis_input_assets_object_key",
        ),
        sa.CheckConstraint(
            "status <> 'verified' OR verified_at IS NOT NULL",
            name="ck_dbi_analysis_input_assets_verification",
        ),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["dbi_farms.id"],
            name="fk_dbi_analysis_input_assets_farm_id_dbi_farms",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plot_id"],
            ["dbi_plots.id"],
            name="fk_dbi_analysis_input_assets_plot_id_dbi_plots",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_dbi_analysis_input_assets",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "object_key",
            name="uq_dbi_analysis_input_assets_tenant_object",
        ),
    )
    op.create_index(
        "ix_dbi_analysis_input_assets_tenant_ref",
        "dbi_analysis_input_assets",
        ["tenant_ref"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_analysis_input_assets_farm_id",
        "dbi_analysis_input_assets",
        ["farm_id"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_analysis_input_assets_status",
        "dbi_analysis_input_assets",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_analysis_input_assets_sha256",
        "dbi_analysis_input_assets",
        ["sha256"],
        unique=False,
    )

    op.create_table(
        "dbi_analysis_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column(
            "manifest_schema_version",
            sa.String(length=64),
            server_default="artifact-manifest.v1",
            nullable=False,
        ),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "produced_by_stage",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("crs", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "manifest_schema_version = 'artifact-manifest.v1'",
            name="ck_dbi_analysis_artifacts_schema_version",
        ),
        sa.CheckConstraint(
            "role IN ("
            "'validated_inventory', 'analysis_boundary', 'hex_density', "
            "'planting_priority', 'kde_density', 'cartographic_package', "
            "'technical_report', 'pipeline_state', 'pipeline_manifest'"
            ")",
            name="ck_dbi_analysis_artifacts_role",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_dbi_analysis_artifacts_positive_size",
        ),
        sa.CheckConstraint(
            SHA256_CHECK,
            name="ck_dbi_analysis_artifacts_sha256",
        ),
        sa.CheckConstraint(
            CONTENT_TYPE_CHECK,
            name="ck_dbi_analysis_artifacts_content_type",
        ),
        sa.CheckConstraint(
            OBJECT_KEY_CHECK,
            name="ck_dbi_analysis_artifacts_object_key",
        ),
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_dbi_analysis_artifacts",
        ),
        sa.UniqueConstraint(
            "object_key",
            name="uq_dbi_analysis_artifacts_object_key",
        ),
    )
    op.create_index(
        "ix_dbi_analysis_artifacts_job_id",
        "dbi_analysis_artifacts",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_analysis_artifacts_attempt_id",
        "dbi_analysis_artifacts",
        ["attempt_id"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_analysis_artifacts_role",
        "dbi_analysis_artifacts",
        ["role"],
        unique=False,
    )
    op.create_index(
        "ix_dbi_analysis_artifacts_sha256",
        "dbi_analysis_artifacts",
        ["sha256"],
        unique=False,
    )


def downgrade() -> None:
    """Revierte artefactos, activos y la integridad compuesta."""

    op.drop_table("dbi_analysis_artifacts")
    op.drop_table("dbi_analysis_input_assets")
    op.drop_constraint(
        "uq_dbi_analysis_job_attempts_id_job",
        "dbi_analysis_job_attempts",
        type_="unique",
    )
