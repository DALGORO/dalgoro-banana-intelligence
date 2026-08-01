"""Guardas, altas y mutaciones transaccionales para administración DBI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.dbi.admin_creation_plan import (
    DBIAdminMembershipCreationPlan,
    DBIAdminPrincipalRegistrationPlan,
    plan_membership_creation,
    plan_principal_registration,
)
from app.dbi.admin_mutation_plan import (
    DBIAdminMembershipMutationPlan,
    plan_membership_mutation,
)
from app.dbi.admin_policy import (
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminPolicy,
)
from app.dbi.admin_state import (
    DBIAdminLockedMembershipStates,
    DBIAdminPersistedMembershipState,
)
from app.dbi.authorization import DBIFarmScope, DBIPlotScope


class DBIAdminGuardRepositoryPort(Protocol):
    """Puerto que impone locks, carga exacta y persistencia sin commit interno."""

    def lock_and_load_membership_states(
        self,
        *,
        tenant_ref: str,
        organization_refs: frozenset[str],
        membership_ids: frozenset[UUID],
    ) -> DBIAdminLockedMembershipStates: ...

    def scope_hierarchy_matches(
        self,
        *,
        farm_scopes: frozenset[DBIFarmScope],
        plot_scopes: frozenset[DBIPlotScope],
    ) -> bool: ...

    def count_remaining_administrators(
        self,
        *,
        tenant_ref: str,
        organization_refs: frozenset[str],
        excluded_membership_id: UUID,
    ) -> dict[str, int]: ...

    def register_principal(
        self,
        *,
        actor_principal_id: UUID,
        actor_membership_id: UUID,
        plan: DBIAdminPrincipalRegistrationPlan,
    ) -> bool: ...

    def create_membership(
        self,
        *,
        actor_principal_id: UUID,
        actor_membership_id: UUID,
        plan: DBIAdminMembershipCreationPlan,
    ) -> bool: ...

    def apply_membership_mutation(
        self,
        *,
        actor_principal_id: UUID,
        actor_membership_id: UUID,
        target_membership_id: UUID,
        plan: DBIAdminMembershipMutationPlan,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class DBIAdminGuardEvidence:
    """Evidencia no sensible de una guarda administrativa aprobada."""

    tenant_ref: str
    organization_refs: frozenset[str]
    lock_keys: tuple[int, ...]
    protected_organization_refs: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class DBIAdminPrincipalRegistrationEvidence:
    """Resultado de un registro nuevo o idempotente de principal."""

    guard: DBIAdminGuardEvidence
    plan: DBIAdminPrincipalRegistrationPlan
    created: bool


@dataclass(frozen=True, slots=True)
class DBIAdminMembershipCreationEvidence:
    """Resultado de una creación nueva o idempotente de membresía."""

    guard: DBIAdminGuardEvidence
    plan: DBIAdminMembershipCreationPlan
    created: bool


@dataclass(frozen=True, slots=True)
class DBIAdminMembershipMutationEvidence:
    """Resultado autorizado y plan aplicado dentro de la transacción externa."""

    guard: DBIAdminGuardEvidence
    plan: DBIAdminMembershipMutationPlan


@dataclass(frozen=True, slots=True)
class _AuthorizedActorOperation:
    locked: DBIAdminLockedMembershipStates
    actor: DBIAdminPersistedMembershipState
    tenant_ref: str
    organization_refs: frozenset[str]


@dataclass(frozen=True, slots=True)
class _AuthorizedMembershipChange:
    locked: DBIAdminLockedMembershipStates
    actor: DBIAdminPersistedMembershipState
    target: DBIAdminPersistedMembershipState
    organization_refs: frozenset[str]
    protected_organization_refs: frozenset[str]


def _required_uuid(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise DBIAdminConflict()
    return value


def _required_snapshot(value: object) -> DBIAdminAuthoritySnapshot:
    if not isinstance(value, DBIAdminAuthoritySnapshot):
        raise DBIAdminConflict()
    return value


def _required_locked_states(
    value: object,
    *,
    membership_ids: frozenset[UUID],
) -> DBIAdminLockedMembershipStates:
    if not isinstance(value, DBIAdminLockedMembershipStates):
        raise DBIAdminConflict()
    if not isinstance(value.lock_keys, tuple) or not all(
        isinstance(key, int) and not isinstance(key, bool)
        for key in value.lock_keys
    ):
        raise DBIAdminConflict()
    if not isinstance(value.states, Mapping):
        raise DBIAdminConflict()
    if frozenset(value.states.keys()) != membership_ids:
        raise DBIAdminConflict()
    if not all(
        isinstance(membership_id, UUID)
        and isinstance(state, DBIAdminPersistedMembershipState)
        and membership_id == state.membership_id
        for membership_id, state in value.states.items()
    ):
        raise DBIAdminConflict()
    return value


def _required_state(
    locked: DBIAdminLockedMembershipStates,
    membership_id: UUID,
) -> DBIAdminPersistedMembershipState:
    state = locked.states.get(membership_id)
    if not isinstance(state, DBIAdminPersistedMembershipState):
        raise DBIAdminConflict()
    return state


def _require_authority_match(
    persisted: DBIAdminPersistedMembershipState,
    expected: DBIAdminAuthoritySnapshot,
) -> None:
    if persisted.authority != expected:
        raise DBIAdminConflict()


def _actor_guard_evidence(
    authorized: _AuthorizedActorOperation,
) -> DBIAdminGuardEvidence:
    return DBIAdminGuardEvidence(
        tenant_ref=authorized.tenant_ref,
        organization_refs=authorized.organization_refs,
        lock_keys=authorized.locked.lock_keys,
    )


def _change_guard_evidence(
    authorized: _AuthorizedMembershipChange,
) -> DBIAdminGuardEvidence:
    return DBIAdminGuardEvidence(
        tenant_ref=authorized.target.authority.tenant_ref,
        organization_refs=authorized.organization_refs,
        lock_keys=authorized.locked.lock_keys,
        protected_organization_refs=authorized.protected_organization_refs,
    )


class DBIAdminService:
    """Coordina locks, política, planes y persistencia sin abrir transacciones.

    El repositorio adquiere advisory locks organizacionales y bloquea las
    membresías como raíces mutables. El servicio valida autoridad y jerarquía,
    construye planes puros y delega la persistencia sobre la misma sesión.
    """

    def __init__(self, repository: DBIAdminGuardRepositoryPort) -> None:
        self._repository = repository

    def _lock_and_load(
        self,
        *,
        tenant_ref: str,
        organization_refs: frozenset[str],
        membership_ids: frozenset[UUID],
    ) -> DBIAdminLockedMembershipStates:
        if not isinstance(membership_ids, frozenset) or not membership_ids:
            raise DBIAdminConflict()
        normalized_ids = frozenset(
            _required_uuid(value) for value in membership_ids
        )
        locked = self._repository.lock_and_load_membership_states(
            tenant_ref=tenant_ref,
            organization_refs=organization_refs,
            membership_ids=normalized_ids,
        )
        return _required_locked_states(locked, membership_ids=normalized_ids)

    def _require_scope_hierarchy(
        self,
        snapshot: DBIAdminAuthoritySnapshot,
    ) -> None:
        if not self._repository.scope_hierarchy_matches(
            farm_scopes=snapshot.farm_scopes,
            plot_scopes=snapshot.plot_scopes,
        ):
            raise DBIAdminConflict()

    def _authorize_principal_registration(
        self,
        actor: DBIAdminAuthoritySnapshot,
        *,
        actor_membership_id: UUID,
        target_principal_ref: str,
        tenant_ref: str,
        organization_refs: frozenset[str],
    ) -> _AuthorizedActorOperation:
        actor = _required_snapshot(actor)
        actor_membership_id = _required_uuid(actor_membership_id)
        locked = self._lock_and_load(
            tenant_ref=tenant_ref,
            organization_refs=organization_refs,
            membership_ids=frozenset({actor_membership_id}),
        )
        persisted_actor = _required_state(locked, actor_membership_id)
        _require_authority_match(persisted_actor, actor)
        DBIAdminPolicy.require_principal_registration(
            persisted_actor.authority,
            target_principal_ref=target_principal_ref,
            tenant_ref=tenant_ref,
            organization_refs=organization_refs,
        )
        return _AuthorizedActorOperation(
            locked=locked,
            actor=persisted_actor,
            tenant_ref=tenant_ref,
            organization_refs=organization_refs,
        )

    def guard_principal_registration(
        self,
        actor: DBIAdminAuthoritySnapshot,
        *,
        actor_membership_id: UUID,
        target_principal_ref: str,
        tenant_ref: str,
        organization_refs: frozenset[str],
    ) -> DBIAdminGuardEvidence:
        """Serializa y autoriza el registro idempotente de un principal."""

        return _actor_guard_evidence(
            self._authorize_principal_registration(
                actor,
                actor_membership_id=actor_membership_id,
                target_principal_ref=target_principal_ref,
                tenant_ref=tenant_ref,
                organization_refs=organization_refs,
            )
        )

    def register_principal(
        self,
        actor: DBIAdminAuthoritySnapshot,
        *,
        actor_membership_id: UUID,
        principal_id: UUID,
        target_principal_ref: str,
        tenant_ref: str,
        organization_refs: frozenset[str],
        occurred_at: datetime,
        correlation_ref: str,
    ) -> DBIAdminPrincipalRegistrationEvidence:
        """Autoriza y registra un principal activo de forma idempotente."""

        actor_membership_id = _required_uuid(actor_membership_id)
        authorized = self._authorize_principal_registration(
            actor,
            actor_membership_id=actor_membership_id,
            target_principal_ref=target_principal_ref,
            tenant_ref=tenant_ref,
            organization_refs=organization_refs,
        )
        plan = plan_principal_registration(
            principal_id=principal_id,
            legacy_identity_ref=target_principal_ref,
            tenant_ref=tenant_ref,
            organization_refs=organization_refs,
            occurred_at=occurred_at,
            correlation_ref=correlation_ref,
        )
        created = self._repository.register_principal(
            actor_principal_id=authorized.actor.principal_id,
            actor_membership_id=actor_membership_id,
            plan=plan,
        )
        return DBIAdminPrincipalRegistrationEvidence(
            guard=_actor_guard_evidence(authorized),
            plan=plan,
            created=created,
        )

    def _authorize_membership_create(
        self,
        actor: DBIAdminAuthoritySnapshot,
        requested: DBIAdminAuthoritySnapshot,
        *,
        actor_membership_id: UUID,
    ) -> _AuthorizedActorOperation:
        actor = _required_snapshot(actor)
        requested = _required_snapshot(requested)
        actor_membership_id = _required_uuid(actor_membership_id)
        organizations = requested.all_organization_refs
        locked = self._lock_and_load(
            tenant_ref=requested.tenant_ref,
            organization_refs=organizations,
            membership_ids=frozenset({actor_membership_id}),
        )
        persisted_actor = _required_state(locked, actor_membership_id)
        _require_authority_match(persisted_actor, actor)
        DBIAdminPolicy.require_membership_create(
            persisted_actor.authority,
            requested,
        )
        self._require_scope_hierarchy(requested)
        return _AuthorizedActorOperation(
            locked=locked,
            actor=persisted_actor,
            tenant_ref=requested.tenant_ref,
            organization_refs=organizations,
        )

    def guard_membership_create(
        self,
        actor: DBIAdminAuthoritySnapshot,
        requested: DBIAdminAuthoritySnapshot,
        *,
        actor_membership_id: UUID,
    ) -> DBIAdminGuardEvidence:
        """Serializa y autoriza la creación de una membresía activa."""

        return _actor_guard_evidence(
            self._authorize_membership_create(
                actor,
                requested,
                actor_membership_id=actor_membership_id,
            )
        )

    def create_membership(
        self,
        actor: DBIAdminAuthoritySnapshot,
        requested: DBIAdminAuthoritySnapshot,
        *,
        actor_membership_id: UUID,
        membership_id: UUID,
        principal_id: UUID,
        occurred_at: datetime,
        correlation_ref: str,
    ) -> DBIAdminMembershipCreationEvidence:
        """Autoriza y crea una membresía activa de forma idempotente."""

        actor_membership_id = _required_uuid(actor_membership_id)
        authorized = self._authorize_membership_create(
            actor,
            requested,
            actor_membership_id=actor_membership_id,
        )
        plan = plan_membership_creation(
            membership_id=membership_id,
            principal_id=principal_id,
            requested=requested,
            occurred_at=occurred_at,
            correlation_ref=correlation_ref,
        )
        created = self._repository.create_membership(
            actor_principal_id=authorized.actor.principal_id,
            actor_membership_id=actor_membership_id,
            plan=plan,
        )
        return DBIAdminMembershipCreationEvidence(
            guard=_actor_guard_evidence(authorized),
            plan=plan,
            created=created,
        )

    def _authorize_membership_change(
        self,
        actor: DBIAdminAuthoritySnapshot,
        before: DBIAdminAuthoritySnapshot,
        after: DBIAdminAuthoritySnapshot,
        *,
        actor_membership_id: UUID,
        target_membership_id: UUID,
        expected_updated_at: datetime,
    ) -> _AuthorizedMembershipChange:
        actor = _required_snapshot(actor)
        before = _required_snapshot(before)
        after = _required_snapshot(after)
        actor_membership_id = _required_uuid(actor_membership_id)
        target_membership_id = _required_uuid(target_membership_id)

        organizations = frozenset(
            set(before.all_organization_refs) | set(after.all_organization_refs)
        )
        membership_ids = frozenset(
            {actor_membership_id, target_membership_id}
        )
        locked = self._lock_and_load(
            tenant_ref=before.tenant_ref,
            organization_refs=organizations,
            membership_ids=membership_ids,
        )
        persisted_actor = _required_state(locked, actor_membership_id)
        persisted_target = _required_state(locked, target_membership_id)
        _require_authority_match(persisted_actor, actor)
        _require_authority_match(persisted_target, before)
        persisted_target.require_membership_version(expected_updated_at)

        DBIAdminPolicy.require_membership_change(
            persisted_actor.authority,
            persisted_target.authority,
            after,
        )
        self._require_scope_hierarchy(after)
        protected = DBIAdminPolicy.organizations_losing_last_admin_protection(
            persisted_target.authority,
            after,
        )
        if protected:
            remaining_counts = self._repository.count_remaining_administrators(
                tenant_ref=before.tenant_ref,
                organization_refs=protected,
                excluded_membership_id=target_membership_id,
            )
            DBIAdminPolicy.require_remaining_administrators(
                protected,
                remaining_counts,
            )

        return _AuthorizedMembershipChange(
            locked=locked,
            actor=persisted_actor,
            target=persisted_target,
            organization_refs=organizations,
            protected_organization_refs=protected,
        )

    def guard_membership_change(
        self,
        actor: DBIAdminAuthoritySnapshot,
        before: DBIAdminAuthoritySnapshot,
        after: DBIAdminAuthoritySnapshot,
        *,
        actor_membership_id: UUID,
        target_membership_id: UUID,
        expected_updated_at: datetime,
    ) -> DBIAdminGuardEvidence:
        """Bloquea, recarga y protege una mutación sin persistirla."""

        authorized = self._authorize_membership_change(
            actor,
            before,
            after,
            actor_membership_id=actor_membership_id,
            target_membership_id=target_membership_id,
            expected_updated_at=expected_updated_at,
        )
        return _change_guard_evidence(authorized)

    def mutate_membership(
        self,
        actor: DBIAdminAuthoritySnapshot,
        before: DBIAdminAuthoritySnapshot,
        after: DBIAdminAuthoritySnapshot,
        *,
        actor_membership_id: UUID,
        target_membership_id: UUID,
        expected_updated_at: datetime,
        next_updated_at: datetime,
        correlation_ref: str,
    ) -> DBIAdminMembershipMutationEvidence:
        """Autoriza y aplica una mutación usando la transacción externa."""

        authorized = self._authorize_membership_change(
            actor,
            before,
            after,
            actor_membership_id=actor_membership_id,
            target_membership_id=target_membership_id,
            expected_updated_at=expected_updated_at,
        )
        plan = plan_membership_mutation(
            authorized.target,
            after,
            next_updated_at=next_updated_at,
            correlation_ref=correlation_ref,
        )
        self._repository.apply_membership_mutation(
            actor_principal_id=authorized.actor.principal_id,
            actor_membership_id=actor_membership_id,
            target_membership_id=target_membership_id,
            plan=plan,
        )
        return DBIAdminMembershipMutationEvidence(
            guard=_change_guard_evidence(authorized),
            plan=plan,
        )
