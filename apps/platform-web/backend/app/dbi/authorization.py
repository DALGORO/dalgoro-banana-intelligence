"""Política pura de autorización para recursos DBI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


DENIED_MESSAGE = "Acceso DBI denegado."
_WILDCARD_REFS = frozenset({"all", "any"})


class DBIPermission(StrEnum):
    """Permisos explícitos reconocidos por la frontera DBI."""

    READ = "read"
    WRITE = "write"
    SUBMIT_ANALYSIS = "submit_analysis"
    APPROVE_AGRONOMIC = "approve_agronomic"
    MANAGE = "manage"


class DBIAccessDenied(PermissionError):
    """Denegación uniforme que no revela el ámbito que falló."""

    def __init__(self) -> None:
        super().__init__(DENIED_MESSAGE)


def _validated_ref(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} debe ser texto.")

    normalized = value.strip()
    if (
        not normalized
        or "*" in normalized
        or normalized.casefold() in _WILDCARD_REFS
    ):
        raise ValueError(f"{field_name} no admite valores vacíos o comodines.")

    return normalized


def _validated_uuid(value: UUID, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} debe ser UUID.")
    return value


@dataclass(frozen=True, slots=True)
class DBIFarmScope:
    """Pertenencia explícita de una finca dentro de una organización."""

    organization_ref: str
    farm_id: UUID

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "organization_ref",
            _validated_ref(
                self.organization_ref,
                field_name="organization_ref",
            ),
        )
        _validated_uuid(self.farm_id, field_name="farm_id")


@dataclass(frozen=True, slots=True)
class DBIPlotScope:
    """Pertenencia explícita de un lote dentro de una finca."""

    organization_ref: str
    farm_id: UUID
    plot_id: UUID

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "organization_ref",
            _validated_ref(
                self.organization_ref,
                field_name="organization_ref",
            ),
        )
        _validated_uuid(self.farm_id, field_name="farm_id")
        _validated_uuid(self.plot_id, field_name="plot_id")


@dataclass(frozen=True, slots=True)
class DBIAccessContext:
    """Identidad y ámbitos ya resueltos por una futura capa confiable."""

    principal_ref: str
    tenant_ref: str
    organization_refs: frozenset[str] = frozenset()
    farm_scopes: frozenset[DBIFarmScope] = frozenset()
    plot_scopes: frozenset[DBIPlotScope] = frozenset()
    permissions: frozenset[DBIPermission] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "principal_ref",
            _validated_ref(self.principal_ref, field_name="principal_ref"),
        )
        object.__setattr__(
            self,
            "tenant_ref",
            _validated_ref(self.tenant_ref, field_name="tenant_ref"),
        )

        organization_refs = frozenset(
            _validated_ref(value, field_name="organization_ref")
            for value in self.organization_refs
        )
        farm_scopes = frozenset(self.farm_scopes)
        plot_scopes = frozenset(self.plot_scopes)
        permissions = frozenset(self.permissions)

        if not all(isinstance(scope, DBIFarmScope) for scope in farm_scopes):
            raise TypeError("farm_scopes solo admite DBIFarmScope.")
        if not all(isinstance(scope, DBIPlotScope) for scope in plot_scopes):
            raise TypeError("plot_scopes solo admite DBIPlotScope.")
        if not all(
            isinstance(permission, DBIPermission)
            for permission in permissions
        ):
            raise TypeError("permissions solo admite DBIPermission.")

        for farm_scope in farm_scopes:
            if farm_scope.organization_ref not in organization_refs:
                raise ValueError(
                    "Toda finca debe pertenecer a una organización autorizada."
                )

        for plot_scope in plot_scopes:
            parent = DBIFarmScope(
                organization_ref=plot_scope.organization_ref,
                farm_id=plot_scope.farm_id,
            )
            if parent not in farm_scopes:
                raise ValueError(
                    "Todo lote debe pertenecer a una finca autorizada."
                )

        object.__setattr__(self, "organization_refs", organization_refs)
        object.__setattr__(self, "farm_scopes", farm_scopes)
        object.__setattr__(self, "plot_scopes", plot_scopes)
        object.__setattr__(self, "permissions", permissions)


class DBIAuthorizationPolicy:
    """Valida permiso y pertenencia exacta con denegación por defecto."""

    @staticmethod
    def _require_base(
        context: DBIAccessContext,
        *,
        tenant_ref: str,
        permission: DBIPermission,
    ) -> None:
        if (
            not isinstance(context, DBIAccessContext)
            or not isinstance(permission, DBIPermission)
        ):
            raise DBIAccessDenied()

        try:
            normalized_tenant = _validated_ref(
                tenant_ref,
                field_name="tenant_ref",
            )
        except (TypeError, ValueError) as error:
            raise DBIAccessDenied() from error

        if (
            normalized_tenant != context.tenant_ref
            or permission not in context.permissions
        ):
            raise DBIAccessDenied()

    @classmethod
    def require_tenant(
        cls,
        context: DBIAccessContext,
        *,
        tenant_ref: str,
        permission: DBIPermission,
    ) -> None:
        """Exige permiso y coincidencia exacta de tenant."""

        cls._require_base(
            context,
            tenant_ref=tenant_ref,
            permission=permission,
        )

    @classmethod
    def require_organization(
        cls,
        context: DBIAccessContext,
        *,
        tenant_ref: str,
        organization_ref: str,
        permission: DBIPermission,
    ) -> None:
        """Exige tenant, permiso y organización explícitos."""

        cls._require_base(
            context,
            tenant_ref=tenant_ref,
            permission=permission,
        )
        try:
            normalized_organization = _validated_ref(
                organization_ref,
                field_name="organization_ref",
            )
        except (TypeError, ValueError) as error:
            raise DBIAccessDenied() from error

        if normalized_organization not in context.organization_refs:
            raise DBIAccessDenied()

    @classmethod
    def require_farm(
        cls,
        context: DBIAccessContext,
        *,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        permission: DBIPermission,
    ) -> None:
        """Exige tenant, organización y finca completos."""

        cls.require_organization(
            context,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            permission=permission,
        )
        try:
            scope = DBIFarmScope(
                organization_ref=organization_ref,
                farm_id=farm_id,
            )
        except (TypeError, ValueError) as error:
            raise DBIAccessDenied() from error

        if scope not in context.farm_scopes:
            raise DBIAccessDenied()

    @classmethod
    def require_plot(
        cls,
        context: DBIAccessContext,
        *,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        permission: DBIPermission,
    ) -> None:
        """Exige tenant, organización, finca y lote completos."""

        cls.require_farm(
            context,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            permission=permission,
        )
        try:
            scope = DBIPlotScope(
                organization_ref=organization_ref,
                farm_id=farm_id,
                plot_id=plot_id,
            )
        except (TypeError, ValueError) as error:
            raise DBIAccessDenied() from error

        if scope not in context.plot_scopes:
            raise DBIAccessDenied()
