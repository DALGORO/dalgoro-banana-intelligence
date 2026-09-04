"""Asociación pura de observaciones Sampling a UP post-deduplicación."""

from __future__ import annotations

import math
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_EARTH_RADIUS_M = 6_371_008.8


class _AssociationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class DBIUPMatchProfile(_AssociationModel):
    profile_version: str = Field(min_length=1, max_length=64)
    tolerance_m: float = Field(gt=0, le=100, default=12)
    ambiguity_margin_m: float = Field(ge=0, le=50, default=2)

    @field_validator("profile_version")
    @classmethod
    def canonical_version(cls, value: str) -> str:
        if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("profile_version debe ser canónica.")
        return value

    @model_validator(mode="after")
    def validate_margin(self) -> "DBIUPMatchProfile":
        if self.ambiguity_margin_m > self.tolerance_m:
            raise ValueError("ambiguity_margin_m no puede superar tolerance_m.")
        return self


class DBIUPCandidate(_AssociationModel):
    up_id: UUID
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


class DBIUPMatchCandidate(_AssociationModel):
    up_id: UUID
    distance_m: float = Field(ge=0)


class DBIUPAssociation(_AssociationModel):
    profile_version: str
    status: Literal["matched", "ambiguous", "no_match"]
    matched_up_id: UUID | None
    candidates: tuple[DBIUPMatchCandidate, ...]

    @model_validator(mode="after")
    def validate_status(self) -> "DBIUPAssociation":
        if self.status == "matched":
            if self.matched_up_id is None or not self.candidates:
                raise ValueError("matched requiere una UP seleccionada.")
        elif self.matched_up_id is not None:
            raise ValueError("Sólo matched puede exponer matched_up_id.")
        return self


def _distance_m(
    left_lon: float,
    left_lat: float,
    right_lon: float,
    right_lat: float,
) -> float:
    latitude0 = math.radians((left_lat + right_lat) / 2.0)
    dx = (
        math.radians(right_lon - left_lon)
        * _EARTH_RADIUS_M
        * math.cos(latitude0)
    )
    dy = math.radians(right_lat - left_lat) * _EARTH_RADIUS_M
    return math.hypot(dx, dy)


def associate_observation_to_up(
    *,
    observed_longitude: float,
    observed_latitude: float,
    candidates: tuple[DBIUPCandidate, ...],
    profile: DBIUPMatchProfile,
) -> DBIUPAssociation:
    """Resuelve proximidad sin mutar identidad ni coordenada canónica de ninguna UP."""

    if isinstance(observed_longitude, bool) or isinstance(observed_latitude, bool):
        raise ValueError("Las coordenadas observadas deben ser numéricas.")
    observed_longitude = float(observed_longitude)
    observed_latitude = float(observed_latitude)
    if (
        not math.isfinite(observed_longitude)
        or not math.isfinite(observed_latitude)
        or not -180 <= observed_longitude <= 180
        or not -90 <= observed_latitude <= 90
    ):
        raise ValueError("Las coordenadas observadas están fuera de rango.")
    if not isinstance(profile, DBIUPMatchProfile):
        profile = DBIUPMatchProfile.model_validate(profile)

    ranked = sorted(
        (
            DBIUPMatchCandidate(
                up_id=candidate.up_id,
                distance_m=round(
                    _distance_m(
                        observed_longitude,
                        observed_latitude,
                        candidate.longitude,
                        candidate.latitude,
                    ),
                    3,
                ),
            )
            for candidate in candidates
        ),
        key=lambda item: (item.distance_m, str(item.up_id)),
    )
    within = tuple(item for item in ranked if item.distance_m <= profile.tolerance_m)
    if not within:
        return DBIUPAssociation(
            profile_version=profile.profile_version,
            status="no_match",
            matched_up_id=None,
            candidates=(),
        )
    if len(within) == 1:
        return DBIUPAssociation(
            profile_version=profile.profile_version,
            status="matched",
            matched_up_id=within[0].up_id,
            candidates=within,
        )

    nearest, second = within[0], within[1]
    if second.distance_m - nearest.distance_m >= profile.ambiguity_margin_m:
        return DBIUPAssociation(
            profile_version=profile.profile_version,
            status="matched",
            matched_up_id=nearest.up_id,
            candidates=within,
        )
    return DBIUPAssociation(
        profile_version=profile.profile_version,
        status="ambiguous",
        matched_up_id=None,
        candidates=within,
    )
