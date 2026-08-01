"""Contratos HTTP estrictos para la administración funcional DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.dbi.admin_policy import (
    DBIAdminAuthoritySnapshot,
    DBIAdminMembershipStatus,
)
from app.dbi.authorization import DBIFarmScope, DBIPermission, DBIPlotScope

_WILDCARD_REFS = frozenset({"all", "any"})


class _DBIAdminModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _validated_ref(value: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or "*" in normalized
        or normalized.casefold() in _WILDCARD_REFS
    ):
        raise ValueError("La referencia no admite valores vacíos o comodines.")
    return normalized


def _unique(values: tuple[object, ...], *, field_name: str) -> tuple[object, ...]:
    seen: list[object] = []
    for value in values:
        if value in seen:
            raise ValueError(f"{field_name} no admite duplicados.")
        seen.append(value)
    return values


def _utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("La fecha debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


class DBIAdminFarmScopeInput(_DBIAdminModel):
    organization_ref: str = Field(min_length=1, max_length=255)
    farm_id: UUID

    @field_validator("organization_ref")
    @classmethod
    def validate_organization_ref(cls, value: str) -> str:
        return _validated_ref(value)

    def to_domain(self) -> DBIFarmScope:
        return DBIFarmScope(
            organization_ref=self.organization_ref,
            farm_id=self.farm_id,
        )


class DBIAdminPlotScopeInput(_DBIAdminModel):
    organization_ref: str = Field(min_length=1, max_length=255)
    farm_id: UUID
    plot_id: UUID

    @field_validator("organization_ref")
    @classmethod
    def validate_organization_ref(cls, value: str) -> str:
        return _validated_ref(value)

    def to_domain(self) -> DBIPlotScope:
        return DBIPlotScope(
            organization_ref=self.organization_ref,
            farm_id=self.farm_id,
            plot_id=self.plot_id,
        )


class DBIAdminAuthorityInput(_DBIAdminModel):
    """Autoridad completa solicitada sin estados globales controlables."""

    permissions: tuple[DBIPermission, ...] = Field(min_length=1)
    organization_scopes: tuple[str, ...] = ()
    farm_scopes: tuple[DBIAdminFarmScopeInput, ...] = ()
    plot_scopes: tuple[DBIAdminPlotScopeInput, ...] = ()

    @field_validator("organization_scopes")
    @classmethod
    def validate_organization_scopes(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = tuple(_validated_ref(value) for value in values)
        return _unique(
            normalized,
            field_name="organization_scopes",
        )  # type: ignore[return-value]

    @model_validator(mode="after")
    def validate_authority(self) -> "DBIAdminAuthorityInput":
        _unique(self.permissions, field_name="permissions")
        _unique(self.farm_scopes, field_name="farm_scopes")
        _unique(self.plot_scopes, field_name="plot_scopes")
        if not (
            self.organization_scopes
            or self.farm_scopes
            or self.plot_scopes
        ):
            raise ValueError("Debe declarar al menos un ámbito DBI explícito.")
        return self

    @property
    def permission_set(self) -> frozenset[DBIPermission]:
        return frozenset(self.permissions)

    @property
    def organization_set(self) -> frozenset[str]:
        return frozenset(self.organization_scopes)

    @property
    def farm_set(self) -> frozenset[DBIFarmScope]:
        return frozenset(scope.to_domain() for scope in self.farm_scopes)

    @property
    def plot_set(self) -> frozenset[DBIPlotScope]:
        return frozenset(scope.to_domain() for scope in self.plot_scopes)


class DBIAdminPrincipalRegistrationRequest(_DBIAdminModel):
    principal_id: UUID
    legacy_identity_ref: str = Field(min_length=1, max_length=255)
    organization_refs: tuple[str, ...] = Field(min_length=1)
    correlation_ref: str = Field(min_length=1, max_length=128)

    @field_validator("legacy_identity_ref", "correlation_ref")
    @classmethod
    def validate_refs(cls, value: str) -> str:
        return _validated_ref(value)

    @field_validator("organization_refs")
    @classmethod
    def validate_organizations(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = tuple(_validated_ref(value) for value in values)
        return _unique(
            normalized,
            field_name="organization_refs",
        )  # type: ignore[return-value]

    @property
    def organization_set(self) -> frozenset[str]:
        return frozenset(self.organization_refs)


class DBIAdminMembershipCreationRequest(DBIAdminAuthorityInput):
    membership_id: UUID
    principal_id: UUID
    principal_ref: str = Field(min_length=1, max_length=255)
    correlation_ref: str = Field(min_length=1, max_length=128)

    @field_validator("principal_ref", "correlation_ref")
    @classmethod
    def validate_refs(cls, value: str) -> str:
        return _validated_ref(value)

    def to_authority_snapshot(
        self,
        *,
        tenant_ref: str,
    ) -> DBIAdminAuthoritySnapshot:
        return DBIAdminAuthoritySnapshot(
            principal_ref=self.principal_ref,
            tenant_ref=_validated_ref(tenant_ref),
            principal_active=True,
            membership_status=DBIAdminMembershipStatus.ACTIVE,
            permissions=self.permission_set,
            organization_scopes=self.organization_set,
            farm_scopes=self.farm_set,
            plot_scopes=self.plot_set,
        )


class DBIAdminMembershipMutationRequest(DBIAdminAuthorityInput):
    expected_updated_at: datetime
    status: DBIAdminMembershipStatus
    correlation_ref: str = Field(min_length=1, max_length=128)

    @field_validator("expected_updated_at")
    @classmethod
    def validate_expected_updated_at(cls, value: datetime) -> datetime:
        return _utc_timestamp(value)

    @field_validator("correlation_ref")
    @classmethod
    def validate_correlation_ref(cls, value: str) -> str:
        return _validated_ref(value)

    def to_authority_snapshot(
        self,
        *,
        before: DBIAdminAuthoritySnapshot,
    ) -> DBIAdminAuthoritySnapshot:
        return DBIAdminAuthoritySnapshot(
            principal_ref=before.principal_ref,
            tenant_ref=before.tenant_ref,
            principal_active=before.principal_active,
            membership_status=self.status,
            permissions=self.permission_set,
            organization_scopes=self.organization_set,
            farm_scopes=self.farm_set,
            plot_scopes=self.plot_set,
        )


class DBIAdminPrincipalRegistrationResponse(_DBIAdminModel):
    principal_id: UUID
    created: bool
    occurred_at: datetime
    correlation_ref: str
    organization_refs: tuple[str, ...]


class DBIAdminMembershipCreationResponse(_DBIAdminModel):
    membership_id: UUID
    principal_id: UUID
    created: bool
    tenant_ref: str
    status: DBIAdminMembershipStatus
    permissions: tuple[DBIPermission, ...]
    organization_scopes: tuple[str, ...]
    farm_scopes: tuple[DBIAdminFarmScopeInput, ...]
    plot_scopes: tuple[DBIAdminPlotScopeInput, ...]
    occurred_at: datetime
    correlation_ref: str


class DBIAdminMembershipMutationResponse(_DBIAdminModel):
    membership_id: UUID
    applied: bool
    updated_at: datetime
    status: DBIAdminMembershipStatus
    permissions: tuple[DBIPermission, ...]
    organization_scopes: tuple[str, ...]
    farm_scopes: tuple[DBIAdminFarmScopeInput, ...]
    plot_scopes: tuple[DBIAdminPlotScopeInput, ...]
    affected_organization_refs: tuple[str, ...]
    correlation_ref: str
