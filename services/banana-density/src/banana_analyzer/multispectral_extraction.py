"""Extracción espacial reproducible para fusionar MULTI con verdad-terreno DBI.

Este módulo produce evidencia ``derived`` a partir de una pila científica ya
co-registrada. La selección espacial llega como máscara explícita: puede representar
COPA_UP o una ventana versionada. Nunca mueve el punto Sampling, nunca inventa una UP
y nunca convierte estadísticos espectrales en observaciones de campo.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

import numpy as np

from .multispectral_indices import SpectralBand, SpectralIndex, index_definition
from .multispectral_stack import (
    PreparedMultispectralStack,
    compute_initial_indices_from_stack,
)

_SCHEMA_VERSION = "dbi-multispectral-extraction.v1"
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class MultispectralExtractionError(RuntimeError):
    """La extracción solicitada no conserva una semántica científica verificable."""


class SpatialSupportMode(StrEnum):
    COPA_UP = "copa_up"
    WINDOW = "window"


@dataclass(frozen=True, slots=True)
class SpectralFieldLink:
    """Enlace inmutable a la versión exacta de verdad-terreno usada como contexto."""

    tenant_ref: str
    organization_ref: str
    farm_id: UUID
    plot_id: UUID
    observation_version_id: UUID
    sampling_point_id: UUID | None = None
    up_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class SpatialSupport:
    """Provenance de la geometría/máscara usada para extraer valores."""

    mode: SpatialSupportMode
    profile_version: str
    limitation: str | None = None


@dataclass(frozen=True, slots=True)
class SpectralVariableSummary:
    variable_kind: str
    variable_ref: str
    evidence_kind: str
    selected_count: int
    valid_count: int
    valid_fraction: float
    mean: float | None
    median: float | None
    p10: float | None
    p90: float | None
    source_ref: UUID | None = None
    source_sha256: str | None = None
    formula_version: str | None = None
    formula: str | None = None


@dataclass(frozen=True, slots=True)
class SpatialSpectralExtraction:
    schema_version: str
    evidence_kind: str
    tenant_ref: str
    organization_ref: str
    farm_id: UUID
    plot_id: UUID
    observation_version_id: UUID
    sampling_point_id: UUID | None
    up_id: UUID | None
    support_mode: SpatialSupportMode
    support_profile_version: str
    support_limitation: str | None
    stack_fingerprint: str
    selected_count: int
    summaries: tuple[SpectralVariableSummary, ...]


def _canonical_ref(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not _REF_RE.fullmatch(value):
        raise MultispectralExtractionError(
            f"{field_name} no es una referencia canónica."
        )
    return value


def _validate_link(link: SpectralFieldLink) -> SpectralFieldLink:
    if not isinstance(link, SpectralFieldLink):
        raise MultispectralExtractionError("link debe ser SpectralFieldLink.")
    _canonical_ref(link.tenant_ref, field_name="tenant_ref")
    _canonical_ref(link.organization_ref, field_name="organization_ref")
    for field_name, value in (
        ("farm_id", link.farm_id),
        ("plot_id", link.plot_id),
        ("observation_version_id", link.observation_version_id),
    ):
        if not isinstance(value, UUID):
            raise MultispectralExtractionError(f"{field_name} debe ser UUID.")
    for field_name, value in (
        ("sampling_point_id", link.sampling_point_id),
        ("up_id", link.up_id),
    ):
        if value is not None and not isinstance(value, UUID):
            raise MultispectralExtractionError(f"{field_name} debe ser UUID o null.")
    return link


def _validate_support(
    support: SpatialSupport,
    *,
    link: SpectralFieldLink,
) -> SpatialSupport:
    if not isinstance(support, SpatialSupport):
        raise MultispectralExtractionError("support debe ser SpatialSupport.")
    if not isinstance(support.mode, SpatialSupportMode):
        raise MultispectralExtractionError("support.mode no es válido.")
    _canonical_ref(support.profile_version, field_name="support.profile_version")
    if support.limitation is not None:
        if (
            not isinstance(support.limitation, str)
            or not support.limitation.strip()
            or len(support.limitation) > 500
        ):
            raise MultispectralExtractionError(
                "support.limitation debe ser texto no vacío de hasta 500 caracteres."
            )
    if support.mode is SpatialSupportMode.WINDOW and support.limitation is None:
        raise MultispectralExtractionError(
            "Una ventana sustituta requiere limitación explícita."
        )
    if support.mode is SpatialSupportMode.COPA_UP and link.up_id is None:
        raise MultispectralExtractionError(
            "COPA_UP requiere una asociación inequívoca con up_id."
        )
    return support


def _selection_mask(
    stack: PreparedMultispectralStack,
    selection_mask: object,
) -> np.ndarray:
    if not isinstance(stack, PreparedMultispectralStack):
        raise MultispectralExtractionError(
            "stack debe ser PreparedMultispectralStack."
        )
    first = stack.bands[SpectralBand.GREEN].calibrated_values
    mask = np.asarray(selection_mask)
    if mask.dtype != np.dtype(bool):
        raise MultispectralExtractionError(
            "selection_mask debe ser una matriz booleana explícita."
        )
    if mask.ndim != 2 or mask.shape != first.shape:
        raise MultispectralExtractionError(
            "selection_mask no coincide con la grilla científica."
        )
    if not np.any(mask):
        raise MultispectralExtractionError(
            "selection_mask no puede seleccionar cero píxeles."
        )
    return mask.copy()


def _summary_stats(
    values: np.ndarray,
    *,
    valid_mask: np.ndarray,
    selection_mask: np.ndarray,
) -> tuple[int, int, float, float | None, float | None, float | None, float | None]:
    selected_count = int(np.count_nonzero(selection_mask))
    usable = selection_mask & valid_mask & np.isfinite(values)
    valid_count = int(np.count_nonzero(usable))
    valid_fraction = valid_count / selected_count
    if valid_count == 0:
        return selected_count, 0, 0.0, None, None, None, None

    selected = values[usable].astype(np.float64, copy=False)
    mean = float(np.mean(selected))
    median = float(np.median(selected))
    p10 = float(np.percentile(selected, 10))
    p90 = float(np.percentile(selected, 90))
    for value in (mean, median, p10, p90):
        if not math.isfinite(value):  # pragma: no cover - defensa tras filtro finite.
            raise MultispectralExtractionError(
                "Un estadístico derivado resultó no finito."
            )
    return selected_count, valid_count, valid_fraction, mean, median, p10, p90


def extract_spectral_evidence(
    stack: PreparedMultispectralStack,
    *,
    link: SpectralFieldLink,
    support: SpatialSupport,
    selection_mask: object,
    epsilon: float = 1e-8,
) -> SpatialSpectralExtraction:
    """Resume bandas e índices dentro de una máscara espacial explícita.

    La función es pura respecto a las bandas fuente: sólo lee copias calibradas y
    devuelve estadísticos. ``observation_version_id`` conserva el vínculo con la
    versión exacta de INSPECT; ``sampling_point_id`` y ``up_id`` son referencias,
    nunca instrucciones para reubicar o reclasificar la observación.
    """

    prepared_link = _validate_link(link)
    prepared_support = _validate_support(support, link=prepared_link)
    mask = _selection_mask(stack, selection_mask)
    selected_count = int(np.count_nonzero(mask))
    summaries: list[SpectralVariableSummary] = []

    for band in SpectralBand:
        prepared_band = stack.bands[band]
        stats = _summary_stats(
            prepared_band.calibrated_values,
            valid_mask=~prepared_band.invalid_mask,
            selection_mask=mask,
        )
        summaries.append(
            SpectralVariableSummary(
                variable_kind="band",
                variable_ref=band.value,
                evidence_kind="derived",
                selected_count=stats[0],
                valid_count=stats[1],
                valid_fraction=stats[2],
                mean=stats[3],
                median=stats[4],
                p10=stats[5],
                p90=stats[6],
                source_ref=prepared_band.source.source_ref,
                source_sha256=prepared_band.source.source_sha256,
            )
        )

    indices = compute_initial_indices_from_stack(stack, epsilon=epsilon)
    for index in SpectralIndex:
        result = indices[index]
        definition = index_definition(index)
        stats = _summary_stats(
            result.values,
            valid_mask=result.valid_mask,
            selection_mask=mask,
        )
        summaries.append(
            SpectralVariableSummary(
                variable_kind="index",
                variable_ref=index.value,
                evidence_kind="derived",
                selected_count=stats[0],
                valid_count=stats[1],
                valid_fraction=stats[2],
                mean=stats[3],
                median=stats[4],
                p10=stats[5],
                p90=stats[6],
                formula_version=definition.formula_version,
                formula=definition.formula,
            )
        )

    return SpatialSpectralExtraction(
        schema_version=_SCHEMA_VERSION,
        evidence_kind="derived",
        tenant_ref=prepared_link.tenant_ref,
        organization_ref=prepared_link.organization_ref,
        farm_id=prepared_link.farm_id,
        plot_id=prepared_link.plot_id,
        observation_version_id=prepared_link.observation_version_id,
        sampling_point_id=prepared_link.sampling_point_id,
        up_id=prepared_link.up_id,
        support_mode=prepared_support.mode,
        support_profile_version=prepared_support.profile_version,
        support_limitation=prepared_support.limitation,
        stack_fingerprint=stack.fingerprint,
        selected_count=selected_count,
        summaries=tuple(summaries),
    )
