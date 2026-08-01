"""Consultas y bloqueos administrativos DBI sobre una sesión recibida."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from hashlib import sha256
from types import MappingProxyType
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.dbi.admin_policy import DBIAdminConflict
from app.dbi.admin_state import (
    DBIAdminLockedMembershipStates,
    build_admin_membership_state,
)
from app.dbi.authorization import DBIFarmScope, DBIPlotScope
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

_ADMIN_LOCK_NAMESPACE = "dalgoro:dbi:admin:organization:v1"
_WILDCARD_REFS = frozenset({"all", "any"})


def _validated_ref(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} debe ser texto.")

    normalized = value.strip()
    if (
        not normalized
        or "*" in normalized
        or normalized.casefold() in _WILDCARD_REFS
    ):
        raise ValueError(
            f"{field_name} no admite valores vacíos o comodines."
        )
    return normalized


def _validated_organization_refs(
    values: frozenset[str],
) -> tuple[str, ...]:
    if not isinstance(values, frozenset):
        raise TypeError("organization_refs debe ser frozenset.")

    normalized = tuple(
        sorted(
            _validated_ref(value, field_name="organization_ref")
            for value in values
        )
    )
    if not normalized:
        raise ValueError("organization_refs no puede estar vacío.")
    return normalized


def _validated_membership_ids(
    values: frozenset[UUID],
) -> tuple[UUID, ...]:
    if not isinstance(values, frozenset) or not values:
        raise ValueError("membership_ids debe contener al menos un UUID.")
    if not all(isinstance(value, UUID) for value in values):
        raise TypeError("membership_ids solo admite UUID.")
    return tuple(sorted(values, key=str))


def organization_advisory_lock_key(
    *,
    tenant_ref: str,
    organization_ref: str,
) -> int:
    """Deriva una clave advisory firmada y estable por tenant/organización."""

    normalized_tenant = _validated_ref(tenant_ref, field_name="tenant_ref")
    normalized_organization = _validated_ref(
        organization_ref,
        field_name="organization_ref",
    )
    material = (
        f"{_ADMIN_LOCK_NAMESPACE}\0{normalized_tenant}"
        f"\0{normalized_organization}"
    ).encode("utf-8")
    key = int.from_bytes(sha256(material).digest()[:8], "big", signed=True)
    return key if key != 0 else 1


class DBIAdminRepository:
    """Repositorio administrativo sin frontera transaccional propia."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _all(
        self,
        statement: Select,
    ) -> tuple[object, ...]:
        return tuple(self._session.execute(statement).scalars().all())

    def add(self, entity: object) -> object:
        """Añade una entidad sin confirmar, revertir o cerrar la transacción."""

        self._session.add(entity)
        return entity

    def list_principals_by_legacy_ref(
        self,
        *,
        legacy_identity_ref: str,
        for_update: bool = False,
    ) -> tuple[DBIPrincipal, ...]:
        """Busca candidatos globales y opcionalmente bloquea sus filas."""

        normalized_ref = _validated_ref(
            legacy_identity_ref,
            field_name="legacy_identity_ref",
        )
        statement = select(DBIPrincipal).where(
            DBIPrincipal.legacy_identity_ref == normalized_ref
        )
        if for_update:
            statement = statement.with_for_update()
        return self._all(statement)  # type: ignore[return-value]

    def list_memberships(
        self,
        *,
        principal_id: UUID,
        tenant_ref: str,
        for_update: bool = False,
    ) -> tuple[DBIMembership, ...]:
        """Busca membresías exactas de un principal dentro de un tenant."""

        if not isinstance(principal_id, UUID):
            raise TypeError("principal_id debe ser UUID.")
        normalized_tenant = _validated_ref(
            tenant_ref,
            field_name="tenant_ref",
        )
        statement = select(DBIMembership).where(
            DBIMembership.principal_id == principal_id,
            DBIMembership.tenant_ref == normalized_tenant,
        )
        if for_update:
            statement = statement.with_for_update()
        return self._all(statement)  # type: ignore[return-value]

    def lock_memberships(
        self,
        *,
        tenant_ref: str,
        membership_ids: frozenset[UUID],
    ) -> tuple[DBIMembership, ...]:
        """Bloquea membresías del tenant en orden estable para evitar deadlocks."""

        normalized_tenant = _validated_ref(
            tenant_ref,
            field_name="tenant_ref",
        )
        ordered_ids = _validated_membership_ids(membership_ids)
        statement = (
            select(DBIMembership)
            .where(
                DBIMembership.tenant_ref == normalized_tenant,
                DBIMembership.id.in_(ordered_ids),
            )
            .order_by(DBIMembership.id)
            .with_for_update()
        )
        return self._all(statement)  # type: ignore[return-value]

    def list_permissions(
        self,
        *,
        membership_id: UUID,
    ) -> tuple[DBIMembershipPermission, ...]:
        if not isinstance(membership_id, UUID):
            raise TypeError("membership_id debe ser UUID.")
        return self._all(
            select(DBIMembershipPermission).where(
                DBIMembershipPermission.membership_id == membership_id
            )
        )  # type: ignore[return-value]

    def list_scopes(
        self,
        *,
        membership_id: UUID,
    ) -> tuple[DBIMembershipScope, ...]:
        if not isinstance(membership_id, UUID):
            raise TypeError("membership_id debe ser UUID.")
        return self._all(
            select(DBIMembershipScope).where(
                DBIMembershipScope.membership_id == membership_id
            )
        )  # type: ignore[return-value]

    def scope_hierarchy_matches(
        self,
        *,
        farm_scopes: frozenset[DBIFarmScope],
        plot_scopes: frozenset[DBIPlotScope],
    ) -> bool:
        """Comprueba que cada finca y lote pertenezca a su jerarquía declarada."""

        if not isinstance(farm_scopes, frozenset) or not all(
            isinstance(scope, DBIFarmScope) for scope in farm_scopes
        ):
            raise TypeError("farm_scopes debe ser frozenset de DBIFarmScope.")
        if not isinstance(plot_scopes, frozenset) or not all(
            isinstance(scope, DBIPlotScope) for scope in plot_scopes
        ):
            raise TypeError("plot_scopes debe ser frozenset de DBIPlotScope.")

        expected_farms = {
            (scope.farm_id, scope.organization_ref) for scope in farm_scopes
        }
        if expected_farms:
            farm_ids = tuple(sorted({item[0] for item in expected_farms}, key=str))
            farm_rows: Sequence[tuple[UUID, str]] = self._session.execute(
                select(Farm.id, Farm.organization_ref).where(
                    Farm.id.in_(farm_ids)
                )
            ).all()
            if set(farm_rows) != expected_farms:
                return False

        expected_plots = {
            (scope.plot_id, scope.farm_id, scope.organization_ref)
            for scope in plot_scopes
        }
        if expected_plots:
            plot_ids = tuple(sorted({item[0] for item in expected_plots}, key=str))
            plot_rows: Sequence[tuple[UUID, UUID, str]] = self._session.execute(
                select(Plot.id, Plot.farm_id, Farm.organization_ref)
                .join(Farm, Plot.farm_id == Farm.id)
                .where(Plot.id.in_(plot_ids))
            ).all()
            if set(plot_rows) != expected_plots:
                return False

        return True

    def lock_organization_authority(
        self,
        *,
        tenant_ref: str,
        organization_refs: frozenset[str],
    ) -> tuple[int, ...]:
        """Adquiere locks transaccionales ordenados para autoridad organizacional."""

        normalized_tenant = _validated_ref(
            tenant_ref,
            field_name="tenant_ref",
        )
        organizations = _validated_organization_refs(organization_refs)
        keys = tuple(
            organization_advisory_lock_key(
                tenant_ref=normalized_tenant,
                organization_ref=organization_ref,
            )
            for organization_ref in organizations
        )
        for key in keys:
            self._session.execute(select(func.pg_advisory_xact_lock(key)))
        return keys

    def lock_and_load_membership_states(
        self,
        *,
        tenant_ref: str,
        organization_refs: frozenset[str],
        membership_ids: frozenset[UUID],
    ) -> DBIAdminLockedMembershipStates:
        """Serializa por membresía y carga su agregado administrativo exacto.

        La membresía es la raíz mutable: toda sustitución de permisos o ámbitos
        debe adquirir primero este mismo bloqueo. El principal global es de solo
        lectura en esta frontera y los hijos se leen después de bloquear su raíz,
        evitando exigir privilegios UPDATE sobre tablas que no se actualizan.
        """

        normalized_tenant = _validated_ref(
            tenant_ref,
            field_name="tenant_ref",
        )
        ordered_membership_ids = _validated_membership_ids(membership_ids)
        expected_membership_ids = frozenset(ordered_membership_ids)

        lock_keys = self.lock_organization_authority(
            tenant_ref=normalized_tenant,
            organization_refs=organization_refs,
        )
        memberships = self.lock_memberships(
            tenant_ref=normalized_tenant,
            membership_ids=expected_membership_ids,
        )
        if (
            not all(isinstance(row, DBIMembership) for row in memberships)
            or frozenset(row.id for row in memberships)
            != expected_membership_ids
        ):
            raise DBIAdminConflict()

        principal_ids = frozenset(row.principal_id for row in memberships)
        if not principal_ids or not all(
            isinstance(value, UUID) for value in principal_ids
        ):
            raise DBIAdminConflict()
        ordered_principal_ids = tuple(sorted(principal_ids, key=str))
        principals = self._all(
            select(DBIPrincipal)
            .where(DBIPrincipal.id.in_(ordered_principal_ids))
            .order_by(DBIPrincipal.id)
        )
        if (
            not all(isinstance(row, DBIPrincipal) for row in principals)
            or frozenset(row.id for row in principals) != principal_ids
        ):
            raise DBIAdminConflict()

        permissions = self._all(
            select(DBIMembershipPermission)
            .where(
                DBIMembershipPermission.membership_id.in_(
                    ordered_membership_ids
                )
            )
            .order_by(
                DBIMembershipPermission.membership_id,
                DBIMembershipPermission.permission,
            )
        )
        scopes = self._all(
            select(DBIMembershipScope)
            .where(
                DBIMembershipScope.membership_id.in_(
                    ordered_membership_ids
                )
            )
            .order_by(
                DBIMembershipScope.membership_id,
                DBIMembershipScope.id,
            )
        )
        if not all(
            isinstance(row, DBIMembershipPermission) for row in permissions
        ) or not all(isinstance(row, DBIMembershipScope) for row in scopes):
            raise DBIAdminConflict()

        principal_by_id = {row.id: row for row in principals}
        permissions_by_membership: dict[
            UUID,
            list[DBIMembershipPermission],
        ] = defaultdict(list)
        for row in permissions:
            permissions_by_membership[row.membership_id].append(row)

        scopes_by_membership: dict[
            UUID,
            list[DBIMembershipScope],
        ] = defaultdict(list)
        for row in scopes:
            scopes_by_membership[row.membership_id].append(row)

        states = {}
        for membership in memberships:
            principal = principal_by_id.get(membership.principal_id)
            if not isinstance(principal, DBIPrincipal):
                raise DBIAdminConflict()
            state = build_admin_membership_state(
                principal=principal,
                membership=membership,
                permissions=tuple(
                    permissions_by_membership.get(membership.id, ())
                ),
                scopes=tuple(scopes_by_membership.get(membership.id, ())),
            )
            states[membership.id] = state

        if frozenset(states) != expected_membership_ids:
            raise DBIAdminConflict()
        return DBIAdminLockedMembershipStates(
            lock_keys=lock_keys,
            states=MappingProxyType(states),
        )

    def count_remaining_administrators(
        self,
        *,
        tenant_ref: str,
        organization_refs: frozenset[str],
        excluded_membership_id: UUID,
    ) -> dict[str, int]:
        """Cuenta otros administradores activos por organización explícita."""

        normalized_tenant = _validated_ref(
            tenant_ref,
            field_name="tenant_ref",
        )
        organizations = _validated_organization_refs(organization_refs)
        if not isinstance(excluded_membership_id, UUID):
            raise TypeError("excluded_membership_id debe ser UUID.")

        statement = (
            select(
                DBIMembershipScope.organization_ref,
                func.count(func.distinct(DBIMembership.id)),
            )
            .select_from(DBIMembershipScope)
            .join(
                DBIMembership,
                DBIMembershipScope.membership_id == DBIMembership.id,
            )
            .join(
                DBIPrincipal,
                DBIMembership.principal_id == DBIPrincipal.id,
            )
            .join(
                DBIMembershipPermission,
                DBIMembershipPermission.membership_id == DBIMembership.id,
            )
            .where(
                DBIMembership.tenant_ref == normalized_tenant,
                DBIMembership.status == DBIMembershipStatus.ACTIVE.value,
                DBIPrincipal.status == DBIPrincipalStatus.ACTIVE.value,
                DBIMembershipPermission.permission == "manage",
                DBIMembershipScope.scope_type
                == DBIMembershipScopeType.ORGANIZATION.value,
                DBIMembershipScope.organization_ref.in_(organizations),
                DBIMembership.id != excluded_membership_id,
            )
            .group_by(DBIMembershipScope.organization_ref)
        )
        rows: Sequence[tuple[str, int]] = self._session.execute(statement).all()
        counts = {organization_ref: 0 for organization_ref in organizations}
        for organization_ref, count in rows:
            if organization_ref in counts:
                counts[organization_ref] = int(count)
        return counts
