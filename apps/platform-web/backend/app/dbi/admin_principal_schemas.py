"""Contratos de consulta autorizada de principales DBI."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_WILDCARD_REFS = frozenset({"all", "any"})


class _DBIAdminPrincipalModel(BaseModel):
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


class DBIAdminPrincipalLookupQuery(_DBIAdminPrincipalModel):
    organization_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("organization_refs")
    @classmethod
    def validate_organizations(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = tuple(_validated_ref(value) for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("organization_refs no admite duplicados.")
        return normalized

    @property
    def organization_set(self) -> frozenset[str]:
        return frozenset(self.organization_refs)


class DBIAdminPrincipalReadResponse(_DBIAdminPrincipalModel):
    principal_id: UUID
    legacy_identity_ref: str
    active: bool
    created_at: datetime
    updated_at: datetime
