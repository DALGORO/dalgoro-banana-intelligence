"""Contratos de verdad-terreno para captura de campo DBI.

La observación de campo representa evidencia observada. Los derivados e inferencias
se mantienen fuera de este contrato para evitar convertir una estimación en dato
crudo. Una corrección crea una nueva versión; nunca sobrescribe silenciosamente la
observación original.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DBI_FIELD_OBSERVATION_SCHEMA_VERSION = "dbi-field-observation.v1"

FieldState = Literal["observed", "not_measured", "not_applicable"]
EvidenceKind = Literal["observed"]


class _InspectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class _MissingAwareField(_InspectionModel):
    state: FieldState
    reason: str | None = Field(default=None, min_length=1, max_length=160)

    def _validate_missing_state(self, value: object | None) -> None:
        if self.state == "observed":
            if value is None:
                raise ValueError("Un campo observado requiere valor.")
            if self.reason is not None:
                raise ValueError("Un campo observado no debe declarar razón de ausencia.")
            return
        if value is not None:
            raise ValueError("Un campo no medido/no aplicable debe conservar valor nulo.")
        if not self.reason:
            raise ValueError("Un campo no medido/no aplicable requiere razón explícita.")


class DBIObservedInt(_MissingAwareField):
    value: int | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "DBIObservedInt":
        self._validate_missing_state(self.value)
        return self


class DBIObservedFloat(_MissingAwareField):
    value: float | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "DBIObservedFloat":
        self._validate_missing_state(self.value)
        return self


class DBIObservedBool(_MissingAwareField):
    value: bool | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "DBIObservedBool":
        self._validate_missing_state(self.value)
        return self


class DBIObservedText(_MissingAwareField):
    value: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_state(self) -> "DBIObservedText":
        self._validate_missing_state(self.value)
        return self


class DBIFoureObservation(DBIObservedInt):
    """Escala Fouré completa. Nunca se reemplaza por una agrupación derivada."""

    @model_validator(mode="after")
    def validate_foure(self) -> "DBIFoureObservation":
        if self.state == "observed" and self.value is not None and not 0 <= self.value <= 6:
            raise ValueError("Fouré observado debe estar entre 0 y 6.")
        return self


class DBILeafCountObservation(DBIObservedInt):
    @model_validator(mode="after")
    def validate_leaf_count(self) -> "DBILeafCountObservation":
        if self.state == "observed" and self.value is not None and not 0 <= self.value <= 60:
            raise ValueError("El conteo foliar observado debe estar entre 0 y 60.")
        return self


class DBIGPSFix(_InspectionModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    accuracy_m: float = Field(ge=0, le=10_000)
    captured_at: datetime


class DBIPhotoEvidence(_MissingAwareField):
    """Referencia a un asset privado; nunca contiene URL firmada ni path local."""

    asset_id: UUID | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "DBIPhotoEvidence":
        self._validate_missing_state(self.asset_id)
        return self


class DBICoreObservation(_InspectionModel):
    foure: DBIFoureObservation
    yls: DBILeafCountObservation
    functional_leaves: DBILeafCountObservation
    mother_condition: DBIObservedText
    successor_condition: DBIObservedText
    bunch_present: DBIObservedBool
    visible_affection: DBIObservedText
    severity: DBIObservedText
    observer_confidence: DBIObservedText
    general_photo: DBIPhotoEvidence
    lesion_photo: DBIPhotoEvidence
    note: str | None = Field(default=None, max_length=1_000)


class DBIStructuralObservation(_InspectionModel):
    pseudostem_diameter_cm: DBIObservedFloat

    @model_validator(mode="after")
    def validate_diameter(self) -> "DBIStructuralObservation":
        field = self.pseudostem_diameter_cm
        if field.state == "observed" and field.value is not None and not 0 < field.value <= 200:
            raise ValueError("El diámetro observado debe estar entre 0 y 200 cm.")
        return self


class DBIDiagnosticObservation(_InspectionModel):
    """Sección opcional; sólo se crea cuando existe justificación diagnóstica."""

    trigger_reason: str = Field(min_length=1, max_length=240)
    root_condition: DBIObservedText
    necrosis_or_damage: DBIObservedText
    root_sample_taken: DBIObservedBool
    nematode_or_lab_result: DBIObservedText
    soil_or_nutrition: DBIObservedText
    evidence_photo: DBIPhotoEvidence
    protocol_ref: str | None = Field(default=None, max_length=160)
    laboratory_ref: str | None = Field(default=None, max_length=160)
    method_version: str | None = Field(default=None, max_length=80)


class DBIFieldObservationPayload(_InspectionModel):
    tenant_ref: str = Field(min_length=1, max_length=128)
    organization_ref: str = Field(min_length=1, max_length=128)
    farm_id: UUID
    plot_id: UUID
    operator_ref: str = Field(min_length=1, max_length=128)
    observed_at: datetime
    gps_fix: DBIGPSFix | None = None
    sampling_point_id: UUID | None = None
    up_id: UUID | None = None
    core: DBICoreObservation
    structural: DBIStructuralObservation | None = None
    diagnostic: DBIDiagnosticObservation | None = None
    evidence_kind: EvidenceKind = "observed"

    @field_validator("tenant_ref", "organization_ref", "operator_ref")
    @classmethod
    def require_canonical_scope(cls, value: str) -> str:
        if (
            value != value.strip()
            or "*" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("La referencia debe ser canónica.")
        return value


class DBIFieldObservationCreate(_InspectionModel):
    payload: DBIFieldObservationPayload


class DBIFieldObservationCorrection(_InspectionModel):
    base_version_id: UUID
    correction_reason: str = Field(min_length=1, max_length=500)
    payload: DBIFieldObservationPayload


class DBIFieldObservationVersion(_InspectionModel):
    schema_version: Literal["dbi-field-observation.v1"] = DBI_FIELD_OBSERVATION_SCHEMA_VERSION
    observation_id: UUID
    version_id: UUID
    version: int = Field(ge=1)
    supersedes_version_id: UUID | None = None
    correction_reason: str | None = Field(default=None, max_length=500)
    created_at: datetime
    payload: DBIFieldObservationPayload

    @model_validator(mode="after")
    def validate_version_chain(self) -> "DBIFieldObservationVersion":
        if self.version == 1:
            if self.supersedes_version_id is not None or self.correction_reason is not None:
                raise ValueError("La versión inicial no puede declarar corrección previa.")
            return self
        if self.supersedes_version_id is None or not self.correction_reason:
            raise ValueError("Una corrección requiere versión previa y motivo.")
        return self
