"""H14/2H-2D/1: ticket SQL, NO inicio multipart.

Revision ID: dbi_0032_raster_session_prep
Revises: dbi_0031_raster_asset

Revisión solo en CI PostgreSQL efímero; NO aplicar a Render/producción.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "dbi_0032_raster_session_prep"
down_revision: str | None = "dbi_0031_raster_asset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dbi_scientific_raster_session_preparations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_ref", sa.String(128), nullable=False),
        sa.Column("organization_ref", sa.String(128), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("plot_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("reservation_sha256", sa.String(64), nullable=False),
        sa.Column("declared_sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("part_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("part_count", sa.Integer(), nullable=False),
        sa.Column("max_grants_per_window", sa.Integer(), nullable=False),
        sa.Column("max_client_concurrency", sa.Integer(), nullable=False),
        sa.Column("checksum_algorithm", sa.String(12), nullable=False),
        sa.Column("checksum_type", sa.String(12), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by_ref", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_dbi_scientific_raster_session_preparations"),
        sa.ForeignKeyConstraint(
            ["asset_id", "binding_id"],
            ["dbi_scientific_raster_input_assets.id",
             "dbi_scientific_raster_input_assets.binding_id"],
            name="fk_dbi_scientific_raster_preparation_asset_binding",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "asset_id", name="uq_dbi_scientific_raster_preparation_asset",
        ),
        sa.UniqueConstraint(
            "tenant_ref", "idempotency_key_hash",
            name="uq_dbi_scientific_raster_preparation_key",
        ),
        sa.CheckConstraint(
            "status IN ('prepared_no_provider','cancelled_no_provider') "
            "AND ((status='cancelled_no_provider') = (cancelled_at IS NOT NULL))",
            name="ck_dbi_scientific_raster_preparation_state",
        ),
        sa.CheckConstraint(
            "size_bytes > 67108864 AND size_bytes <= 10737418240 "
            "AND part_size_bytes = 67108864 AND part_count BETWEEN 2 AND 10000 "
            "AND max_grants_per_window = 8 AND max_client_concurrency = 4",
            name="ck_dbi_scientific_raster_preparation_plan",
        ),
        sa.CheckConstraint(
            "checksum_algorithm = 'SHA256' AND checksum_type = 'COMPOSITE'",
            name="ck_dbi_scientific_raster_preparation_checksum",
        ),
        sa.CheckConstraint(
            "manifest_sha256 ~ '^[0-9a-f]{64}$' AND "
            "reservation_sha256 ~ '^[0-9a-f]{64}$' AND "
            "declared_sha256 ~ '^[0-9a-f]{64}$' AND "
            "idempotency_key_hash ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_scientific_raster_preparation_hashes",
        ),
        sa.CheckConstraint(
            "expires_at > created_at AND updated_at >= created_at "
            "AND (cancelled_at IS NULL OR cancelled_at >= created_at)",
            name="ck_dbi_scientific_raster_preparation_times",
        ),
    )
    op.create_index(
        "ix_dbi_scientific_raster_preparation_scope",
        "dbi_scientific_raster_session_preparations",
        ["tenant_ref", "organization_ref", "farm_id", "plot_id", "campaign_id"],
    )
    op.create_index(
        "ix_dbi_scientific_raster_preparation_expiry",
        "dbi_scientific_raster_session_preparations",
        ["status", "expires_at"],
    )


def downgrade() -> None:
    # Nunca eliminar tickets de auditoría salvo procedimiento institucional.
    op.execute(sa.text(
        "DO $$ BEGIN IF EXISTS "
        "(SELECT 1 FROM dbi_scientific_raster_session_preparations) THEN "
        "RAISE EXCEPTION 'DBI session preparations exist; downgrade forbidden'; "
        "END IF; END $$"
    ))
    op.drop_index(
        "ix_dbi_scientific_raster_preparation_expiry",
        table_name="dbi_scientific_raster_session_preparations",
    )
    op.drop_index(
        "ix_dbi_scientific_raster_preparation_scope",
        table_name="dbi_scientific_raster_session_preparations",
    )
    op.drop_table("dbi_scientific_raster_session_preparations")
