"""Guardas transaccionales para operaciones administrativas DBI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.dbi.admin_policy import (
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminPolicy,
)
from app.dbi.admin_state import (
    DBIAdminLockedMembershipStates,
    DBIAdminPersistedMembershipState,
)


class DBIAdminGuardRepositoryPort(Protocol):
    """Puerto que impone el orden advisory locks → filas → snapshots."""

    def lock_and_load_membership_states(
        self,
        *,
        tenant_ref: str,
        organization_refs: frozenset[str],
        membership_ids: frozenset[UUID],
    ) -> DBIAdminLockedMembershipStates: ...

    def count_remaining_administrators(
        self,
        *,
        tenant_ref: str,
        organization_refs: frozenset[str],
        excluded_membership_id: UUID,
    ) -> dict[str, int]: ...


@dataclass(frozen=True, slots=True)
class DBIAdminGuardEvidence:
    """Evidencia no sensible de una guarda administrativa aprobada."""

    tenant_ref: str
    organization_refs: frozenset[str]
    lock_keys: tuple[int, ...]
    protected_organization_refs: frozenset[str] = frozenset()


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


class DBIAdminService:
    """Coordina locks, estado persistido y política sin aplicar mutaciones.

    El repositorio debe adquirir primero todos los advisory locks
    organizacionales en orden estable, después bloquear las membresías y sus
    principales, y finalmente construir los snapshots devueltos. El servicio no
    admite estados precargados fuera de esa operación atómica.
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
        return DBIAdminGuardEvidence(
            tenant_ref=tenant_ref,
            organization_refs=organization_refs,
            lock_keys=locked.lock_keys,
        )

    def guard_membership_create(
        self,
        actor: DBIAdminAuthoritySnapshot,
        requested: DBIAdminAuthoritySnapshot,
        *,
        actor_membership_id: UUID,
    ) -> DBIAdminGuardEvidence:
        """Serializa y autoriza la creación de una membresía activa."""

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
        return DBIAdminGuardEvidence(
            tenant_ref=requested.tenant_ref,
            organization_refs=organizations,
            lock_keys=locked.lock_keys,
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
        """Bloquea, recarga y protege una mutación de membresía."""

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

        return DBIAdminGuardEvidence(
            tenant_ref=before.tenant_ref,
            organization_refs=organizations,
            lock_keys=locked.lock_keys,
            protected_organization_refs=protected,
        )
