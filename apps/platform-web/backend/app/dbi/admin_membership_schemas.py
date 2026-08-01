"""Contratos de consulta y estado para membresías administrativas DBI."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dbi.admin_policy import DBIAdminMembershipStatus
from app.dbi.admin_schemas import DBIAdminFarmScopeInput, DBIAdminPlotScopeInput
from app.dbi.authorization import DBIPermission

_WILDCARD_REFS = frozenset({"all", "any"})


class _DBIAdminMembershipModel(BaseModel):
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


class DBIAdminMembershipStatusRequest(_DBIAdminMembershipModel):
    expected_updated_at: datetime
    correlation_ref: str = Field(min_length=1, max_length=128)

    @field_validator("expected_updated_at")
    @classmethod
    def validate_expected_updated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expected_updated_at debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @field_validator("correlation_ref")
    @classmethod
    def validate_correlation_ref(cls, value: str) -> str:
        return _validated_ref(value)


class DBIAdminMembershipReadResponse(_DBIAdminMembershipModel):
    membership_id: UUID
    principal_id: UUID
    principal_ref: str
    tenant_ref: str
    principal_active: bool
    status: DBIAdminMembershipStatus
    permissions: tuple[DBIPermission, ...]
    organization_scopes: tuple[str, ...]
    farm_scopes: tuple[DBIAdminFarmScopeInput, ...]
    plot_scopes: tuple[DBIAdminPlotScopeInput, ...]
    principal_updated_at: datetime
    membership_updated_at: datetime
