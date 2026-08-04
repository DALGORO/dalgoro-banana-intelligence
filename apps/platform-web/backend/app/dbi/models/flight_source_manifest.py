"""Manifiestos inmutables de fotografías y auxiliares de un vuelo DBI."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid import UUID, uuid4

from app.db.dbi_base import DBIBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FlightSourceBundle(DBIBase):
    """Cabecera estable de un manifiesto ``flight-source-bundle.v1``."""

    __tablename__ = "dbi_flight_source_bundles"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "tenant_ref",
            name="uq_dbi_flight_source_bundles_id_tenant",
        ),
        UniqueConstraint(
            "tenant_ref",
            "farm_id",
            "flight_ref",
            name="uq_dbi_flight_source_bundles_flight",
        ),
        ForeignKeyConstraint(
            ["plot_id", "farm_id"],
            ["dbi_plots.id", "dbi_plots.farm_id"],
            name="fk_dbi_flight_source_bundles_plot_farm",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["master_asset_id", "tenant_ref"],
            [
                "dbi_analysis_input_assets.id",
                "dbi_analysis_input_assets.tenant_ref",
            ],
            name="fk_dbi_flight_source_bundles_master_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "schema_version = 'flight-source-bundle.v1'",
            name="ck_dbi_flight_source_bundles_schema",
        ),
        CheckConstraint(
            "length(flight_ref) BETWEEN 1 AND 128 "
            "AND btrim(flight_ref) = flight_ref",
            name="ck_dbi_flight_source_bundles_flight_ref",
        ),
        CheckConstraint(
            "manifest_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_flight_source_bundles_sha256",
        ),
        CheckConstraint(
            "entry_count BETWEEN 1 AND 10000",
            name="ck_dbi_flight_source_bundles_entry_count",
        ),
        CheckConstraint(
            "total_size_bytes > 0",
            name="ck_dbi_flight_source_bundles_total_size",
        ),
        Index("ix_dbi_flight_source_bundles_tenant", "tenant_ref"),
        Index("ix_dbi_flight_source_bundles_farm", "farm_id"),
        Index("ix_dbi_flight_source_bundles_master", "master_asset_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_farms.id", ondelete="RESTRICT"),
        nullable=False,
    )
    plot_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    flight_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    master_asset_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="flight-source-bundle.v1",
    )
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    entries: Mapped[list["FlightSourceEntry"]] = relationship(
        back_populates="bundle",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="FlightSourceEntry.ordinal",
    )


class FlightSourceEntry(DBIBase):
    """Instantánea verificable de un objeto fuente individual del vuelo."""

    __tablename__ = "dbi_flight_source_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["bundle_id", "tenant_ref"],
            [
                "dbi_flight_source_bundles.id",
                "dbi_flight_source_bundles.tenant_ref",
            ],
            name="fk_dbi_flight_source_entries_bundle_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["asset_id", "tenant_ref"],
            [
                "dbi_analysis_input_assets.id",
                "dbi_analysis_input_assets.tenant_ref",
            ],
            name="fk_dbi_flight_source_entries_asset_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "bundle_id",
            "logical_name",
            name="uq_dbi_flight_source_entries_logical_name",
        ),
        UniqueConstraint(
            "bundle_id",
            "ordinal",
            name="uq_dbi_flight_source_entries_ordinal",
        ),
        CheckConstraint(
            "ordinal BETWEEN 1 AND 10000",
            name="ck_dbi_flight_source_entries_ordinal",
        ),
        CheckConstraint(
            "role IN ('source_photo', 'auxiliary')",
            name="ck_dbi_flight_source_entries_role",
        ),
        CheckConstraint(
            "length(logical_name) BETWEEN 1 AND 512 "
            "AND btrim(logical_name) = logical_name "
            "AND logical_name !~ '(^|/)\\.{1,2}(/|$)' "
            "AND logical_name NOT LIKE '/%' "
            "AND logical_name NOT LIKE '%//%'",
            name="ck_dbi_flight_source_entries_logical_name",
        ),
        CheckConstraint(
            "content_type ~ '^[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+$'",
            name="ck_dbi_flight_source_entries_content_type",
        ),
        CheckConstraint(
            "size_bytes > 0",
            name="ck_dbi_flight_source_entries_positive_size",
        ),
        CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_flight_source_entries_sha256",
        ),
        CheckConstraint(
            "sensor_camera IS NULL OR (length(sensor_camera) BETWEEN 1 AND 160 "
            "AND btrim(sensor_camera) = sensor_camera)",
            name="ck_dbi_flight_source_entries_sensor",
        ),
        Index("ix_dbi_flight_source_entries_tenant", "tenant_ref"),
        Index("ix_dbi_flight_source_entries_asset", "asset_id"),
        Index("ix_dbi_flight_source_entries_capture", "captured_at"),
    )

    bundle_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    asset_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    logical_name: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sensor_camera: Mapped[str | None] = mapped_column(String(160), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    bundle: Mapped[FlightSourceBundle] = relationship(back_populates="entries")
