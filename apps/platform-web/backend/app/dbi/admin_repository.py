"""Consultas y bloqueos administrativos DBI sobre una sesión recibida."""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

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
        if not isinstance(membership_ids, frozenset) or not membership_ids:
            raise ValueError("membership_ids debe contener al menos un UUID.")
        if not all(isinstance(value, UUID) for value in membership_ids):
            raise TypeError("membership_ids solo admite UUID.")

        ordered_ids = tuple(sorted(membership_ids, key=str))
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
