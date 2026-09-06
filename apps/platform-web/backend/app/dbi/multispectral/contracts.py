"""Contratos persistentes para evidencia multiespectral derivada DBI."""

from __future__ import annotations

import math
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DBI_MULTISPECTRAL_EXTRACTION_SCHEMA_VERSION = "dbi-multispectral-extraction.v1"
_EXTRACTION_NAMESPACE = UUID("cab825e8-68ad-4a34-a19a-4d8d87e86c57")
_BAND_REFS = frozenset({"green", "red", "red_edge", "nir"})
_INDEX_REFS = frozenset(
    {"ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green"}
)


class _MultispectralModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class DBISpectralVariableSummary(_MultispectralModel):
    variable_kind: Literal["band", "index"]
    variable_ref: str = Field(min_length=1, max_length=64)
    evidence_kind: Literal["derived"] = "derived"
    selected_count: int = Field(gt=0)
    valid_count: int = Field(ge=0)
    valid_fraction: float = Field(ge=0, le=1)
    mean: float | None = None
    median: float | None = None
    p10: float | None = None
    p90: float | None = None
    source_ref: UUID | None = None
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    formula_version: str | None = Field(default=None, min_length=1, max_length=128)
    formula: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("mean", "median", "p10", "p90")
    @classmethod
    def require_finite_statistics(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("Los estadísticos espectrales deben ser finitos o null.")
        return value

    @model_validator(mode="after")
    def validate_summary_semantics(self) -> "DBISpectralVariableSummary":
        if self.valid_count > self.selected_count:
            raise ValueError("valid_count no puede superar selected_count.")
        expected_fraction = self.valid_count / self.selected_count
        if abs(self.valid_fraction - expected_fraction) > 1e-9:
            raise ValueError("valid_fraction diverge de los conteos persistidos.")

        stats = (self.mean, self.median, self.p10, self.p90)
        if self.valid_count == 0:
            if any(value is not None for value in stats):
                raise ValueError("Sin píxeles válidos los estadísticos deben ser null.")
        elif any(value is None for value in stats):
            raise ValueError("Con píxeles válidos todos los estadísticos son obligatorios.")

        if self.variable_kind == "band":
            if self.variable_ref not in _BAND_REFS:
                raise ValueError("variable_ref de banda no pertenece al contrato inicial.")
            if self.source_ref is None or self.source_sha256 is None:
                raise ValueError("Una banda derivada debe conservar source_ref y SHA-256.")
            if self.formula_version is not None or self.formula is not None:
                raise ValueError("Una banda no debe inventar provenance de fórmula.")
        else:
            if self.variable_ref not in _INDEX_REFS:
                raise ValueError("variable_ref de índice no pertenece al contrato inicial.")
            if self.formula_version is None or self.formula is None:
                raise ValueError("Un índice debe conservar fórmula y versión.")
            if self.source_ref is not None or self.source_sha256 is not None:
                raise ValueError("El índice no suplanta la identidad de una banda fuente.")
        return self


class DBIMultispectralExtractionCandidate(_MultispectralModel):
    schema_version: Literal["dbi-multispectral-extraction.v1"] = (
        DBI_MULTISPECTRAL_EXTRACTION_SCHEMA_VERSION
    )
    tenant_ref: str = Field(min_length=1, max_length=128)
    organization_ref: str = Field(min_length=1, max_length=128)
    farm_id: UUID
    plot_id: UUID
    observation_version_id: UUID
    source_raster_product_id: UUID
    sampling_point_id: UUID | None = None
    up_id: UUID | None = None
    support_mode: Literal["copa_up", "window"]
    support_profile_version: str = Field(min_length=1, max_length=128)
    support_limitation: str | None = Field(default=None, min_length=1, max_length=500)
    stack_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_count: int = Field(gt=0)
    evidence_kind: Literal["derived"] = "derived"
    summaries: tuple[DBISpectralVariableSummary, ...]

    @field_validator(
        "tenant_ref",
        "organization_ref",
        "support_profile_version",
    )
    @classmethod
    def require_canonical_ref(cls, value: str) -> str:
        if (
            value != value.strip()
            or "*" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("La referencia debe ser canónica.")
        return value

    @model_validator(mode="after")
    def validate_candidate_semantics(self) -> "DBIMultispectralExtractionCandidate":
        if self.support_mode == "copa_up":
            if self.up_id is None:
                raise ValueError("COPA_UP exige up_id inequívoco.")
            if self.support_limitation is not None:
                raise ValueError("COPA_UP no debe cargar una limitación de ventana sustituta.")
        elif self.support_limitation is None:
            raise ValueError("Una ventana sustituta exige limitación explícita.")

        expected_keys = {
            *(("band", ref) for ref in _BAND_REFS),
            *(("index", ref) for ref in _INDEX_REFS),
        }
        keys = {(item.variable_kind, item.variable_ref) for item in self.summaries}
        if keys != expected_keys or len(self.summaries) != len(expected_keys):
            raise ValueError("summaries debe contener exactamente 4 bandas y 6 índices.")
        if any(item.selected_count != self.selected_count for item in self.summaries):
            raise ValueError("Cada resumen debe conservar el selected_count de la extracción.")
        return self


def multispectral_extraction_id(candidate: DBIMultispectralExtractionCandidate) -> UUID:
    """Identidad estable para replay exacto de una derivación científica."""

    if not isinstance(candidate, DBIMultispectralExtractionCandidate):
        candidate = DBIMultispectralExtractionCandidate.model_validate(candidate)
    material = ":".join(
        (
            "dbi",
            "multispectral-extraction",
            "v1",
            str(candidate.observation_version_id),
            str(candidate.source_raster_product_id),
            candidate.support_mode,
            candidate.support_profile_version,
            candidate.stack_fingerprint,
        )
    )
    return uuid5(_EXTRACTION_NAMESPACE, material)
