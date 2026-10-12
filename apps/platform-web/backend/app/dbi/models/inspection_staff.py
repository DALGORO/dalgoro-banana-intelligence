"""Padrón INSTITUCIONAL de DALGORO, ajeno a los permisos DBI del cliente.

El rol de aplicación DBI sólo debe tener SELECT de estas tablas.
Altas y revocaciones: fuera de la API, por autoridad DALGORO confiable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint, Computed, DateTime, ForeignKey, Index,
    Integer, String, UniqueConstraint, Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.dbi_base import DBIBase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DBIInspectionInstitutionalStaffRoleRecord(DBIBase):
    """Cargo laboral global, no privilegio de un tenant/organización cliente."""

    __tablename__ = "dbi_inspect_staff_roles"
    __table_args__ = (
        UniqueConstraint(
            "principal_id", "role", name="uq_dbi_inspect_staff_principal_role",
        ),
        # Los técnicos ocupan NULL (muchos); administrador activo ocupa 1.
        # La unicidad se comprueba en PostgreSQL incluso ante carreras.
        UniqueConstraint(
            "active_administrator_slot", name="uq_dbi_inspect_one_active_admin",
        ),
        CheckConstraint(
            "role IN ('technician', 'administrator')",
            name="ck_dbi_inspect_staff_role",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_dbi_inspect_staff_status",
        ),
        CheckConstraint(
            "(status = 'active' AND revoked_by_ref IS NULL AND revoked_at IS NULL "
            "AND revocation_reason IS NULL) OR "
            "(status = 'revoked' AND revoked_by_ref IS NOT NULL "
            "AND revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)",
            name="ck_dbi_inspect_staff_revocation",
        ),
        CheckConstraint(
            "length(accredited_by_ref) BETWEEN 1 AND 128 "
            "AND btrim(accredited_by_ref) = accredited_by_ref "
            "AND accredited_by_ref NOT LIKE '%*%' "
            "AND (revoked_by_ref IS NULL OR "
            "(length(revoked_by_ref) BETWEEN 1 AND 128 "
            "AND btrim(revoked_by_ref) = revoked_by_ref "
            "AND revoked_by_ref NOT LIKE '%*%')) "
            "AND (revocation_reason IS NULL OR "
            "(length(revocation_reason) BETWEEN 1 AND 512 "
            "AND btrim(revocation_reason) = revocation_reason))",
            name="ck_dbi_inspect_staff_canonical_audit",
        ),
        Index("ix_dbi_inspect_staff_roles_principal", "principal_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    principal_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("dbi_principals.id", ondelete="RESTRICT"), nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active",
    )
    active_administrator_slot: Mapped[int | None] = mapped_column(
        Integer,
        Computed(
            "CASE WHEN role = 'administrator' AND status = 'active' "
            "THEN 1 ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )
    accredited_by_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    accredited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now,
    )
    revoked_by_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(512))


class DBIInspectionInstitutionalStaffAuditRecord(DBIBase):
    """Libro institucional auditado mediante trigger del MOTOR, append-only."""

    __tablename__ = "dbi_inspect_staff_audit_events"
    __table_args__ = (
        UniqueConstraint("role_id", "event_kind", name="uq_dbi_inspect_staff_audit_step"),
        CheckConstraint(
            "event_kind IN ('accredited', 'revoked')",
            name="ck_dbi_inspect_staff_audit_kind",
        ),
        Index("ix_dbi_inspect_staff_audit_role", "role_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    role_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("dbi_inspect_staff_roles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now,
    )
