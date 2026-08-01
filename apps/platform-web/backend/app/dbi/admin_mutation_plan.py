"""Plan puro e inmutable para mutaciones administrativas DBI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from app.dbi.admin_policy import (
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminMembershipStatus,
)
from app.dbi.admin_state import DBIAdminPersistedMembershipState

_WILDCARD_REFS = frozenset({"all", "any"})


class DBIAdminMutationAction(StrEnum):
    """Acciones exitosas producidas por una mutación de membresía."""

    MEMBERSHIP_ACTIVATED = "membership_activated"
    MEMBERSHIP_INACTIVATED = "membership_inactivated"
    MEMBERSHIP_REVOKED = "membership_revoked"
    MEMBERSHIP_PERMISSIONS_REPLACED = "membership_permissions_replaced"
    MEMBERSHIP_SCOPES_REPLACED = "membership_scopes_replaced"


@dataclass(frozen=True, slots=True)
class DBIAdminPlannedAuditEvent:
    """Evidencia no sensible prevista para una organización afectada."""

    organization_ref: str
    action: DBIAdminMutationAction
    resource_type: str
    resource_ref: str
    correlation_ref: str


@dataclass(frozen=True, slots=True)
class DBIAdminMembershipMutationPlan:
    """Diferencia autorizable entre un estado bloqueado y el estado solicitado."""

    before: DBIAdminAuthoritySnapshot
    after: DBIAdminAuthoritySnapshot
    persisted_updated_at: datetime
    next_updated_at: datetime
    changed_status: bool
    changed_permissions: bool
    changed_scopes: bool
    affected_organization_refs: frozenset[str]
    audit_events: tuple[DBIAdminPlannedAuditEvent, ...]

    @property
    def applied(self) -> bool:
        return bool(
            self.changed_status
            or self.changed_permissions
            or self.changed_scopes
        )


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


def _utc_timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DBIAdminConflict()
    return value.astimezone(timezone.utc)


def _status_action(
    before: DBIAdminMembershipStatus,
    after: DBIAdminMembershipStatus,
) -> DBIAdminMutationAction | None:
    if before is after:
        return None
    if after is DBIAdminMembershipStatus.REVOKED:
        return DBIAdminMutationAction.MEMBERSHIP_REVOKED
    if after is DBIAdminMembershipStatus.ACTIVE:
        return DBIAdminMutationAction.MEMBERSHIP_ACTIVATED
    if after is DBIAdminMembershipStatus.INACTIVE:
        return DBIAdminMutationAction.MEMBERSHIP_INACTIVATED
    raise DBIAdminConflict()


def plan_membership_mutation(
    persisted: DBIAdminPersistedMembershipState,
    after: DBIAdminAuthoritySnapshot,
    *,
    next_updated_at: datetime,
    correlation_ref: str,
) -> DBIAdminMembershipMutationPlan:
    """Construye un plan determinista sin ejecutar operaciones persistentes."""

    if not isinstance(persisted, DBIAdminPersistedMembershipState):
        raise DBIAdminConflict()
    if not isinstance(after, DBIAdminAuthoritySnapshot):
        raise DBIAdminConflict()

    before = persisted.authority
    if (
        before.principal_ref != after.principal_ref
        or before.tenant_ref != after.tenant_ref
        or before.principal_active != after.principal_active
    ):
        raise DBIAdminConflict()

    correlation = _validated_ref(correlation_ref)
    persisted_version = _utc_timestamp(persisted.membership_updated_at)
    requested_version = _utc_timestamp(next_updated_at)

    changed_status = before.membership_status is not after.membership_status
    changed_permissions = before.permissions != after.permissions
    changed_scopes = (
        before.organization_scopes != after.organization_scopes
        or before.farm_scopes != after.farm_scopes
        or before.plot_scopes != after.plot_scopes
    )
    applied = changed_status or changed_permissions or changed_scopes

    if applied and requested_version <= persisted_version:
        raise DBIAdminConflict()
    effective_next_version = (
        requested_version if applied else persisted_version
    )

    organizations = frozenset(
        set(before.all_organization_refs) | set(after.all_organization_refs)
    )
    actions: list[DBIAdminMutationAction] = []
    status_action = _status_action(
        before.membership_status,
        after.membership_status,
    )
    if status_action is not None:
        actions.append(status_action)
    if changed_permissions:
        actions.append(
            DBIAdminMutationAction.MEMBERSHIP_PERMISSIONS_REPLACED
        )
    if changed_scopes:
        actions.append(DBIAdminMutationAction.MEMBERSHIP_SCOPES_REPLACED)

    resource_ref = str(persisted.membership_id)
    events = tuple(
        DBIAdminPlannedAuditEvent(
            organization_ref=organization_ref,
            action=action,
            resource_type="membership",
            resource_ref=resource_ref,
            correlation_ref=correlation,
        )
        for organization_ref in sorted(organizations)
        for action in actions
    )

    return DBIAdminMembershipMutationPlan(
        before=before,
        after=after,
        persisted_updated_at=persisted_version,
        next_updated_at=effective_next_version,
        changed_status=changed_status,
        changed_permissions=changed_permissions,
        changed_scopes=changed_scopes,
        affected_organization_refs=organizations,
        audit_events=events,
    )
