"""Resolución canónica de identidad y membresías DBI."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypeVar
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.models.agriculture import Farm, Plot
from app.dbi.models.identity import (
    DBIMembership,
    DBIMembershipPermission,
    DBIMembershipScope,
    DBIMembershipScopeType,
    DBIMembershipStatus,
    DBIPrincipal,
    DBIPrincipalStatus,
)

ModelT = TypeVar("ModelT")
_WILDCARD_REFS = frozenset({"all", "any"})


class DBIIdentityRepositoryPort(Protocol):
    """Consultas mínimas que necesita el resolvedor."""

    def list_principals(
        self,
        *,
        legacy_identity_ref: str,
    ) -> Sequence[DBIPrincipal]: ...

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

    def farm_matches_scope(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
    ) -> bool: ...

    def plot_matches_scope(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> bool: ...


class DBIIdentityRepository:
    """Repositorio de identidad ligado a una sesión DBI recibida."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _all(
        self,
        statement: Select[tuple[ModelT]],
    ) -> tuple[ModelT, ...]:
        return tuple(self._session.execute(statement).scalars().all())

    def _exists(
        self,
        statement: Select[tuple[UUID]],
    ) -> bool:
        return (
            self._session.execute(statement).scalar_one_or_none()
            is not None
        )

    def list_principals(
        self,
        *,
        legacy_identity_ref: str,
    ) -> tuple[DBIPrincipal, ...]:
        """Busca candidatos sin asumir que la restricción única es suficiente."""

        return self._all(
            select(DBIPrincipal).where(
                DBIPrincipal.legacy_identity_ref == legacy_identity_ref
            )
        )

    def list_memberships(
        self,
        *,
        principal_id: UUID,
        tenant_ref: str,
    ) -> tuple[DBIMembership, ...]:
        """Busca membresías exactas de un principal dentro de un tenant."""

        return self._all(
            select(DBIMembership).where(
                DBIMembership.principal_id == principal_id,
                DBIMembership.tenant_ref == tenant_ref,
            )
        )

    def list_permissions(
        self,
        *,
        membership_id: UUID,
    ) -> tuple[DBIMembershipPermission, ...]:
        """Obtiene los permisos globales de una membresía."""

        return self._all(
            select(DBIMembershipPermission).where(
                DBIMembershipPermission.membership_id == membership_id
            )
        )

    def list_scopes(
        self,
        *,
        membership_id: UUID,
    ) -> tuple[DBIMembershipScope, ...]:
        """Obtiene los ámbitos jerárquicos de una membresía."""

        return self._all(
            select(DBIMembershipScope).where(
                DBIMembershipScope.membership_id == membership_id
            )
        )

    def farm_matches_scope(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
    ) -> bool:
        """Confirma la organización real de una finca."""

        return self._exists(
            select(Farm.id).where(
                Farm.id == farm_id,
                Farm.organization_ref == organization_ref,
            )
        )

    def plot_matches_scope(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> bool:
        """Confirma conjuntamente organización, finca y lote."""

        return self._exists(
            select(Plot.id)
            .join(Farm, Plot.farm_id == Farm.id)
            .where(
                Plot.id == plot_id,
                Plot.farm_id == farm_id,
                Farm.organization_ref == organization_ref,
            )
        )


def _normalized_ref(value: object) -> str:
    if not isinstance(value, str):
        raise DBIAccessDenied()

    normalized = value.strip()
    if (
        not normalized
        or "*" in normalized
        or normalized.casefold() in _WILDCARD_REFS
    ):
        raise DBIAccessDenied()
    return normalized


def _only(values: Sequence[ModelT]) -> ModelT:
    if len(values) != 1:
        raise DBIAccessDenied()
    return values[0]


class DBIAccessContextResolver:
    """Construye un contexto solo desde autoridad DBI activa y consistente."""

    def __init__(self, repository: DBIIdentityRepositoryPort) -> None:
        self._repository = repository

    def resolve(
        self,
        *,
        legacy_identity_ref: str,
        tenant_ref: str,
    ) -> DBIAccessContext:
        """Resuelve una identidad autenticada con denegación cerrada."""

        normalized_identity = _normalized_ref(legacy_identity_ref)
        normalized_tenant = _normalized_ref(tenant_ref)

        principal = _only(
            self._repository.list_principals(
                legacy_identity_ref=normalized_identity
            )
        )
        if (
            not isinstance(principal, DBIPrincipal)
            or not isinstance(principal.id, UUID)
            or principal.legacy_identity_ref != normalized_identity
            or principal.status != DBIPrincipalStatus.ACTIVE.value
        ):
            raise DBIAccessDenied()

        membership = _only(
            self._repository.list_memberships(
                principal_id=principal.id,
                tenant_ref=normalized_tenant,
            )
        )
        if (
            not isinstance(membership, DBIMembership)
            or not isinstance(membership.id, UUID)
            or membership.principal_id != principal.id
            or membership.tenant_ref != normalized_tenant
            or membership.status != DBIMembershipStatus.ACTIVE.value
        ):
            raise DBIAccessDenied()

        permissions = self._resolve_permissions(membership)
        (
            organization_refs,
            farm_scopes,
            plot_scopes,
        ) = self._resolve_scopes(membership)

        try:
            return DBIAccessContext(
                principal_ref=str(principal.id),
                tenant_ref=normalized_tenant,
                organization_refs=frozenset(organization_refs),
                farm_scopes=frozenset(farm_scopes),
                plot_scopes=frozenset(plot_scopes),
                permissions=frozenset(permissions),
            )
        except (TypeError, ValueError) as error:
            raise DBIAccessDenied() from error

    def _resolve_permissions(
        self,
        membership: DBIMembership,
    ) -> set[DBIPermission]:
        rows = self._repository.list_permissions(
            membership_id=membership.id
        )
        if not rows:
            raise DBIAccessDenied()

        raw_permissions: set[str] = set()
        permissions: set[DBIPermission] = set()
        for row in rows:
            if (
                not isinstance(row, DBIMembershipPermission)
                or row.membership_id != membership.id
                or row.permission in raw_permissions
            ):
                raise DBIAccessDenied()
            raw_permissions.add(row.permission)
            try:
                permissions.add(DBIPermission(row.permission))
            except (TypeError, ValueError) as error:
                raise DBIAccessDenied() from error

        return permissions

    def _resolve_scopes(
        self,
        membership: DBIMembership,
    ) -> tuple[
        set[str],
        set[DBIFarmScope],
        set[DBIPlotScope],
    ]:
        organization_refs: set[str] = set()
        farm_scopes: set[DBIFarmScope] = set()
        plot_scopes: set[DBIPlotScope] = set()
        seen: set[tuple[object, ...]] = set()

        for row in self._repository.list_scopes(
            membership_id=membership.id
        ):
            if (
                not isinstance(row, DBIMembershipScope)
                or row.membership_id != membership.id
            ):
                raise DBIAccessDenied()

            try:
                scope_type = DBIMembershipScopeType(row.scope_type)
            except (TypeError, ValueError) as error:
                raise DBIAccessDenied() from error

            organization_ref = _normalized_ref(row.organization_ref)
            if organization_ref != row.organization_ref:
                raise DBIAccessDenied()

            key = (
                scope_type,
                organization_ref,
                row.farm_id,
                row.plot_id,
            )
            if key in seen:
                raise DBIAccessDenied()
            seen.add(key)

            organization_refs.add(organization_ref)
            if scope_type is DBIMembershipScopeType.ORGANIZATION:
                if row.farm_id is not None or row.plot_id is not None:
                    raise DBIAccessDenied()
                continue

            if not isinstance(row.farm_id, UUID):
                raise DBIAccessDenied()
            if not self._repository.farm_matches_scope(
                organization_ref=organization_ref,
                farm_id=row.farm_id,
            ):
                raise DBIAccessDenied()

            farm_scope = DBIFarmScope(
                organization_ref=organization_ref,
                farm_id=row.farm_id,
            )
            farm_scopes.add(farm_scope)

            if scope_type is DBIMembershipScopeType.FARM:
                if row.plot_id is not None:
                    raise DBIAccessDenied()
                continue

            if (
                scope_type is not DBIMembershipScopeType.PLOT
                or not isinstance(row.plot_id, UUID)
                or not self._repository.plot_matches_scope(
                    organization_ref=organization_ref,
                    farm_id=row.farm_id,
                    plot_id=row.plot_id,
                )
            ):
                raise DBIAccessDenied()

            plot_scopes.add(
                DBIPlotScope(
                    organization_ref=organization_ref,
                    farm_id=row.farm_id,
                    plot_id=row.plot_id,
                )
            )

        return organization_refs, farm_scopes, plot_scopes
