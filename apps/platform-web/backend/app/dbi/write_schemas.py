"""Contratos estrictos para escrituras agrícolas DBI autorizadas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _WriteModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _reject_explicit_nulls(model: BaseModel, field_names: frozenset[str]) -> None:
    for field_name in field_names:
        if field_name in model.model_fields_set and getattr(model, field_name) is None:
            raise ValueError(f"{field_name} no puede ser null.")


class FarmCreate(_WriteModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    status: str = Field(default="active", pattern="^(active|inactive|archived)$")


class FarmUpdate(_WriteModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    status: str | None = Field(
        default=None,
        pattern="^(active|inactive|archived)$",
    )

    @model_validator(mode="after")
    def require_change(self) -> "FarmUpdate":
        if not self.model_fields_set:
            raise ValueError("Debe indicar al menos un campo para actualizar.")
        _reject_explicit_nulls(self, frozenset({"name", "status"}))
        return self


class PlotCreate(_WriteModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    area_hectares: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    status: str = Field(default="active", pattern="^(active|inactive|archived)$")


class PlotUpdate(_WriteModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    area_hectares: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    status: str | None = Field(
        default=None,
        pattern="^(active|inactive|archived)$",
    )

    @model_validator(mode="after")
    def require_change(self) -> "PlotUpdate":
        if not self.model_fields_set:
            raise ValueError("Debe indicar al menos un campo para actualizar.")
        _reject_explicit_nulls(self, frozenset({"name", "status"}))
        return self


class CampaignCreate(_WriteModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    starts_at: datetime
    ends_at: datetime | None = None
    status: str = Field(
        default="planned",
        pattern="^(planned|active|completed|cancelled)$",
    )

    @model_validator(mode="after")
    def validate_dates(self) -> "CampaignCreate":
        if self.ends_at is not None and self.ends_at < self.starts_at:
            raise ValueError("ends_at no puede ser anterior a starts_at.")
        return self


class CampaignUpdate(_WriteModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    status: str | None = Field(
        default=None,
        pattern="^(planned|active|completed|cancelled)$",
    )

    @model_validator(mode="after")
    def require_change(self) -> "CampaignUpdate":
        if not self.model_fields_set:
            raise ValueError("Debe indicar al menos un campo para actualizar.")
        _reject_explicit_nulls(
            self,
            frozenset({"name", "starts_at", "status"}),
        )
        if (
            self.starts_at is not None
            and "ends_at" in self.model_fields_set
            and self.ends_at is not None
            and self.ends_at < self.starts_at
        ):
            raise ValueError("ends_at no puede ser anterior a starts_at.")
        return self
