"""Planes puros e inmutables para altas administrativas DBI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID

from app.dbi.admin_policy import (
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminMembershipStatus,
)

_WILDCARD_REFS = frozenset({"all", "any"})


class DBIAdminCreationAction(StrEnum):
    """Acciones append-only producidas exclusivamente por altas nuevas."""

    PRINCIPAL_REGISTERED = "principal_registered"
    MEMBERSHIP_CREATED = "membership_created"


@dataclass(frozen=True, slots=True)
class DBIAdminPlannedCreationAuditEvent:
    """Evidencia mínima prevista para una organización y un recurso nuevo."""

    organization_ref: str
    action: DBIAdminCreationAction
    resource_type: str
    resource_ref: str
    correlation_ref: str


@dataclass(frozen=True, slots=True)
class DBIAdminPrincipalRegistrationPlan:
    """Alta propuesta de un principal global sin mutar su estado después."""

    principal_id: UUID
    legacy_identity_ref: str
    tenant_ref: str
    organization_refs: frozenset[str]
    occurred_at: datetime
    correlation_ref: str
    audit_events: tuple[DBIAdminPlannedCreationAuditEvent, ...]


@dataclass(frozen=True, slots=True)
class DBIAdminMembershipCreationPlan:
    """Alta propuesta de una membresía activa y su autoridad explícita."""

    membership_id: UUID
    principal_id: UUID
    requested: DBIAdminAuthoritySnapshot
    occurred_at: datetime
    correlation_ref: str
    audit_events: tuple[DBIAdminPlannedCreationAuditEvent, ...]


def _required_uuid(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise DBIAdminConflict()
    return value


def _validated_ref(value: object) -> str:
    if not isinstance(value, str):
        raise DBIAdminConflict()
    normalized = value.strip()
    if (
        not normalized
        or normalized != value
        or "*" in normalized
        or normalized.casefold() in _WILDCARD_REFS
    ):
        raise DBIAdminConflict()
    return normalized


def _validated_organizations(values: object) -> frozenset[str]:
    if not isinstance(values, frozenset) or not values:
        raise DBIAdminConflict()
    normalized = frozenset(_validated_ref(value) for value in values)
    if len(normalized) != len(values):
        raise DBIAdminConflict()
    return normalized


def _utc_timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DBIAdminConflict()
    return value.astimezone(timezone.utc)


def plan_principal_registration(
    *,
    principal_id: UUID,
    legacy_identity_ref: str,
    tenant_ref: str,
    organization_refs: frozenset[str],
    occurred_at: datetime,
    correlation_ref: str,
) -> DBIAdminPrincipalRegistrationPlan:
    """Construye una propuesta determinista de registro global idempotente."""

    target_id = _required_uuid(principal_id)
    target_ref = _validated_ref(legacy_identity_ref)
    tenant = _validated_ref(tenant_ref)
    organizations = _validated_organizations(organization_refs)
    timestamp = _utc_timestamp(occurred_at)
    correlation = _validated_ref(correlation_ref)
    resource_ref = str(target_id)

    events = tuple(
        DBIAdminPlannedCreationAuditEvent(
            organization_ref=organization_ref,
            action=DBIAdminCreationAction.PRINCIPAL_REGISTERED,
            resource_type="principal",
            resource_ref=resource_ref,
            correlation_ref=correlation,
        )
        for organization_ref in sorted(organizations)
    )
    return DBIAdminPrincipalRegistrationPlan(
        principal_id=target_id,
        legacy_identity_ref=target_ref,
        tenant_ref=tenant,
        organization_refs=organizations,
        occurred_at=timestamp,
        correlation_ref=correlation,
        audit_events=events,
    )


def plan_membership_creation(
    *,
    membership_id: UUID,
    principal_id: UUID,
    requested: DBIAdminAuthoritySnapshot,
    occurred_at: datetime,
    correlation_ref: str,
) -> DBIAdminMembershipCreationPlan:
    """Construye una propuesta de membresía inicial activa y explícita."""

    target_membership_id = _required_uuid(membership_id)
    target_principal_id = _required_uuid(principal_id)
    if not isinstance(requested, DBIAdminAuthoritySnapshot):
        raise DBIAdminConflict()
    if (
        not requested.principal_active
        or requested.membership_status is not DBIAdminMembershipStatus.ACTIVE
    ):
        raise DBIAdminConflict()

    organizations = _validated_organizations(
        requested.all_organization_refs
    )
    timestamp = _utc_timestamp(occurred_at)
    correlation = _validated_ref(correlation_ref)
    resource_ref = str(target_membership_id)

    events = tuple(
        DBIAdminPlannedCreationAuditEvent(
            organization_ref=organization_ref,
            action=DBIAdminCreationAction.MEMBERSHIP_CREATED,
            resource_type="membership",
            resource_ref=resource_ref,
            correlation_ref=correlation,
        )
        for organization_ref in sorted(organizations)
    )
    return DBIAdminMembershipCreationPlan(
        membership_id=target_membership_id,
        principal_id=target_principal_id,
        requested=requested,
        occurred_at=timestamp,
        correlation_ref=correlation,
        audit_events=events,
    )
