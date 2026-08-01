"""Evidencia administrativa DBI mínima, no sensible y append-only."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.dbi_base import DBIBase


class DBIAdminAuditAction(StrEnum):
    """Operaciones administrativas persistibles como evidencia exitosa."""

    PRINCIPAL_REGISTERED = "principal_registered"
    MEMBERSHIP_CREATED = "membership_created"
    MEMBERSHIP_ACTIVATED = "membership_activated"
    MEMBERSHIP_INACTIVATED = "membership_inactivated"
    MEMBERSHIP_REVOKED = "membership_revoked"
    MEMBERSHIP_PERMISSIONS_REPLACED = "membership_permissions_replaced"
    MEMBERSHIP_SCOPES_REPLACED = "membership_scopes_replaced"


class DBIAdminAuditResourceType(StrEnum):
    """Tipos de recursos administrativos admitidos."""

    PRINCIPAL = "principal"
    MEMBERSHIP = "membership"


class DBIAdminAuditOutcome(StrEnum):
    """Resultado persistible dentro de la misma transacción de dominio."""

    SUCCEEDED = "succeeded"


DBI_ADMIN_AUDIT_ACTION_VALUES = tuple(
    action.value for action in DBIAdminAuditAction
)
DBI_ADMIN_AUDIT_RESOURCE_VALUES = tuple(
    resource.value for resource in DBIAdminAuditResourceType
)


def utc_now() -> datetime:
    """Devuelve una fecha consciente de zona horaria en UTC."""

    return datetime.now(timezone.utc)


class DBIAdminAuditEvent(DBIBase):
    """Evento exitoso por organización, sin payload o descripción libre."""

    __tablename__ = "dbi_admin_audit_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ("
            "'principal_registered', 'membership_created', "
            "'membership_activated', 'membership_inactivated', "
            "'membership_revoked', 'membership_permissions_replaced', "
            "'membership_scopes_replaced'"
            ")",
            name="ck_dbi_admin_audit_action",
        ),
        CheckConstraint(
            "resource_type IN ('principal', 'membership')",
            name="ck_dbi_admin_audit_resource_type",
        ),
        CheckConstraint(
            "outcome = 'succeeded'",
            name="ck_dbi_admin_audit_outcome",
        ),
        CheckConstraint(
            "tenant_ref = btrim(tenant_ref) "
            "AND length(tenant_ref) > 0 "
            "AND position('*' in tenant_ref) = 0 "
            "AND lower(tenant_ref) NOT IN ('all', 'any')",
            name="ck_dbi_admin_audit_tenant_ref",
        ),
        CheckConstraint(
            "organization_ref = btrim(organization_ref) "
            "AND length(organization_ref) > 0 "
            "AND position('*' in organization_ref) = 0 "
            "AND lower(organization_ref) NOT IN ('all', 'any')",
            name="ck_dbi_admin_audit_organization_ref",
        ),
        CheckConstraint(
            "resource_ref = btrim(resource_ref) "
            "AND length(resource_ref) > 0 "
            "AND position('*' in resource_ref) = 0 "
            "AND lower(resource_ref) NOT IN ('all', 'any')",
            name="ck_dbi_admin_audit_resource_ref",
        ),
        CheckConstraint(
            "correlation_ref = btrim(correlation_ref) "
            "AND length(correlation_ref) > 0 "
            "AND position('*' in correlation_ref) = 0 "
            "AND lower(correlation_ref) NOT IN ('all', 'any')",
            name="ck_dbi_admin_audit_correlation_ref",
        ),
        UniqueConstraint(
            "tenant_ref",
            "organization_ref",
            "correlation_ref",
            "action",
            "resource_type",
            "resource_ref",
            name="uq_dbi_admin_audit_correlation_resource",
        ),
        Index(
            "ix_dbi_admin_audit_tenant_occurred",
            "tenant_ref",
            "occurred_at",
        ),
        Index(
            "ix_dbi_admin_audit_organization_occurred",
            "tenant_ref",
            "organization_ref",
            "occurred_at",
        ),
        Index(
            "ix_dbi_admin_audit_actor_occurred",
            "actor_principal_id",
            "occurred_at",
        ),
        Index(
            "ix_dbi_admin_audit_resource",
            "resource_type",
            "resource_ref",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    actor_principal_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_principals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_membership_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dbi_memberships.id", ondelete="RESTRICT"),
        nullable=False,
    )
    tenant_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(24), nullable=False)
    resource_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=DBIAdminAuditOutcome.SUCCEEDED.value,
    )
    correlation_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
