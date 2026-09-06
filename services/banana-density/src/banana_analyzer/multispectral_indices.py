"""Índices multiespectrales reproducibles para DBI-MULTI-001.

Este módulo vive en ``banana-density`` porque el cálculo por píxel pertenece al
worker geoespacial, no al proceso HTTP. Consume bandas ya alineadas y calibradas
al dominio científico del producto fuente; nunca reemplaza ni modifica las
bandas originales.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

import numpy as np


_SCHEMA_VERSION = "dbi-multispectral-index.v1"
_DEFAULT_EPSILON = 1e-8


class MultispectralIndexError(RuntimeError):
    """La entrada no permite producir un derivado científico verificable."""


class SpectralBand(StrEnum):
    GREEN = "green"
    RED = "red"
    RED_EDGE = "red_edge"
    NIR = "nir"


class SpectralIndex(StrEnum):
    NDVI = "ndvi"
    NDRE = "ndre"
    GNDVI = "gndvi"
    EVI2 = "evi2"
    CI_RED_EDGE = "ci_red_edge"
    CI_GREEN = "ci_green"


@dataclass(frozen=True, slots=True)
class SpectralIndexDefinition:
    index: SpectralIndex
    formula_version: str
    formula: str
    required_bands: tuple[SpectralBand, ...]


@dataclass(frozen=True, slots=True)
class SpectralIndexResult:
    schema_version: str
    index: SpectralIndex
    formula_version: str
    formula: str
    evidence_kind: str
    required_bands: tuple[SpectralBand, ...]
    epsilon: float
    values: np.ndarray
    valid_mask: np.ndarray


_DEFINITIONS: dict[SpectralIndex, SpectralIndexDefinition] = {
    SpectralIndex.NDVI: SpectralIndexDefinition(
        index=SpectralIndex.NDVI,
        formula_version="ndvi_v1",
        formula="(nir-red)/(nir+red)",
        required_bands=(SpectralBand.NIR, SpectralBand.RED),
    ),
    SpectralIndex.NDRE: SpectralIndexDefinition(
        index=SpectralIndex.NDRE,
        formula_version="ndre_v1",
        formula="(nir-red_edge)/(nir+red_edge)",
        required_bands=(SpectralBand.NIR, SpectralBand.RED_EDGE),
    ),
    SpectralIndex.GNDVI: SpectralIndexDefinition(
        index=SpectralIndex.GNDVI,
        formula_version="gndvi_v1",
        formula="(nir-green)/(nir+green)",
        required_bands=(SpectralBand.NIR, SpectralBand.GREEN),
    ),
    SpectralIndex.EVI2: SpectralIndexDefinition(
        index=SpectralIndex.EVI2,
        formula_version="evi2_v1",
        formula="2.5*(nir-red)/(nir+2.4*red+1.0)",
        required_bands=(SpectralBand.NIR, SpectralBand.RED),
    ),
    SpectralIndex.CI_RED_EDGE: SpectralIndexDefinition(
        index=SpectralIndex.CI_RED_EDGE,
        formula_version="ci_red_edge_v1",
        formula="nir/red_edge-1",
        required_bands=(SpectralBand.NIR, SpectralBand.RED_EDGE),
    ),
    SpectralIndex.CI_GREEN: SpectralIndexDefinition(
        index=SpectralIndex.CI_GREEN,
        formula_version="ci_green_v1",
        formula="nir/green-1",
        required_bands=(SpectralBand.NIR, SpectralBand.GREEN),
    ),
}


def index_definition(index: SpectralIndex) -> SpectralIndexDefinition:
    if not isinstance(index, SpectralIndex):
        raise MultispectralIndexError("index debe ser SpectralIndex.")
    return _DEFINITIONS[index]


def _as_float_array(value: object, *, band: SpectralBand) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise MultispectralIndexError(
            f"La banda {band.value} no puede convertirse a matriz científica."
        ) from error
    if array.ndim != 2 or array.size == 0:
        raise MultispectralIndexError(
            f"La banda {band.value} debe ser una matriz 2D no vacía."
        )
    return array


def _required_arrays(
    definition: SpectralIndexDefinition,
    bands: Mapping[SpectralBand | str, object],
) -> dict[SpectralBand, np.ndarray]:
    if not isinstance(bands, Mapping):
        raise MultispectralIndexError("bands debe ser un mapping de bandas alineadas.")

    normalized: dict[SpectralBand, np.ndarray] = {}
    shape: tuple[int, int] | None = None
    for band in definition.required_bands:
        raw = bands.get(band)
        if raw is None:
            raw = bands.get(band.value)
        if raw is None:
            raise MultispectralIndexError(f"Falta la banda requerida {band.value}.")
        array = _as_float_array(raw, band=band)
        if shape is None:
            shape = array.shape
        elif array.shape != shape:
            raise MultispectralIndexError("Las bandas requeridas no están alineadas.")
        normalized[band] = array
    return normalized


def _explicit_invalid_mask(mask: object | None, *, shape: tuple[int, int]) -> np.ndarray:
    if mask is None:
        return np.zeros(shape, dtype=bool)
    array = np.asarray(mask)
    if array.shape != shape:
        raise MultispectralIndexError("invalid_mask no coincide con la grilla de bandas.")
    return array.astype(bool, copy=False)


def _safe_divide(
    numerator: np.ndarray,
    denominator: np.ndarray,
    *,
    base_valid: np.ndarray,
    epsilon: float,
) -> tuple[np.ndarray, np.ndarray]:
    denominator_valid = np.isfinite(denominator) & (np.abs(denominator) > epsilon)
    valid = base_valid & np.isfinite(numerator) & denominator_valid
    values = np.full(numerator.shape, np.nan, dtype=np.float64)
    np.divide(numerator, denominator, out=values, where=valid)
    valid &= np.isfinite(values)
    values[~valid] = np.nan
    return values, valid


def compute_index(
    index: SpectralIndex,
    bands: Mapping[SpectralBand | str, object],
    *,
    invalid_mask: object | None = None,
    epsilon: float = _DEFAULT_EPSILON,
) -> SpectralIndexResult:
    """Calcula un índice sin clipping arbitrario y conserva máscara explícita.

    ``bands`` debe contener matrices 2D ya co-registradas. ``invalid_mask`` marca
    píxeles nodata/QA inválidos provenientes de la autoridad ráster. El resultado
    usa ``NaN`` fuera de la máscara válida; no inventa reflectancia ni rellena huecos.
    """

    definition = index_definition(index)
    if not isinstance(epsilon, (int, float)) or isinstance(epsilon, bool):
        raise MultispectralIndexError("epsilon debe ser numérico positivo y finito.")
    epsilon = float(epsilon)
    if not np.isfinite(epsilon) or epsilon <= 0:
        raise MultispectralIndexError("epsilon debe ser numérico positivo y finito.")

    arrays = _required_arrays(definition, bands)
    shape = next(iter(arrays.values())).shape
    explicit_invalid = _explicit_invalid_mask(invalid_mask, shape=shape)
    base_valid = ~explicit_invalid
    for array in arrays.values():
        base_valid &= np.isfinite(array)

    nir = arrays[SpectralBand.NIR]

    if index is SpectralIndex.NDVI:
        red = arrays[SpectralBand.RED]
        values, valid = _safe_divide(
            nir - red,
            nir + red,
            base_valid=base_valid,
            epsilon=epsilon,
        )
    elif index is SpectralIndex.NDRE:
        red_edge = arrays[SpectralBand.RED_EDGE]
        values, valid = _safe_divide(
            nir - red_edge,
            nir + red_edge,
            base_valid=base_valid,
            epsilon=epsilon,
        )
    elif index is SpectralIndex.GNDVI:
        green = arrays[SpectralBand.GREEN]
        values, valid = _safe_divide(
            nir - green,
            nir + green,
            base_valid=base_valid,
            epsilon=epsilon,
        )
    elif index is SpectralIndex.EVI2:
        red = arrays[SpectralBand.RED]
        values, valid = _safe_divide(
            2.5 * (nir - red),
            nir + 2.4 * red + 1.0,
            base_valid=base_valid,
            epsilon=epsilon,
        )
    elif index is SpectralIndex.CI_RED_EDGE:
        red_edge = arrays[SpectralBand.RED_EDGE]
        ratio, valid = _safe_divide(
            nir,
            red_edge,
            base_valid=base_valid,
            epsilon=epsilon,
        )
        values = ratio - 1.0
        values[~valid] = np.nan
    elif index is SpectralIndex.CI_GREEN:
        green = arrays[SpectralBand.GREEN]
        ratio, valid = _safe_divide(
            nir,
            green,
            base_valid=base_valid,
            epsilon=epsilon,
        )
        values = ratio - 1.0
        values[~valid] = np.nan
    else:  # pragma: no cover - defensa si el enum se extiende sin implementar fórmula.
        raise MultispectralIndexError(f"Índice no implementado: {index.value}.")

    return SpectralIndexResult(
        schema_version=_SCHEMA_VERSION,
        index=index,
        formula_version=definition.formula_version,
        formula=definition.formula,
        evidence_kind="derived",
        required_bands=definition.required_bands,
        epsilon=epsilon,
        values=values.astype(np.float32),
        valid_mask=valid,
    )


def compute_initial_indices(
    bands: Mapping[SpectralBand | str, object],
    *,
    invalid_mask: object | None = None,
    epsilon: float = _DEFAULT_EPSILON,
) -> dict[SpectralIndex, SpectralIndexResult]:
    """Calcula el conjunto inicial aprobado de DBI-MULTI-001."""

    return {
        index: compute_index(
            index,
            bands,
            invalid_mask=invalid_mask,
            epsilon=epsilon,
        )
        for index in SpectralIndex
    }
