"""Persist versioned flight-source bundles and exact source snapshots.

Revision ID: dbi_0011_flight_manifest
Revises: dbi_0010_asset_multipart
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "dbi_0011_flight_manifest"
down_revision: str | None = "dbi_0010_asset_multipart"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable, tenant-safe manifests without moving binaries."""

    op.drop_constraint(
        "ck_dbi_analysis_input_assets_kind",
        "dbi_analysis_input_assets",
        type_="check",
    )
    op.create_check_constraint(
        "ck_dbi_analysis_input_assets_kind",
        "dbi_analysis_input_assets",
        "asset_kind IN ("
        "'orthophoto', 'boundary', 'exclusions', "
        "'flight_photo', 'flight_auxiliary'"
        ")",
    )

    op.create_table(
        "dbi_flight_source_bundles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("plot_id", sa.Uuid(), nullable=True),
        sa.Column("flight_ref", sa.String(length=128), nullable=False),
        sa.Column("master_asset_id", sa.Uuid(), nullable=False),
        sa.Column(
            "schema_version",
            sa.String(length=64),
            server_default="flight-source-bundle.v1",
            nullable=False,
        ),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("total_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_by_ref", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "schema_version = 'flight-source-bundle.v1'",
            name="ck_dbi_flight_source_bundles_schema",
        ),
        sa.CheckConstraint(
            "length(flight_ref) BETWEEN 1 AND 128 "
            "AND btrim(flight_ref) = flight_ref",
            name="ck_dbi_flight_source_bundles_flight_ref",
        ),
        sa.CheckConstraint(
            "manifest_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_flight_source_bundles_sha256",
        ),
        sa.CheckConstraint(
            "entry_count BETWEEN 1 AND 10000",
            name="ck_dbi_flight_source_bundles_entry_count",
        ),
        sa.CheckConstraint(
            "total_size_bytes > 0",
            name="ck_dbi_flight_source_bundles_total_size",
        ),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["dbi_farms.id"],
            name="fk_dbi_flight_source_bundles_farm_id_dbi_farms",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plot_id", "farm_id"],
            ["dbi_plots.id", "dbi_plots.farm_id"],
            name="fk_dbi_flight_source_bundles_plot_farm",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["master_asset_id", "tenant_ref"],
            [
                "dbi_analysis_input_assets.id",
                "dbi_analysis_input_assets.tenant_ref",
            ],
            name="fk_dbi_flight_source_bundles_master_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_dbi_flight_source_bundles",
        ),
        sa.UniqueConstraint(
            "id",
            "tenant_ref",
            name="uq_dbi_flight_source_bundles_id_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "farm_id",
            "flight_ref",
            name="uq_dbi_flight_source_bundles_flight",
        ),
    )
    op.create_index(
        "ix_dbi_flight_source_bundles_tenant",
        "dbi_flight_source_bundles",
        ["tenant_ref"],
    )
    op.create_index(
        "ix_dbi_flight_source_bundles_farm",
        "dbi_flight_source_bundles",
        ["farm_id"],
    )
    op.create_index(
        "ix_dbi_flight_source_bundles_master",
        "dbi_flight_source_bundles",
        ["master_asset_id"],
    )

    op.create_table(
        "dbi_flight_source_entries",
        sa.Column("bundle_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("logical_name", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("sensor_camera", sa.String(length=160), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "ordinal BETWEEN 1 AND 10000",
            name="ck_dbi_flight_source_entries_ordinal",
        ),
        sa.CheckConstraint(
            "role IN ('source_photo', 'auxiliary')",
            name="ck_dbi_flight_source_entries_role",
        ),
        sa.CheckConstraint(
            "length(logical_name) BETWEEN 1 AND 512 "
            "AND btrim(logical_name) = logical_name "
            "AND logical_name !~ '(^|/)\\.{1,2}(/|$)' "
            "AND logical_name NOT LIKE '/%' "
            "AND logical_name NOT LIKE '%//%'",
            name="ck_dbi_flight_source_entries_logical_name",
        ),
        sa.CheckConstraint(
            "content_type ~ '^[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+$'",
            name="ck_dbi_flight_source_entries_content_type",
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_dbi_flight_source_entries_positive_size",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_flight_source_entries_sha256",
        ),
        sa.CheckConstraint(
            "sensor_camera IS NULL OR (length(sensor_camera) BETWEEN 1 AND 160 "
            "AND btrim(sensor_camera) = sensor_camera)",
            name="ck_dbi_flight_source_entries_sensor",
        ),
        sa.ForeignKeyConstraint(
            ["bundle_id", "tenant_ref"],
            [
                "dbi_flight_source_bundles.id",
                "dbi_flight_source_bundles.tenant_ref",
            ],
            name="fk_dbi_flight_source_entries_bundle_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "tenant_ref"],
            [
                "dbi_analysis_input_assets.id",
                "dbi_analysis_input_assets.tenant_ref",
            ],
            name="fk_dbi_flight_source_entries_asset_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "bundle_id",
            "asset_id",
            name="pk_dbi_flight_source_entries",
        ),
        sa.UniqueConstraint(
            "bundle_id",
            "logical_name",
            name="uq_dbi_flight_source_entries_logical_name",
        ),
        sa.UniqueConstraint(
            "bundle_id",
            "ordinal",
            name="uq_dbi_flight_source_entries_ordinal",
        ),
    )
    op.create_index(
        "ix_dbi_flight_source_entries_tenant",
        "dbi_flight_source_entries",
        ["tenant_ref"],
    )
    op.create_index(
        "ix_dbi_flight_source_entries_asset",
        "dbi_flight_source_entries",
        ["asset_id"],
    )
    op.create_index(
        "ix_dbi_flight_source_entries_capture",
        "dbi_flight_source_entries",
        ["captured_at"],
    )


def downgrade() -> None:
    """Remove manifests and restore the previous asset-kind contract."""

    op.drop_table("dbi_flight_source_entries")
    op.drop_table("dbi_flight_source_bundles")
    op.drop_constraint(
        "ck_dbi_analysis_input_assets_kind",
        "dbi_analysis_input_assets",
        type_="check",
    )
    op.create_check_constraint(
        "ck_dbi_analysis_input_assets_kind",
        "dbi_analysis_input_assets",
        "asset_kind IN ('orthophoto', 'boundary', 'exclusions')",
    )

