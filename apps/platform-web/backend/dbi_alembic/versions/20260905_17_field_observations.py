"""Persist immutable, versioned field observations.

Revision ID: dbi_0017_field_observations
Revises: dbi_0016_sampling_plans
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from geoalchemy2 import Geometry
import sqlalchemy as sa

revision: str = "dbi_0017_field_observations"
down_revision: str | None = "dbi_0016_sampling_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dbi_field_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("organization_ref", sa.String(length=128), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("plot_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_ref", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_field_observations"),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["dbi_farms.id"],
            name="fk_dbi_field_observations_farm",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plot_id", "farm_id"],
            ["dbi_plots.id", "dbi_plots.farm_id"],
            name="fk_dbi_field_observations_plot_farm",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "length(tenant_ref) BETWEEN 1 AND 128 "
            "AND btrim(tenant_ref) = tenant_ref "
            "AND tenant_ref NOT LIKE '%*%' "
            "AND length(organization_ref) BETWEEN 1 AND 128 "
            "AND btrim(organization_ref) = organization_ref "
            "AND organization_ref NOT LIKE '%*%' "
            "AND length(created_by_ref) BETWEEN 1 AND 128 "
            "AND btrim(created_by_ref) = created_by_ref",
            name="ck_dbi_field_observations_canonical_refs",
        ),
    )
    op.create_index(
        "ix_dbi_field_observations_tenant",
        "dbi_field_observations",
        ["tenant_ref"],
    )
    op.create_index(
        "ix_dbi_field_observations_farm_plot",
        "dbi_field_observations",
        ["farm_id", "plot_id"],
    )
    op.create_index(
        "ix_dbi_field_observations_created_at",
        "dbi_field_observations",
        ["created_at"],
    )

    op.create_table(
        "dbi_field_observation_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("observation_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("supersedes_version_id", sa.Uuid(), nullable=True),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("operator_ref", sa.String(length=128), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "gps_point",
            Geometry("POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("gps_accuracy_m", sa.Float(), nullable=True),
        sa.Column("gps_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sampling_point_id", sa.Uuid(), nullable=True),
        sa.Column("up_id", sa.Uuid(), nullable=True),
        sa.Column(
            "evidence_kind",
            sa.String(length=16),
            server_default="observed",
            nullable=False,
        ),
        sa.Column("correction_reason", sa.String(length=500), nullable=True),
        sa.Column("recorded_by_ref", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_field_observation_versions"),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["dbi_field_observations.id"],
            name="fk_dbi_field_observation_versions_observation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sampling_point_id"],
            ["dbi_sampling_points.id"],
            name="fk_dbi_field_observation_versions_sampling_point",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "observation_id",
            "version",
            name="uq_dbi_field_observation_versions_observation_version",
        ),
        sa.UniqueConstraint(
            "observation_id",
            "id",
            name="uq_dbi_field_observation_versions_observation_id",
        ),
        sa.UniqueConstraint(
            "supersedes_version_id",
            name="uq_dbi_field_observation_versions_supersedes",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_dbi_field_observation_versions_positive_version",
        ),
        sa.CheckConstraint(
            "evidence_kind = 'observed'",
            name="ck_dbi_field_observation_versions_evidence_kind",
        ),
        sa.CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_field_observation_versions_payload_sha256",
        ),
        sa.CheckConstraint(
            "octet_length(payload_json) BETWEEN 2 AND 262144",
            name="ck_dbi_field_observation_versions_payload_size",
        ),
        sa.CheckConstraint(
            "length(schema_version) BETWEEN 1 AND 64 "
            "AND btrim(schema_version) = schema_version "
            "AND length(operator_ref) BETWEEN 1 AND 128 "
            "AND btrim(operator_ref) = operator_ref "
            "AND length(recorded_by_ref) BETWEEN 1 AND 128 "
            "AND btrim(recorded_by_ref) = recorded_by_ref",
            name="ck_dbi_field_observation_versions_canonical_refs",
        ),
        sa.CheckConstraint(
            "(version = 1 AND supersedes_version_id IS NULL AND correction_reason IS NULL) OR "
            "(version > 1 AND supersedes_version_id IS NOT NULL "
            "AND correction_reason IS NOT NULL "
            "AND length(btrim(correction_reason)) BETWEEN 1 AND 500)",
            name="ck_dbi_field_observation_versions_chain",
        ),
        sa.CheckConstraint(
            "(gps_point IS NULL AND gps_accuracy_m IS NULL AND gps_captured_at IS NULL) OR "
            "(gps_point IS NOT NULL AND gps_accuracy_m IS NOT NULL "
            "AND gps_accuracy_m >= 0 AND gps_accuracy_m <= 10000 "
            "AND gps_captured_at IS NOT NULL)",
            name="ck_dbi_field_observation_versions_gps_bundle",
        ),
        sa.CheckConstraint(
            "gps_point IS NULL OR (NOT ST_IsEmpty(gps_point) AND ST_IsValid(gps_point))",
            name="ck_dbi_field_observation_versions_gps_geometry",
        ),
    )
    op.create_foreign_key(
        "fk_dbi_field_observation_versions_supersedes_same_observation",
        "dbi_field_observation_versions",
        "dbi_field_observation_versions",
        ["observation_id", "supersedes_version_id"],
        ["observation_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_dbi_field_observation_versions_observation",
        "dbi_field_observation_versions",
        ["observation_id"],
    )
    op.create_index(
        "ix_dbi_field_observation_versions_sampling_point",
        "dbi_field_observation_versions",
        ["sampling_point_id"],
    )
    op.create_index(
        "ix_dbi_field_observation_versions_up",
        "dbi_field_observation_versions",
        ["up_id"],
    )
    op.create_index(
        "ix_dbi_field_observation_versions_observed_at",
        "dbi_field_observation_versions",
        ["observed_at"],
    )
    op.create_index(
        "ix_dbi_field_observation_versions_gps_gist",
        "dbi_field_observation_versions",
        ["gps_point"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_table("dbi_field_observation_versions")
    op.drop_table("dbi_field_observations")
