"""Persistencia idempotente de altas administrativas DBI."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.dbi.admin_creation_plan import (
    DBIAdminMembershipCreationPlan,
    DBIAdminPlannedCreationAuditEvent,
    DBIAdminPrincipalRegistrationPlan,
)
from app.dbi.admin_policy import DBIAdminConflict
from app.dbi.admin_repository import DBIAdminRepository
from app.dbi.admin_state import build_admin_membership_state
from app.dbi.models.admin_audit import (
    DBIAdminAuditEvent,
    DBIAdminAuditOutcome,
)
from app.dbi.models.identity import (
    DBIMembership,
    DBIMembershipPermission,
    DBIMembershipScope,
    DBIMembershipScopeType,
    DBIMembershipStatus,
    DBIPrincipal,
    DBIPrincipalStatus,
)


def _required_uuid(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise DBIAdminConflict()
    return value


def _required_principal_plan(
    value: object,
) -> DBIAdminPrincipalRegistrationPlan:
    if not isinstance(value, DBIAdminPrincipalRegistrationPlan):
        raise DBIAdminConflict()
    return value


def _required_membership_plan(
    value: object,
) -> DBIAdminMembershipCreationPlan:
    if not isinstance(value, DBIAdminMembershipCreationPlan):
        raise DBIAdminConflict()
    return value


def _validated_events(
    events: Iterable[object],
    *,
    organization_refs: frozenset[str],
    resource_type: str,
    resource_ref: str,
    correlation_ref: str,
) -> tuple[DBIAdminPlannedCreationAuditEvent, ...]:
    validated = tuple(events)
    if len(validated) != len(organization_refs):
        raise DBIAdminConflict()
    if not all(
        isinstance(event, DBIAdminPlannedCreationAuditEvent)
        and event.organization_ref in organization_refs
        and event.resource_type == resource_type
        and event.resource_ref == resource_ref
        and event.correlation_ref == correlation_ref
        for event in validated
    ):
        raise DBIAdminConflict()
    keys = {
        (
            event.organization_ref,
            event.action,
            event.resource_type,
            event.resource_ref,
            event.correlation_ref,
        )
        for event in validated
    }
    if len(keys) != len(validated):
        raise DBIAdminConflict()
    if {event.organization_ref for event in validated} != organization_refs:
        raise DBIAdminConflict()
    return validated


class DBIAdminCreationPersistenceRepository(DBIAdminRepository):
    """Crea recursos DBI sin abrir ni confirmar la transacción recibida."""

    def _add_creation_audit_events(
        self,
        *,
        actor_principal_id: UUID,
        actor_membership_id: UUID,
        tenant_ref: str,
        occurred_at,
        events: tuple[DBIAdminPlannedCreationAuditEvent, ...],
    ) -> None:
        for event in events:
            self.add(
                DBIAdminAuditEvent(
                    actor_principal_id=actor_principal_id,
                    actor_membership_id=actor_membership_id,
                    tenant_ref=tenant_ref,
                    organization_ref=event.organization_ref,
                    action=event.action.value,
                    resource_type=event.resource_type,
                    resource_ref=event.resource_ref,
                    outcome=DBIAdminAuditOutcome.SUCCEEDED.value,
                    correlation_ref=event.correlation_ref,
                    occurred_at=occurred_at,
                )
            )

    def _principal_candidates(
        self,
        *,
        principal_id: UUID,
        legacy_identity_ref: str,
    ) -> tuple[DBIPrincipal, ...]:
        rows = self._all(
            select(DBIPrincipal)
            .where(
                or_(
                    DBIPrincipal.id == principal_id,
                    DBIPrincipal.legacy_identity_ref == legacy_identity_ref,
                )
            )
            .order_by(DBIPrincipal.id)
        )
        if not all(isinstance(row, DBIPrincipal) for row in rows):
            raise DBIAdminConflict()
        return rows  # type: ignore[return-value]

    @staticmethod
    def _require_exact_active_principal(
        rows: tuple[DBIPrincipal, ...],
        *,
        principal_id: UUID,
        legacy_identity_ref: str,
    ) -> DBIPrincipal:
        if len(rows) != 1:
            raise DBIAdminConflict()
        principal = rows[0]
        if (
            principal.id != principal_id
            or principal.legacy_identity_ref != legacy_identity_ref
            or principal.status != DBIPrincipalStatus.ACTIVE.value
        ):
            raise DBIAdminConflict()
        return principal

    def register_principal(
        self,
        *,
        actor_principal_id: UUID,
        actor_membership_id: UUID,
        plan: DBIAdminPrincipalRegistrationPlan,
    ) -> bool:
        """Registra un principal activo o acepta un alta idéntica ya persistida."""

        actor_principal_id = _required_uuid(actor_principal_id)
        actor_membership_id = _required_uuid(actor_membership_id)
        plan = _required_principal_plan(plan)
        events = _validated_events(
            plan.audit_events,
            organization_refs=plan.organization_refs,
            resource_type="principal",
            resource_ref=str(plan.principal_id),
            correlation_ref=plan.correlation_ref,
        )

        inserted_id = self._session.execute(
            postgresql_insert(DBIPrincipal)
            .values(
                id=plan.principal_id,
                legacy_identity_ref=plan.legacy_identity_ref,
                status=DBIPrincipalStatus.ACTIVE.value,
                created_at=plan.occurred_at,
                updated_at=plan.occurred_at,
            )
            .on_conflict_do_nothing()
            .returning(DBIPrincipal.id)
        ).scalar_one_or_none()

        if inserted_id is not None:
            if inserted_id != plan.principal_id:
                raise DBIAdminConflict()
            self._add_creation_audit_events(
                actor_principal_id=actor_principal_id,
                actor_membership_id=actor_membership_id,
                tenant_ref=plan.tenant_ref,
                occurred_at=plan.occurred_at,
                events=events,
            )
            return True

        self._require_exact_active_principal(
            self._principal_candidates(
                principal_id=plan.principal_id,
                legacy_identity_ref=plan.legacy_identity_ref,
            ),
            principal_id=plan.principal_id,
            legacy_identity_ref=plan.legacy_identity_ref,
        )
        return False

    def _membership_candidates(
        self,
        *,
        membership_id: UUID,
        principal_id: UUID,
        tenant_ref: str,
    ) -> tuple[DBIMembership, ...]:
        rows = self._all(
            select(DBIMembership)
            .where(
                or_(
                    DBIMembership.id == membership_id,
                    (
                        (DBIMembership.principal_id == principal_id)
                        & (DBIMembership.tenant_ref == tenant_ref)
                    ),
                )
            )
            .order_by(DBIMembership.id)
        )
        if not all(isinstance(row, DBIMembership) for row in rows):
            raise DBIAdminConflict()
        return rows  # type: ignore[return-value]

    def _require_exact_membership(
        self,
        *,
        plan: DBIAdminMembershipCreationPlan,
        principal: DBIPrincipal,
    ) -> None:
        rows = self._membership_candidates(
            membership_id=plan.membership_id,
            principal_id=plan.principal_id,
            tenant_ref=plan.requested.tenant_ref,
        )
        if len(rows) != 1:
            raise DBIAdminConflict()
        membership = rows[0]
        if (
            membership.id != plan.membership_id
            or membership.principal_id != plan.principal_id
            or membership.tenant_ref != plan.requested.tenant_ref
            or membership.status != DBIMembershipStatus.ACTIVE.value
        ):
            raise DBIAdminConflict()

        state = build_admin_membership_state(
            principal=principal,
            membership=membership,
            permissions=self.list_permissions(membership_id=membership.id),
            scopes=self.list_scopes(membership_id=membership.id),
        )
        if state.authority != plan.requested:
            raise DBIAdminConflict()

    def _add_membership_authority(
        self,
        plan: DBIAdminMembershipCreationPlan,
    ) -> None:
        for permission in sorted(
            plan.requested.permissions,
            key=lambda value: value.value,
        ):
            self.add(
                DBIMembershipPermission(
                    membership_id=plan.membership_id,
                    permission=permission.value,
                )
            )
        for organization_ref in sorted(plan.requested.organization_scopes):
            self.add(
                DBIMembershipScope(
                    membership_id=plan.membership_id,
                    scope_type=DBIMembershipScopeType.ORGANIZATION.value,
                    organization_ref=organization_ref,
                    farm_id=None,
                    plot_id=None,
                )
            )
        for scope in sorted(
            plan.requested.farm_scopes,
            key=lambda value: (value.organization_ref, str(value.farm_id)),
        ):
            self.add(
                DBIMembershipScope(
                    membership_id=plan.membership_id,
                    scope_type=DBIMembershipScopeType.FARM.value,
                    organization_ref=scope.organization_ref,
                    farm_id=scope.farm_id,
                    plot_id=None,
                )
            )
        for scope in sorted(
            plan.requested.plot_scopes,
            key=lambda value: (
                value.organization_ref,
                str(value.farm_id),
                str(value.plot_id),
            ),
        ):
            self.add(
                DBIMembershipScope(
                    membership_id=plan.membership_id,
                    scope_type=DBIMembershipScopeType.PLOT.value,
                    organization_ref=scope.organization_ref,
                    farm_id=scope.farm_id,
                    plot_id=scope.plot_id,
                )
            )

    def create_membership(
        self,
        *,
        actor_principal_id: UUID,
        actor_membership_id: UUID,
        plan: DBIAdminMembershipCreationPlan,
    ) -> bool:
        """Crea una membresía completa o acepta un estado idéntico existente."""

        actor_principal_id = _required_uuid(actor_principal_id)
        actor_membership_id = _required_uuid(actor_membership_id)
        plan = _required_membership_plan(plan)
        events = _validated_events(
            plan.audit_events,
            organization_refs=plan.requested.all_organization_refs,
            resource_type="membership",
            resource_ref=str(plan.membership_id),
            correlation_ref=plan.correlation_ref,
        )
        principal = self._require_exact_active_principal(
            self._principal_candidates(
                principal_id=plan.principal_id,
                legacy_identity_ref=plan.requested.principal_ref,
            ),
            principal_id=plan.principal_id,
            legacy_identity_ref=plan.requested.principal_ref,
        )

        inserted_id = self._session.execute(
            postgresql_insert(DBIMembership)
            .values(
                id=plan.membership_id,
                principal_id=plan.principal_id,
                tenant_ref=plan.requested.tenant_ref,
                status=DBIMembershipStatus.ACTIVE.value,
                created_at=plan.occurred_at,
                updated_at=plan.occurred_at,
            )
            .on_conflict_do_nothing()
            .returning(DBIMembership.id)
        ).scalar_one_or_none()

        if inserted_id is not None:
            if inserted_id != plan.membership_id:
                raise DBIAdminConflict()
            self._add_membership_authority(plan)
            self._add_creation_audit_events(
                actor_principal_id=actor_principal_id,
                actor_membership_id=actor_membership_id,
                tenant_ref=plan.requested.tenant_ref,
                occurred_at=plan.occurred_at,
                events=events,
            )
            return True

        self._require_exact_membership(plan=plan, principal=principal)
        return False
