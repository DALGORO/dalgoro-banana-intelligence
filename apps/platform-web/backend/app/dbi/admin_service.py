"""Guardas transaccionales para operaciones administrativas DBI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.dbi.admin_policy import (
    DBIAdminAuthoritySnapshot,
    DBIAdminConflict,
    DBIAdminPolicy,
)


class DBIAdminGuardRepositoryPort(Protocol):
    """Operaciones de bloqueo y conteo requeridas por las guardas."""

    def lock_organization_authority(
        self,
        *,
        tenant_ref: str,
        organization_refs: frozenset[str],
    ) -> tuple[int, ...]: ...

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


def _validated_timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DBIAdminConflict()
    return value


def _require_current_version(
    *,
    expected_updated_at: datetime,
    persisted_updated_at: datetime,
) -> None:
    expected = _validated_timestamp(expected_updated_at)
    persisted = _validated_timestamp(persisted_updated_at)
    if expected != persisted:
        raise DBIAdminConflict()


class DBIAdminService:
    """Coordina política, concurrencia y locks sin aplicar mutaciones.

    Para cambios de membresía, ``actor``, ``before`` y
    ``persisted_updated_at`` deben provenir de las filas ya bloqueadas con
    ``FOR UPDATE`` dentro de la misma transacción. Esta guarda no sustituye el
    bloqueo de filas ni abre una transacción propia.
    """

    def __init__(self, repository: DBIAdminGuardRepositoryPort) -> None:
        self._repository = repository

    def guard_principal_registration(
        self,
        actor: DBIAdminAuthoritySnapshot,
        *,
        target_principal_ref: str,
        tenant_ref: str,
        organization_refs: frozenset[str],
    ) -> DBIAdminGuardEvidence:
        """Autoriza y serializa el registro idempotente de un principal."""

        DBIAdminPolicy.require_principal_registration(
            actor,
            target_principal_ref=target_principal_ref,
            tenant_ref=tenant_ref,
            organization_refs=organization_refs,
        )
        lock_keys = self._repository.lock_organization_authority(
            tenant_ref=tenant_ref,
            organization_refs=organization_refs,
        )
        return DBIAdminGuardEvidence(
            tenant_ref=tenant_ref,
            organization_refs=organization_refs,
            lock_keys=lock_keys,
        )

    def guard_membership_create(
        self,
        actor: DBIAdminAuthoritySnapshot,
        requested: DBIAdminAuthoritySnapshot,
    ) -> DBIAdminGuardEvidence:
        """Autoriza y serializa la creación de una membresía activa."""

        DBIAdminPolicy.require_membership_create(actor, requested)
        organizations = requested.all_organization_refs
        lock_keys = self._repository.lock_organization_authority(
            tenant_ref=requested.tenant_ref,
            organization_refs=organizations,
        )
        return DBIAdminGuardEvidence(
            tenant_ref=requested.tenant_ref,
            organization_refs=organizations,
            lock_keys=lock_keys,
        )

    def guard_membership_change(
        self,
        actor: DBIAdminAuthoritySnapshot,
        before: DBIAdminAuthoritySnapshot,
        after: DBIAdminAuthoritySnapshot,
        *,
        target_membership_id: UUID,
        expected_updated_at: datetime,
        persisted_updated_at: datetime,
    ) -> DBIAdminGuardEvidence:
        """Protege una mutación usando estados ya bloqueados y actuales."""

        if not isinstance(target_membership_id, UUID):
            raise DBIAdminConflict()

        DBIAdminPolicy.require_membership_change(actor, before, after)
        _require_current_version(
            expected_updated_at=expected_updated_at,
            persisted_updated_at=persisted_updated_at,
        )

        organizations = frozenset(
            set(before.all_organization_refs) | set(after.all_organization_refs)
        )
        lock_keys = self._repository.lock_organization_authority(
            tenant_ref=before.tenant_ref,
            organization_refs=organizations,
        )

        protected = DBIAdminPolicy.organizations_losing_last_admin_protection(
            before,
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
            lock_keys=lock_keys,
            protected_organization_refs=protected,
        )
