"""Resolución cerrada del actor administrativo DBI autenticado."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.dbi.admin_policy import DBIAdminConflict
from app.dbi.admin_repository import DBIAdminRepository
from app.dbi.admin_state import (
    DBIAdminPersistedMembershipState,
    build_admin_membership_state,
)
from app.dbi.authorization import DBIAccessContext, DBIFarmScope
from app.dbi.models.identity import (
    DBIMembership,
    DBIMembershipPermission,
    DBIMembershipScope,
    DBIMembershipStatus,
    DBIPrincipal,
    DBIPrincipalStatus,
)


class DBIAdminActorRepositoryPort(Protocol):
    """Lecturas mínimas para reconstruir al actor desde autoridad DBI."""

    def get_principal(self, *, principal_id: UUID) -> DBIPrincipal | None: ...

    def list_memberships(
        self,
        *,
        principal_id: UUID,
        tenant_ref: str,
    ) -> Sequence[DBIMembership]: ...

    def list_permissions(
        self,
        *,
        membership_id: UUID,
    ) -> Sequence[DBIMembershipPermission]: ...

    def list_scopes(
        self,
        *,
        membership_id: UUID,
    ) -> Sequence[DBIMembershipScope]: ...


class DBIAdminActorRepository:
    """Adaptador de solo lectura sobre la sesión DBI recibida."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session debe ser una sesión SQLAlchemy DBI.")
        self._session = session
        self._admin_repository = DBIAdminRepository(session)

    def get_principal(self, *, principal_id: UUID) -> DBIPrincipal | None:
        if not isinstance(principal_id, UUID):
            raise TypeError("principal_id debe ser UUID.")
        principal = self._session.get(DBIPrincipal, principal_id)
        if principal is None:
            return None
        if not isinstance(principal, DBIPrincipal):
            raise DBIAdminConflict()
        return principal

    def list_memberships(
        self,
        *,
        principal_id: UUID,
        tenant_ref: str,
    ) -> tuple[DBIMembership, ...]:
        return self._admin_repository.list_memberships(
            principal_id=principal_id,
            tenant_ref=tenant_ref,
        )

    def list_permissions(
        self,
        *,
        membership_id: UUID,
    ) -> tuple[DBIMembershipPermission, ...]:
        return self._admin_repository.list_permissions(
            membership_id=membership_id,
        )

    def list_scopes(
        self,
        *,
        membership_id: UUID,
    ) -> tuple[DBIMembershipScope, ...]:
        return self._admin_repository.list_scopes(
            membership_id=membership_id,
        )


def _required_context(value: object) -> DBIAccessContext:
    if not isinstance(value, DBIAccessContext):
        raise DBIAdminConflict()
    return value


def _only_active_principal(
    repository: DBIAdminActorRepositoryPort,
    *,
    principal_id: UUID,
) -> DBIPrincipal:
    principal = repository.get_principal(principal_id=principal_id)
    if (
        not isinstance(principal, DBIPrincipal)
        or principal.id != principal_id
        or principal.status != DBIPrincipalStatus.ACTIVE.value
    ):
        raise DBIAdminConflict()
    return principal


def _only_active_membership(
    repository: DBIAdminActorRepositoryPort,
    *,
    principal_id: UUID,
    tenant_ref: str,
) -> DBIMembership:
    memberships = tuple(
        repository.list_memberships(
            principal_id=principal_id,
            tenant_ref=tenant_ref,
        )
    )
    if len(memberships) != 1:
        raise DBIAdminConflict()
    membership = memberships[0]
    if (
        not isinstance(membership, DBIMembership)
        or membership.principal_id != principal_id
        or membership.tenant_ref != tenant_ref
        or membership.status != DBIMembershipStatus.ACTIVE.value
    ):
        raise DBIAdminConflict()
    return membership


def _context_matches_state(
    context: DBIAccessContext,
    state: DBIAdminPersistedMembershipState,
) -> bool:
    authority = state.authority
    derived_farm_scopes = frozenset(
        DBIFarmScope(
            organization_ref=scope.organization_ref,
            farm_id=scope.farm_id,
        )
        for scope in authority.plot_scopes
    )
    expected_access_farms = frozenset(
        set(authority.farm_scopes) | set(derived_farm_scopes)
    )
    return (
        authority.principal_active
        and authority.membership_active
        and authority.tenant_ref == context.tenant_ref
        and authority.permissions == context.permissions
        and authority.all_organization_refs == context.organization_refs
        and expected_access_farms == context.farm_scopes
        and authority.plot_scopes == context.plot_scopes
    )


class DBIAdminActorResolver:
    """Reconstruye el actor administrativo y niega ante cualquier divergencia."""

    def __init__(self, repository: DBIAdminActorRepositoryPort) -> None:
        self._repository = repository

    def resolve(
        self,
        *,
        context: DBIAccessContext,
    ) -> DBIAdminPersistedMembershipState:
        context = _required_context(context)
        try:
            principal_id = UUID(context.principal_ref)
        except (TypeError, ValueError) as error:
            raise DBIAdminConflict() from error

        principal = _only_active_principal(
            self._repository,
            principal_id=principal_id,
        )
        membership = _only_active_membership(
            self._repository,
            principal_id=principal_id,
            tenant_ref=context.tenant_ref,
        )
        state = build_admin_membership_state(
            principal=principal,
            membership=membership,
            permissions=tuple(
                self._repository.list_permissions(
                    membership_id=membership.id,
                )
            ),
            scopes=tuple(
                self._repository.list_scopes(
                    membership_id=membership.id,
                )
            ),
        )
        if (
            state.principal_id != principal_id
            or state.membership_id != membership.id
            or not _context_matches_state(context, state)
        ):
            raise DBIAdminConflict()
        return state
