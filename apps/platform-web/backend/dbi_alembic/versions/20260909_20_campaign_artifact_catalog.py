"""Add versioned technical artifact catalog scoped by Campaign.

Revision ID: dbi_0020_campaign_artifacts
Revises: dbi_0019_campaign_domain
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0020_campaign_artifacts"
down_revision: str | None = "dbi_0019_campaign_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ARTIFACT_TYPES = (
    "'orthophoto_source', 'boundary', 'validated_inventory', "
    "'density_hexagons', 'planting_candidates', 'operational_priority', "
    "'kde', 'exclusions', 'technical_report', 'sampling_plan', "
    "'sampling_points', 'field_observations'"
)


def upgrade() -> None:
    """Create metadata-only catalog; source bytes remain in their canonical stores."""

    op.create_table(
        "dbi_campaign_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "technical_status",
            sa.String(length=16),
            server_default="current",
            nullable=False,
        ),
        sa.Column(
            "published",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("source_revision_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_campaign_artifacts"),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["dbi_campaigns.id"],
            name="fk_dbi_campaign_artifacts_campaign",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "campaign_id",
            "artifact_type",
            "version",
            name="uq_dbi_campaign_artifacts_type_version",
        ),
        sa.UniqueConstraint(
            "campaign_id",
            "artifact_type",
            "source_kind",
            "source_ref",
            name="uq_dbi_campaign_artifacts_source",
        ),
        sa.CheckConstraint(
            f"artifact_type IN ({_ARTIFACT_TYPES})",
            name="ck_dbi_campaign_artifacts_type",
        ),
        sa.CheckConstraint(
            "source_kind IN ('input_asset', 'analysis_artifact', 'domain_record')",
            name="ck_dbi_campaign_artifacts_source_kind",
        ),
        sa.CheckConstraint(
            "technical_status IN ('current', 'superseded')",
            name="ck_dbi_campaign_artifacts_technical_status",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_dbi_campaign_artifacts_positive_version",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_campaign_artifacts_sha256",
        ),
    )
    op.create_index(
        "ix_dbi_campaign_artifacts_campaign",
        "dbi_campaign_artifacts",
        ["campaign_id"],
    )
    op.create_index(
        "ix_dbi_campaign_artifacts_type",
        "dbi_campaign_artifacts",
        ["artifact_type"],
    )
    op.create_index(
        "ix_dbi_campaign_artifacts_source_ref",
        "dbi_campaign_artifacts",
        ["source_kind", "source_ref"],
    )
    op.create_index(
        "ix_dbi_campaign_artifacts_published",
        "dbi_campaign_artifacts",
        ["published"],
    )
    op.create_index(
        "uq_dbi_campaign_artifacts_current_type",
        "dbi_campaign_artifacts",
        ["campaign_id", "artifact_type"],
        unique=True,
        postgresql_where=sa.text("technical_status = 'current'"),
    )


def downgrade() -> None:
    op.drop_table("dbi_campaign_artifacts")
