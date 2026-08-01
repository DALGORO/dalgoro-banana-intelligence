"""Política pura para administración funcional y cerrada por defecto en DBI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.dbi.authorization import DBIFarmScope, DBIPermission, DBIPlotScope

ADMIN_DENIED_MESSAGE = "Administración DBI denegada."
ADMIN_CONFLICT_MESSAGE = "La operación administrativa DBI entra en conflicto."
_WILDCARD_REFS = frozenset({"all", "any"})


class DBIAdminDenied(PermissionError):
    """Denegación uniforme sin revelar la autoridad o el ámbito que falló."""

    def __init__(self) -> None:
        super().__init__(ADMIN_DENIED_MESSAGE)


class DBIAdminConflict(RuntimeError):
    """Conflicto administrativo que requiere releer el estado persistido."""

    def __init__(self) -> None:
        super().__init__(ADMIN_CONFLICT_MESSAGE)


def _validated_ref(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("La referencia administrativa debe ser texto.")

    normalized = value.strip()
    if (
        not normalized
        or "*" in normalized
        or normalized.casefold() in _WILDCARD_REFS
    ):
        raise ValueError(
            "La referencia administrativa no admite valores vacíos o comodines."
        )
    return normalized


@dataclass(frozen=True, slots=True)
class DBIAdminAuthoritySnapshot:
    """Autoridad persistida explícita de una membresía administrativa.

    ``organization_scopes`` conserva únicamente ámbitos de organización
    explícitos. Los ámbitos padre derivados de una finca o lote no se convierten
    automáticamente en autoridad administrativa de toda la organización.
    """

    principal_ref: str
    tenant_ref: str
    principal_active: bool
    membership_active: bool
    permissions: frozenset[DBIPermission] = frozenset()
    organization_scopes: frozenset[str] = frozenset()
    farm_scopes: frozenset[DBIFarmScope] = frozenset()
    plot_scopes: frozenset[DBIPlotScope] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "principal_ref", _validated_ref(self.principal_ref))
        object.__setattr__(self, "tenant_ref", _validated_ref(self.tenant_ref))

        if not isinstance(self.principal_active, bool):
            raise TypeError("principal_active debe ser booleano.")
        if not isinstance(self.membership_active, bool):
            raise TypeError("membership_active debe ser booleano.")

        permissions = frozenset(self.permissions)
        organization_scopes = frozenset(
            _validated_ref(value) for value in self.organization_scopes
        )
        farm_scopes = frozenset(self.farm_scopes)
        plot_scopes = frozenset(self.plot_scopes)

        if not all(
            isinstance(permission, DBIPermission) for permission in permissions
        ):
            raise TypeError("permissions solo admite DBIPermission.")
        if not all(isinstance(scope, DBIFarmScope) for scope in farm_scopes):
            raise TypeError("farm_scopes solo admite DBIFarmScope.")
        if not all(isinstance(scope, DBIPlotScope) for scope in plot_scopes):
            raise TypeError("plot_scopes solo admite DBIPlotScope.")

        for plot_scope in plot_scopes:
            parent = DBIFarmScope(
                organization_ref=plot_scope.organization_ref,
                farm_id=plot_scope.farm_id,
            )
            if parent not in farm_scopes:
                raise ValueError(
                    "Todo ámbito de lote debe incluir su ámbito de finca padre."
                )

        object.__setattr__(self, "permissions", permissions)
        object.__setattr__(self, "organization_scopes", organization_scopes)
        object.__setattr__(self, "farm_scopes", farm_scopes)
        object.__setattr__(self, "plot_scopes", plot_scopes)

    @property
    def all_organization_refs(self) -> frozenset[str]:
        """Devuelve todas las organizaciones mencionadas por cualquier ámbito."""

        return frozenset(
            set(self.organization_scopes)
            | {scope.organization_ref for scope in self.farm_scopes}
            | {scope.organization_ref for scope in self.plot_scopes}
        )

    @property
    def effective_admin_organizations(self) -> frozenset[str]:
        """Organizaciones administrables de forma explícita y efectiva."""

        if (
            not self.principal_active
            or not self.membership_active
            or DBIPermission.MANAGE not in self.permissions
        ):
            return frozenset()
        return self.organization_scopes


class DBIAdminPolicy:
    """Valida autoridad administrativa sin efectos laterales."""

    @staticmethod
    def _require_snapshot(value: object) -> DBIAdminAuthoritySnapshot:
        if not isinstance(value, DBIAdminAuthoritySnapshot):
            raise DBIAdminDenied()
        return value

    @classmethod
    def require_organization_control(
        cls,
        actor: DBIAdminAuthoritySnapshot,
        *,
        tenant_ref: str,
        organization_refs: frozenset[str],
    ) -> None:
        """Exige ``manage`` y ámbitos de organización explícitos completos."""

        actor = cls._require_snapshot(actor)
        try:
            normalized_tenant = _validated_ref(tenant_ref)
            normalized_organizations = frozenset(
                _validated_ref(value) for value in organization_refs
            )
        except (TypeError, ValueError) as error:
            raise DBIAdminDenied() from error

        if (
            normalized_tenant != actor.tenant_ref
            or not normalized_organizations
            or not normalized_organizations.issubset(
                actor.effective_admin_organizations
            )
        ):
            raise DBIAdminDenied()

    @classmethod
    def require_principal_registration(
        cls,
        actor: DBIAdminAuthoritySnapshot,
        *,
        target_principal_ref: str,
        tenant_ref: str,
        organization_refs: frozenset[str],
    ) -> None:
        """Autoriza registrar una identidad sin mutar su estado global."""

        cls.require_organization_control(
            actor,
            tenant_ref=tenant_ref,
            organization_refs=organization_refs,
        )
        try:
            normalized_target = _validated_ref(target_principal_ref)
        except (TypeError, ValueError) as error:
            raise DBIAdminDenied() from error

        if actor.principal_ref == normalized_target:
            raise DBIAdminDenied()

    @classmethod
    def require_membership_create(
        cls,
        actor: DBIAdminAuthoritySnapshot,
        requested: DBIAdminAuthoritySnapshot,
    ) -> None:
        """Exige que toda autoridad nueva sea subconjunto de la del actor."""

        actor = cls._require_snapshot(actor)
        requested = cls._require_snapshot(requested)
        cls.require_organization_control(
            actor,
            tenant_ref=requested.tenant_ref,
            organization_refs=requested.all_organization_refs,
        )
        cls._require_requested_subset(actor, requested)

        if (
            actor.principal_ref == requested.principal_ref
            or not requested.principal_active
            or not requested.membership_active
        ):
            raise DBIAdminDenied()

    @classmethod
    def require_membership_change(
        cls,
        actor: DBIAdminAuthoritySnapshot,
        before: DBIAdminAuthoritySnapshot,
        after: DBIAdminAuthoritySnapshot,
    ) -> None:
        """Valida una mutación completa y bloquea cambios fuera de cobertura."""

        actor = cls._require_snapshot(actor)
        before = cls._require_snapshot(before)
        after = cls._require_snapshot(after)

        if (
            before.principal_ref != after.principal_ref
            or before.tenant_ref != after.tenant_ref
            or before.principal_active != after.principal_active
        ):
            raise DBIAdminConflict()

        affected_organizations = frozenset(
            set(before.all_organization_refs) | set(after.all_organization_refs)
        )
        cls.require_organization_control(
            actor,
            tenant_ref=before.tenant_ref,
            organization_refs=affected_organizations,
        )
        cls._require_requested_subset(actor, after)

        if actor.principal_ref == before.principal_ref:
            cls._require_self_reduction(before, after)

    @staticmethod
    def _require_requested_subset(
        actor: DBIAdminAuthoritySnapshot,
        requested: DBIAdminAuthoritySnapshot,
    ) -> None:
        if (
            not requested.permissions.issubset(actor.permissions)
            or not requested.all_organization_refs.issubset(
                actor.effective_admin_organizations
            )
        ):
            raise DBIAdminDenied()

    @staticmethod
    def _require_self_reduction(
        before: DBIAdminAuthoritySnapshot,
        after: DBIAdminAuthoritySnapshot,
    ) -> None:
        """Permite a un actor reducir, pero nunca ampliar, su propia autoridad."""

        if (
            not after.permissions.issubset(before.permissions)
            or not after.organization_scopes.issubset(
                before.organization_scopes
            )
            or not after.farm_scopes.issubset(before.farm_scopes)
            or not after.plot_scopes.issubset(before.plot_scopes)
            or (not before.membership_active and after.membership_active)
        ):
            raise DBIAdminDenied()

    @classmethod
    def organizations_losing_last_admin_protection(
        cls,
        before: DBIAdminAuthoritySnapshot,
        after: DBIAdminAuthoritySnapshot,
    ) -> frozenset[str]:
        """Identifica organizaciones donde el objetivo deja de ser administrador."""

        before = cls._require_snapshot(before)
        after = cls._require_snapshot(after)
        if (
            before.principal_ref != after.principal_ref
            or before.tenant_ref != after.tenant_ref
            or before.principal_active != after.principal_active
        ):
            raise DBIAdminConflict()
        return frozenset(
            before.effective_admin_organizations
            - after.effective_admin_organizations
        )

    @staticmethod
    def require_remaining_administrators(
        organization_refs: frozenset[str],
        remaining_counts: Mapping[str, int],
    ) -> None:
        """Exige al menos otro administrador válido por organización afectada."""

        try:
            normalized_organizations = frozenset(
                _validated_ref(value) for value in organization_refs
            )
        except (TypeError, ValueError) as error:
            raise DBIAdminConflict() from error

        for organization_ref in normalized_organizations:
            count = remaining_counts.get(organization_ref)
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                raise DBIAdminConflict()
