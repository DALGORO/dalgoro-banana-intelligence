"""Persist immutable multispectral extractions linked to INSPECT truth-ground.

Revision ID: dbi_0018_multispectral_extractions
Revises: dbi_0017_field_observations
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0018_multispectral_extractions"
down_revision: str | None = "dbi_0017_field_observations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dbi_multispectral_extractions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("organization_ref", sa.String(length=128), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("plot_id", sa.Uuid(), nullable=False),
        sa.Column("observation_id", sa.Uuid(), nullable=False),
        sa.Column("observation_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_raster_product_id", sa.Uuid(), nullable=False),
        sa.Column("sampling_point_id", sa.Uuid(), nullable=True),
        sa.Column("up_id", sa.Uuid(), nullable=True),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("support_mode", sa.String(length=16), nullable=False),
        sa.Column("support_profile_version", sa.String(length=128), nullable=False),
        sa.Column("support_limitation", sa.String(length=500), nullable=True),
        sa.Column("stack_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False),
        sa.Column(
            "evidence_kind",
            sa.String(length=16),
            server_default="derived",
            nullable=False,
        ),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_multispectral_extractions"),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["dbi_farms.id"],
            name="fk_dbi_multispectral_extractions_farm",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plot_id", "farm_id"],
            ["dbi_plots.id", "dbi_plots.farm_id"],
            name="fk_dbi_multispectral_extractions_plot_farm",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "observation_version_id"],
            [
                "dbi_field_observation_versions.observation_id",
                "dbi_field_observation_versions.id",
            ],
            name="fk_dbi_multispectral_extractions_observation_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_raster_product_id"],
            ["dbi_raster_products.id"],
            name="fk_dbi_multispectral_extractions_source_raster",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sampling_point_id"],
            ["dbi_sampling_points.id"],
            name="fk_dbi_multispectral_extractions_sampling_point",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "observation_version_id",
            "source_raster_product_id",
            "support_mode",
            "support_profile_version",
            "stack_fingerprint",
            name="uq_dbi_multispectral_extractions_source_support",
        ),
        sa.CheckConstraint(
            "schema_version = 'dbi-multispectral-extraction.v1'",
            name="ck_dbi_multispectral_extractions_schema_version",
        ),
        sa.CheckConstraint(
            "evidence_kind = 'derived'",
            name="ck_dbi_multispectral_extractions_evidence_kind",
        ),
        sa.CheckConstraint(
            "support_mode IN ('copa_up', 'window')",
            name="ck_dbi_multispectral_extractions_support_mode",
        ),
        sa.CheckConstraint(
            "(support_mode = 'copa_up' AND up_id IS NOT NULL "
            "AND support_limitation IS NULL) OR "
            "(support_mode = 'window' AND support_limitation IS NOT NULL "
            "AND length(btrim(support_limitation)) BETWEEN 1 AND 500)",
            name="ck_dbi_multispectral_extractions_support_semantics",
        ),
        sa.CheckConstraint(
            "selected_count > 0",
            name="ck_dbi_multispectral_extractions_selected_count",
        ),
        sa.CheckConstraint(
            "stack_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_multispectral_extractions_sha256",
        ),
        sa.CheckConstraint(
            "octet_length(payload_json) BETWEEN 2 AND 262144",
            name="ck_dbi_multispectral_extractions_payload_size",
        ),
        sa.CheckConstraint(
            "length(tenant_ref) BETWEEN 1 AND 128 "
            "AND btrim(tenant_ref) = tenant_ref "
            "AND tenant_ref NOT LIKE '%*%' "
            "AND length(organization_ref) BETWEEN 1 AND 128 "
            "AND btrim(organization_ref) = organization_ref "
            "AND organization_ref NOT LIKE '%*%' "
            "AND length(support_profile_version) BETWEEN 1 AND 128 "
            "AND btrim(support_profile_version) = support_profile_version",
            name="ck_dbi_multispectral_extractions_canonical_refs",
        ),
    )
    op.create_index(
        "ix_dbi_multispectral_extractions_tenant",
        "dbi_multispectral_extractions",
        ["tenant_ref"],
    )
    op.create_index(
        "ix_dbi_multispectral_extractions_farm_plot",
        "dbi_multispectral_extractions",
        ["farm_id", "plot_id"],
    )
    op.create_index(
        "ix_dbi_multispectral_extractions_observation_version",
        "dbi_multispectral_extractions",
        ["observation_version_id"],
    )
    op.create_index(
        "ix_dbi_multispectral_extractions_source_raster",
        "dbi_multispectral_extractions",
        ["source_raster_product_id"],
    )
    op.create_index(
        "ix_dbi_multispectral_extractions_sampling_point",
        "dbi_multispectral_extractions",
        ["sampling_point_id"],
    )
    op.create_index(
        "ix_dbi_multispectral_extractions_up",
        "dbi_multispectral_extractions",
        ["up_id"],
    )
    op.create_index(
        "ix_dbi_multispectral_extractions_created_at",
        "dbi_multispectral_extractions",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("dbi_multispectral_extractions")
