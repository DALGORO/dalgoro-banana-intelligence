"""Conversión cerrada de filas DBI a estado administrativo inmutable."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from app.dbi.admin_policy import (
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminMembershipStatus,
)
from app.dbi.authorization import DBIFarmScope, DBIPermission, DBIPlotScope
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


def _normalized_timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DBIAdminConflict()
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class DBIAdminPersistedMembershipState:
    """Estado administrativo completo y versiones optimistas de una membresía."""

    principal_id: UUID
    membership_id: UUID
    principal_updated_at: datetime
    membership_updated_at: datetime
    authority: DBIAdminAuthoritySnapshot

    def require_principal_version(self, expected_updated_at: datetime) -> None:
        if self.principal_updated_at != _normalized_timestamp(expected_updated_at):
            raise DBIAdminConflict()

    def require_membership_version(self, expected_updated_at: datetime) -> None:
        if self.membership_updated_at != _normalized_timestamp(expected_updated_at):
            raise DBIAdminConflict()


def build_admin_membership_state(
    *,
    principal: DBIPrincipal,
    membership: DBIMembership,
    permissions: Sequence[DBIMembershipPermission],
    scopes: Sequence[DBIMembershipScope],
) -> DBIAdminPersistedMembershipState:
    """Construye un snapshot inmutable y falla cerrado ante filas divergentes."""

    if not isinstance(principal, DBIPrincipal):
        raise DBIAdminConflict()
    if not isinstance(membership, DBIMembership):
        raise DBIAdminConflict()
    if isinstance(permissions, (str, bytes)) or not isinstance(
        permissions, Sequence
    ):
        raise DBIAdminConflict()
    if isinstance(scopes, (str, bytes)) or not isinstance(scopes, Sequence):
        raise DBIAdminConflict()

    principal_id = _required_uuid(principal.id)
    membership_id = _required_uuid(membership.id)
    if _required_uuid(membership.principal_id) != principal_id:
        raise DBIAdminConflict()

    if principal.status == DBIPrincipalStatus.ACTIVE.value:
        principal_active = True
    elif principal.status == DBIPrincipalStatus.INACTIVE.value:
        principal_active = False
    else:
        raise DBIAdminConflict()

    try:
        membership_status = DBIAdminMembershipStatus(
            DBIMembershipStatus(membership.status).value
        )
    except (TypeError, ValueError) as error:
        raise DBIAdminConflict() from error

    permission_values: set[DBIPermission] = set()
    permission_keys: set[tuple[UUID, str]] = set()
    for row in permissions:
        if not isinstance(row, DBIMembershipPermission):
            raise DBIAdminConflict()
        row_membership_id = _required_uuid(row.membership_id)
        if row_membership_id != membership_id:
            raise DBIAdminConflict()
        try:
            permission = DBIPermission(row.permission)
        except (TypeError, ValueError) as error:
            raise DBIAdminConflict() from error
        key = (row_membership_id, permission.value)
        if key in permission_keys:
            raise DBIAdminConflict()
        permission_keys.add(key)
        permission_values.add(permission)

    organization_scopes: set[str] = set()
    farm_scopes: set[DBIFarmScope] = set()
    plot_scopes: set[DBIPlotScope] = set()
    scope_keys: set[tuple[object, ...]] = set()

    for row in scopes:
        if not isinstance(row, DBIMembershipScope):
            raise DBIAdminConflict()
        row_membership_id = _required_uuid(row.membership_id)
        if row_membership_id != membership_id:
            raise DBIAdminConflict()
        try:
            scope_type = DBIMembershipScopeType(row.scope_type)
        except (TypeError, ValueError) as error:
            raise DBIAdminConflict() from error

        try:
            if scope_type is DBIMembershipScopeType.ORGANIZATION:
                if row.farm_id is not None or row.plot_id is not None:
                    raise DBIAdminConflict()
                key = (scope_type.value, row.organization_ref)
                if key in scope_keys:
                    raise DBIAdminConflict()
                scope_keys.add(key)
                probe = DBIFarmScope(
                    organization_ref=row.organization_ref,
                    farm_id=UUID(int=0),
                )
                organization_scopes.add(probe.organization_ref)
                continue

            farm_id = _required_uuid(row.farm_id)
            farm_scope = DBIFarmScope(
                organization_ref=row.organization_ref,
                farm_id=farm_id,
            )
            if scope_type is DBIMembershipScopeType.FARM:
                if row.plot_id is not None:
                    raise DBIAdminConflict()
                key = (
                    scope_type.value,
                    farm_scope.organization_ref,
                    farm_scope.farm_id,
                )
                if key in scope_keys:
                    raise DBIAdminConflict()
                scope_keys.add(key)
                farm_scopes.add(farm_scope)
                continue

            plot_id = _required_uuid(row.plot_id)
            plot_scope = DBIPlotScope(
                organization_ref=row.organization_ref,
                farm_id=farm_id,
                plot_id=plot_id,
            )
            key = (
                scope_type.value,
                plot_scope.organization_ref,
                plot_scope.farm_id,
                plot_scope.plot_id,
            )
            if key in scope_keys:
                raise DBIAdminConflict()
            scope_keys.add(key)
            plot_scopes.add(plot_scope)
            farm_scopes.add(farm_scope)
        except (TypeError, ValueError) as error:
            raise DBIAdminConflict() from error

    try:
        authority = DBIAdminAuthoritySnapshot(
            principal_ref=principal.legacy_identity_ref,
            tenant_ref=membership.tenant_ref,
            principal_active=principal_active,
            membership_status=membership_status,
            permissions=frozenset(permission_values),
            organization_scopes=frozenset(organization_scopes),
            farm_scopes=frozenset(farm_scopes),
            plot_scopes=frozenset(plot_scopes),
        )
    except (TypeError, ValueError) as error:
        raise DBIAdminConflict() from error

    return DBIAdminPersistedMembershipState(
        principal_id=principal_id,
        membership_id=membership_id,
        principal_updated_at=_normalized_timestamp(principal.updated_at),
        membership_updated_at=_normalized_timestamp(membership.updated_at),
        authority=authority,
    )
