"""Persist auditable private COG/BigTIFF products.

Revision ID: dbi_0015_raster_products
Revises: dbi_0014_analysis_results
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0015_raster_products"
down_revision: str | None = "dbi_0014_analysis_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SHA_CHECK = "^[0-9a-f]{64}$"
_OBJECT_KEY_CHECK = (
    "object_key ~ '^[A-Za-z0-9][A-Za-z0-9._/-]*$' "
    "AND object_key !~ '(^|/)\\.\\.?(/|$)' "
    "AND object_key NOT LIKE '%//%' "
    "AND object_key NOT LIKE '/%' "
    "AND object_key NOT LIKE '%\\\\%' "
    "AND length(object_key) BETWEEN 1 AND 512"
)


def upgrade() -> None:
    op.create_table(
        "dbi_raster_products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=128), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("plot_id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("product_kind", sa.String(length=32), nullable=False),
        sa.Column("profile_version", sa.String(length=128), nullable=False),
        sa.Column("generator_version", sa.String(length=128), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("crs", sa.String(length=80), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("band_count", sa.Integer(), nullable=False),
        sa.Column("dtype", sa.String(length=64), nullable=False),
        sa.Column("transform_json", sa.Text(), nullable=False),
        sa.Column("bounds_json", sa.Text(), nullable=False),
        sa.Column("nodata_json", sa.Text(), nullable=False),
        sa.Column("scales_json", sa.Text(), nullable=False),
        sa.Column("offsets_json", sa.Text(), nullable=False),
        sa.Column("block_width", sa.Integer(), nullable=False),
        sa.Column("block_height", sa.Integer(), nullable=False),
        sa.Column("compression", sa.String(length=32), nullable=False),
        sa.Column("overview_levels_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="ready", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_raster_products"),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["dbi_farms.id"],
            name="fk_dbi_raster_products_farm",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plot_id", "farm_id"],
            ["dbi_plots.id", "dbi_plots.farm_id"],
            name="fk_dbi_raster_products_plot_farm",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_ref", "source_kind", "source_ref", "source_sha256",
            "product_kind", "profile_version",
            name="uq_dbi_raster_products_source_profile",
        ),
        sa.UniqueConstraint("object_key", name="uq_dbi_raster_products_object_key"),
        sa.CheckConstraint(
            "source_kind IN ('input_asset', 'analysis_artifact')",
            name="ck_dbi_raster_products_source_kind",
        ),
        sa.CheckConstraint(
            "product_kind IN ('rgb_visual', 'scientific')",
            name="ck_dbi_raster_products_product_kind",
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'retired')",
            name="ck_dbi_raster_products_status",
        ),
        sa.CheckConstraint(
            f"source_sha256 ~ '{_SHA_CHECK}' AND sha256 ~ '{_SHA_CHECK}'",
            name="ck_dbi_raster_products_sha256",
        ),
        sa.CheckConstraint(
            "content_type = 'image/tiff'",
            name="ck_dbi_raster_products_content_type",
        ),
        sa.CheckConstraint(
            _OBJECT_KEY_CHECK,
            name="ck_dbi_raster_products_object_key",
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND width > 0 AND height > 0 AND band_count > 0",
            name="ck_dbi_raster_products_positive_shape",
        ),
        sa.CheckConstraint(
            "block_width BETWEEN 64 AND 4096 AND block_height BETWEEN 64 AND 4096",
            name="ck_dbi_raster_products_block_shape",
        ),
        sa.CheckConstraint(
            "length(profile_version) BETWEEN 1 AND 128 "
            "AND btrim(profile_version) = profile_version "
            "AND length(generator_version) BETWEEN 1 AND 128 "
            "AND btrim(generator_version) = generator_version",
            name="ck_dbi_raster_products_versions",
        ),
        sa.CheckConstraint(
            "octet_length(transform_json) BETWEEN 2 AND 4096 "
            "AND octet_length(bounds_json) BETWEEN 2 AND 4096 "
            "AND octet_length(nodata_json) BETWEEN 2 AND 4096 "
            "AND octet_length(scales_json) BETWEEN 2 AND 4096 "
            "AND octet_length(offsets_json) BETWEEN 2 AND 4096 "
            "AND octet_length(overview_levels_json) BETWEEN 2 AND 4096",
            name="ck_dbi_raster_products_metadata_size",
        ),
        sa.CheckConstraint(
            "(status = 'ready' AND retired_at IS NULL) OR "
            "(status = 'retired' AND retired_at IS NOT NULL AND retired_at >= created_at)",
            name="ck_dbi_raster_products_retirement",
        ),
    )
    op.create_index("ix_dbi_raster_products_tenant", "dbi_raster_products", ["tenant_ref"])
    op.create_index("ix_dbi_raster_products_farm_plot", "dbi_raster_products", ["farm_id", "plot_id"])
    op.create_index("ix_dbi_raster_products_source", "dbi_raster_products", ["source_kind", "source_ref"])
    op.create_index("ix_dbi_raster_products_status", "dbi_raster_products", ["status"])


def downgrade() -> None:
    op.drop_table("dbi_raster_products")
