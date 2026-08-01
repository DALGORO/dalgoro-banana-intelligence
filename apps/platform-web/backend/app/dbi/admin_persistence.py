"""Persistencia transaccional de planes administrativos DBI autorizados."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, update

from app.dbi.admin_creation_persistence import (
    DBIAdminCreationPersistenceRepository,
)
from app.dbi.admin_mutation_plan import (
    DBIAdminMembershipMutationPlan,
    DBIAdminPlannedAuditEvent,
)
from app.dbi.admin_policy import DBIAdminConflict
from app.dbi.models.admin_audit import (
    DBIAdminAuditEvent,
    DBIAdminAuditOutcome,
)
from app.dbi.models.identity import (
    DBIMembership,
    DBIMembershipPermission,
    DBIMembershipScope,
    DBIMembershipScopeType,
)


def _required_uuid(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise DBIAdminConflict()
    return value


def _required_plan(value: object) -> DBIAdminMembershipMutationPlan:
    if not isinstance(value, DBIAdminMembershipMutationPlan):
        raise DBIAdminConflict()
    if value.before.tenant_ref != value.after.tenant_ref:
        raise DBIAdminConflict()
    return value


def _validate_event(
    event: object,
    *,
    plan: DBIAdminMembershipMutationPlan,
    target_membership_id: UUID,
) -> DBIAdminPlannedAuditEvent:
    if not isinstance(event, DBIAdminPlannedAuditEvent):
        raise DBIAdminConflict()
    if (
        event.organization_ref not in plan.affected_organization_refs
        or event.resource_type != "membership"
        or event.resource_ref != str(target_membership_id)
    ):
        raise DBIAdminConflict()
    return event


def _validated_events(
    plan: DBIAdminMembershipMutationPlan,
    *,
    target_membership_id: UUID,
) -> tuple[DBIAdminPlannedAuditEvent, ...]:
    events = tuple(
        _validate_event(
            event,
            plan=plan,
            target_membership_id=target_membership_id,
        )
        for event in plan.audit_events
    )
    keys = {
        (
            event.organization_ref,
            event.action,
            event.resource_type,
            event.resource_ref,
            event.correlation_ref,
        )
        for event in events
    }
    if len(keys) != len(events):
        raise DBIAdminConflict()
    return events


class DBIAdminPersistenceRepository(DBIAdminCreationPersistenceRepository):
    """Aplica altas y mutaciones usando la misma sesión y transacción."""

    def apply_membership_mutation(
        self,
        *,
        actor_principal_id: UUID,
        actor_membership_id: UUID,
        target_membership_id: UUID,
        plan: DBIAdminMembershipMutationPlan,
    ) -> None:
        """Actualiza una membresía, sus hijos y auditoría sin confirmar cambios."""

        actor_principal_id = _required_uuid(actor_principal_id)
        actor_membership_id = _required_uuid(actor_membership_id)
        target_membership_id = _required_uuid(target_membership_id)
        plan = _required_plan(plan)

        if not plan.applied:
            if plan.audit_events:
                raise DBIAdminConflict()
            return
        if not plan.affected_organization_refs or not plan.audit_events:
            raise DBIAdminConflict()
        events = _validated_events(
            plan,
            target_membership_id=target_membership_id,
        )

        result = self._session.execute(
            update(DBIMembership)
            .where(
                DBIMembership.id == target_membership_id,
                DBIMembership.tenant_ref == plan.before.tenant_ref,
                DBIMembership.updated_at == plan.persisted_updated_at,
            )
            .values(
                status=plan.after.membership_status.value,
                updated_at=plan.next_updated_at,
            )
        )
        if getattr(result, "rowcount", None) != 1:
            raise DBIAdminConflict()

        if plan.changed_permissions:
            self._session.execute(
                delete(DBIMembershipPermission).where(
                    DBIMembershipPermission.membership_id
                    == target_membership_id
                )
            )
            for permission in sorted(
                plan.after.permissions,
                key=lambda value: value.value,
            ):
                self.add(
                    DBIMembershipPermission(
                        membership_id=target_membership_id,
                        permission=permission.value,
                    )
                )

        if plan.changed_scopes:
            self._session.execute(
                delete(DBIMembershipScope).where(
                    DBIMembershipScope.membership_id == target_membership_id
                )
            )
            for organization_ref in sorted(plan.after.organization_scopes):
                self.add(
                    DBIMembershipScope(
                        membership_id=target_membership_id,
                        scope_type=DBIMembershipScopeType.ORGANIZATION.value,
                        organization_ref=organization_ref,
                        farm_id=None,
                        plot_id=None,
                    )
                )
            for farm_scope in sorted(
                plan.after.farm_scopes,
                key=lambda value: (
                    value.organization_ref,
                    str(value.farm_id),
                ),
            ):
                self.add(
                    DBIMembershipScope(
                        membership_id=target_membership_id,
                        scope_type=DBIMembershipScopeType.FARM.value,
                        organization_ref=farm_scope.organization_ref,
                        farm_id=farm_scope.farm_id,
                        plot_id=None,
                    )
                )
            for plot_scope in sorted(
                plan.after.plot_scopes,
                key=lambda value: (
                    value.organization_ref,
                    str(value.farm_id),
                    str(value.plot_id),
                ),
            ):
                self.add(
                    DBIMembershipScope(
                        membership_id=target_membership_id,
                        scope_type=DBIMembershipScopeType.PLOT.value,
                        organization_ref=plot_scope.organization_ref,
                        farm_id=plot_scope.farm_id,
                        plot_id=plot_scope.plot_id,
                    )
                )

        for event in events:
            self.add(
                DBIAdminAuditEvent(
                    actor_principal_id=actor_principal_id,
                    actor_membership_id=actor_membership_id,
                    tenant_ref=plan.before.tenant_ref,
                    organization_ref=event.organization_ref,
                    action=event.action.value,
                    resource_type=event.resource_type,
                    resource_ref=event.resource_ref,
                    outcome=DBIAdminAuditOutcome.SUCCEEDED.value,
                    correlation_ref=event.correlation_ref,
                    occurred_at=plan.next_updated_at,
                )
            )
