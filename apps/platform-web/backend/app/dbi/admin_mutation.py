"""Planificación inmutable de mutaciones administrativas DBI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.dbi.admin_policy import (
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminMembershipStatus,
)
from app.dbi.authorization import DBIFarmScope, DBIPermission, DBIPlotScope


class DBIAdminMutationKind(StrEnum):
    """Clases explícitas de cambio de membresía."""

    NOOP = "noop"
    UPDATE_AUTHORITY = "update_authority"
    DEACTIVATE = "deactivate"
    REACTIVATE = "reactivate"
    REVOKE = "revoke"


@dataclass(frozen=True, slots=True)
class DBIAdminMembershipMutationPlan:
    """Diferencia auditada entre dos snapshots de la misma membresía."""

    principal_ref: str
    tenant_ref: str
    kind: DBIAdminMutationKind
    before_status: DBIAdminMembershipStatus
    after_status: DBIAdminMembershipStatus
    permissions_to_add: frozenset[DBIPermission]
    permissions_to_remove: frozenset[DBIPermission]
    organization_scopes_to_add: frozenset[str]
    organization_scopes_to_remove: frozenset[str]
    farm_scopes_to_add: frozenset[DBIFarmScope]
    farm_scopes_to_remove: frozenset[DBIFarmScope]
    plot_scopes_to_add: frozenset[DBIPlotScope]
    plot_scopes_to_remove: frozenset[DBIPlotScope]
    affected_organization_refs: frozenset[str]
    admin_organizations_gained: frozenset[str]
    admin_organizations_lost: frozenset[str]

    @property
    def has_changes(self) -> bool:
        return self.kind is not DBIAdminMutationKind.NOOP

    @property
    def changes_authority(self) -> bool:
        return any(
            (
                self.permissions_to_add,
                self.permissions_to_remove,
                self.organization_scopes_to_add,
                self.organization_scopes_to_remove,
                self.farm_scopes_to_add,
                self.farm_scopes_to_remove,
                self.plot_scopes_to_add,
                self.plot_scopes_to_remove,
            )
        )


def _require_snapshot(value: object) -> DBIAdminAuthoritySnapshot:
    if not isinstance(value, DBIAdminAuthoritySnapshot):
        raise DBIAdminConflict()
    return value


def _mutation_kind(
    before: DBIAdminAuthoritySnapshot,
    after: DBIAdminAuthoritySnapshot,
    *,
    changes_authority: bool,
) -> DBIAdminMutationKind:
    if before == after:
        return DBIAdminMutationKind.NOOP
    if before.membership_status is DBIAdminMembershipStatus.REVOKED:
        raise DBIAdminConflict()
    if after.membership_status is DBIAdminMembershipStatus.REVOKED:
        return DBIAdminMutationKind.REVOKE
    if (
        before.membership_status is DBIAdminMembershipStatus.ACTIVE
        and after.membership_status is DBIAdminMembershipStatus.INACTIVE
    ):
        return DBIAdminMutationKind.DEACTIVATE
    if (
        before.membership_status is DBIAdminMembershipStatus.INACTIVE
        and after.membership_status is DBIAdminMembershipStatus.ACTIVE
    ):
        return DBIAdminMutationKind.REACTIVATE
    if before.membership_status is after.membership_status and changes_authority:
        return DBIAdminMutationKind.UPDATE_AUTHORITY
    raise DBIAdminConflict()


def plan_membership_mutation(
    before: DBIAdminAuthoritySnapshot,
    after: DBIAdminAuthoritySnapshot,
) -> DBIAdminMembershipMutationPlan:
    """Calcula un delta inmutable sin abrir sesiones ni modificar filas."""

    before = _require_snapshot(before)
    after = _require_snapshot(after)
    if (
        before.principal_ref != after.principal_ref
        or before.tenant_ref != after.tenant_ref
        or before.principal_active != after.principal_active
    ):
        raise DBIAdminConflict()

    permissions_to_add = after.permissions - before.permissions
    permissions_to_remove = before.permissions - after.permissions
    organization_scopes_to_add = (
        after.organization_scopes - before.organization_scopes
    )
    organization_scopes_to_remove = (
        before.organization_scopes - after.organization_scopes
    )
    farm_scopes_to_add = after.farm_scopes - before.farm_scopes
    farm_scopes_to_remove = before.farm_scopes - after.farm_scopes
    plot_scopes_to_add = after.plot_scopes - before.plot_scopes
    plot_scopes_to_remove = before.plot_scopes - after.plot_scopes

    changes_authority = any(
        (
            permissions_to_add,
            permissions_to_remove,
            organization_scopes_to_add,
            organization_scopes_to_remove,
            farm_scopes_to_add,
            farm_scopes_to_remove,
            plot_scopes_to_add,
            plot_scopes_to_remove,
        )
    )
    kind = _mutation_kind(
        before,
        after,
        changes_authority=changes_authority,
    )
    affected_organization_refs = frozenset(
        set(before.all_organization_refs) | set(after.all_organization_refs)
    )

    return DBIAdminMembershipMutationPlan(
        principal_ref=before.principal_ref,
        tenant_ref=before.tenant_ref,
        kind=kind,
        before_status=before.membership_status,
        after_status=after.membership_status,
        permissions_to_add=permissions_to_add,
        permissions_to_remove=permissions_to_remove,
        organization_scopes_to_add=organization_scopes_to_add,
        organization_scopes_to_remove=organization_scopes_to_remove,
        farm_scopes_to_add=farm_scopes_to_add,
        farm_scopes_to_remove=farm_scopes_to_remove,
        plot_scopes_to_add=plot_scopes_to_add,
        plot_scopes_to_remove=plot_scopes_to_remove,
        affected_organization_refs=affected_organization_refs,
        admin_organizations_gained=frozenset(
            after.effective_admin_organizations
            - before.effective_admin_organizations
        ),
        admin_organizations_lost=frozenset(
            before.effective_admin_organizations
            - after.effective_admin_organizations
        ),
    )
