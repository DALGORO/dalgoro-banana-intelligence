"""Persistencia inmutable y versionada de observaciones de campo DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.dbi_base import DBIBase
from app.dbi.spatial import DBI_SPATIAL_SRID


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DBIFieldObservationRecord(DBIBase):
    """Identidad estable de una observación; sus versiones son append-only."""

    __tablename__ = "dbi_field_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plot_id", "farm_id"],
            ["dbi_plots.id", "dbi_plots.farm_id"],
            name="fk_dbi_field_observations_plot_farm",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
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
        Index("ix_dbi_field_observations_tenant", "tenant_ref"),
        Index("ix_dbi_field_observations_farm_plot", "farm_id", "plot_id"),
        Index("ix_dbi_field_observations_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_farms.id", ondelete="RESTRICT"),
        nullable=False,
    )
    plot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    created_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    versions: Mapped[list["DBIFieldObservationVersionRecord"]] = relationship(
        back_populates="observation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="DBIFieldObservationVersionRecord.observation_id",
    )


class DBIFieldObservationVersionRecord(DBIBase):
    """Snapshot observado inmutable; una corrección agrega otra fila."""

    __tablename__ = "dbi_field_observation_versions"
    __table_args__ = (
        UniqueConstraint(
            "observation_id",
            "version",
            name="uq_dbi_field_observation_versions_observation_version",
        ),
        UniqueConstraint(
            "observation_id",
            "id",
            name="uq_dbi_field_observation_versions_observation_id",
        ),
        UniqueConstraint(
            "supersedes_version_id",
            name="uq_dbi_field_observation_versions_supersedes",
        ),
        ForeignKeyConstraint(
            ["observation_id", "supersedes_version_id"],
            [
                "dbi_field_observation_versions.observation_id",
                "dbi_field_observation_versions.id",
            ],
            name="fk_dbi_field_observation_versions_supersedes_same_observation",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "version > 0",
            name="ck_dbi_field_observation_versions_positive_version",
        ),
        CheckConstraint(
            "evidence_kind = 'observed'",
            name="ck_dbi_field_observation_versions_evidence_kind",
        ),
        CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dbi_field_observation_versions_payload_sha256",
        ),
        CheckConstraint(
            "octet_length(payload_json) BETWEEN 2 AND 262144",
            name="ck_dbi_field_observation_versions_payload_size",
        ),
        CheckConstraint(
            "length(schema_version) BETWEEN 1 AND 64 "
            "AND btrim(schema_version) = schema_version "
            "AND length(operator_ref) BETWEEN 1 AND 128 "
            "AND btrim(operator_ref) = operator_ref "
            "AND length(recorded_by_ref) BETWEEN 1 AND 128 "
            "AND btrim(recorded_by_ref) = recorded_by_ref",
            name="ck_dbi_field_observation_versions_canonical_refs",
        ),
        CheckConstraint(
            "(version = 1 AND supersedes_version_id IS NULL AND correction_reason IS NULL) OR "
            "(version > 1 AND supersedes_version_id IS NOT NULL "
            "AND correction_reason IS NOT NULL "
            "AND length(btrim(correction_reason)) BETWEEN 1 AND 500)",
            name="ck_dbi_field_observation_versions_chain",
        ),
        CheckConstraint(
            "(gps_point IS NULL AND gps_accuracy_m IS NULL AND gps_captured_at IS NULL) OR "
            "(gps_point IS NOT NULL AND gps_accuracy_m IS NOT NULL "
            "AND gps_accuracy_m >= 0 AND gps_accuracy_m <= 10000 "
            "AND gps_captured_at IS NOT NULL)",
            name="ck_dbi_field_observation_versions_gps_bundle",
        ),
        CheckConstraint(
            "gps_point IS NULL OR (NOT ST_IsEmpty(gps_point) AND ST_IsValid(gps_point))",
            name="ck_dbi_field_observation_versions_gps_geometry",
        ),
        Index("ix_dbi_field_observation_versions_observation", "observation_id"),
        Index("ix_dbi_field_observation_versions_sampling_point", "sampling_point_id"),
        Index("ix_dbi_field_observation_versions_up", "up_id"),
        Index("ix_dbi_field_observation_versions_observed_at", "observed_at"),
        Index(
            "ix_dbi_field_observation_versions_gps_gist",
            "gps_point",
            postgresql_using="gist",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    observation_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_field_observations.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_version_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    operator_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gps_point: Mapped[WKBElement | None] = mapped_column(
        Geometry("POINT", srid=DBI_SPATIAL_SRID, spatial_index=False),
        nullable=True,
    )
    gps_accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sampling_point_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("dbi_sampling_points.id", ondelete="RESTRICT"),
        nullable=True,
    )
    up_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    evidence_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="observed")
    correction_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recorded_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    observation: Mapped[DBIFieldObservationRecord] = relationship(
        back_populates="versions",
        foreign_keys=[observation_id],
    )
