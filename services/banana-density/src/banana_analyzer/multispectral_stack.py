"""Preparación trazable de bandas científicas para DBI-MULTI-001.

La autoridad científica sigue siendo cada banda fuente (objeto + SHA-256 + índice
de banda + metadata ráster). Este módulo sólo prepara copias calibradas para cálculo,
sin modificar los arrays originales ni convertir índices derivados en nueva verdad.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Mapping
from uuid import UUID

import numpy as np

from .multispectral_indices import (
    SpectralBand,
    SpectralIndex,
    SpectralIndexResult,
    compute_index,
    index_definition,
)

_SCHEMA_VERSION = "dbi-multispectral-stack.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TRANSFORM_TOLERANCE = 1e-12


class MultispectralStackError(RuntimeError):
    """La pila fuente no conserva provenance/alineación científica suficiente."""


@dataclass(frozen=True, slots=True)
class SpectralBandSource:
    """Banda original identificada por referencia y checksum, nunca por ruta local."""

    band: SpectralBand
    source_ref: UUID
    source_sha256: str
    band_index: int
    crs: str
    transform: tuple[float, float, float, float, float, float]
    width: int
    height: int
    dtype: str
    nodata: float | int | None
    scale: float
    offset: float
    calibration_profile_version: str
    values: np.ndarray


@dataclass(frozen=True, slots=True)
class PreparedSpectralBand:
    source: SpectralBandSource
    calibrated_values: np.ndarray
    invalid_mask: np.ndarray


@dataclass(frozen=True, slots=True)
class PreparedMultispectralStack:
    schema_version: str
    fingerprint: str
    bands: dict[SpectralBand, PreparedSpectralBand]


def _canonical_ref(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not _REF_RE.fullmatch(value):
        raise MultispectralStackError(f"{field_name} no es una referencia canónica.")
    return value


def _finite_number(value: object, *, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise MultispectralStackError(f"{field_name} debe ser numérico finito.")
    number = float(value)
    if not math.isfinite(number):
        raise MultispectralStackError(f"{field_name} debe ser numérico finito.")
    return number


def _nodata_value(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise MultispectralStackError("nodata debe ser numérico o null.")
    number = float(value)
    if math.isinf(number):
        raise MultispectralStackError("nodata no puede ser infinito.")
    return number


def _validate_source(
    source: SpectralBandSource,
) -> tuple[
    str,
    tuple[float, float, float, float, float, float],
    np.ndarray,
    float,
    float,
    float | None,
]:
    if not isinstance(source, SpectralBandSource):
        raise MultispectralStackError("Cada entrada debe ser SpectralBandSource.")
    if not isinstance(source.band, SpectralBand):
        raise MultispectralStackError("band debe ser SpectralBand.")
    if not isinstance(source.source_ref, UUID):
        raise MultispectralStackError("source_ref debe ser UUID.")
    if not isinstance(source.source_sha256, str) or not _SHA_RE.fullmatch(
        source.source_sha256
    ):
        raise MultispectralStackError("source_sha256 debe ser SHA-256 canónico.")
    if (
        not isinstance(source.band_index, int)
        or isinstance(source.band_index, bool)
        or source.band_index <= 0
    ):
        raise MultispectralStackError("band_index debe ser entero positivo.")

    crs = _canonical_ref(source.crs, field_name="crs")
    if not isinstance(source.transform, tuple) or len(source.transform) != 6:
        raise MultispectralStackError("transform debe contener seis coeficientes.")
    transform = tuple(
        _finite_number(value, field_name="transform") for value in source.transform
    )

    for field_name, value in (("width", source.width), ("height", source.height)):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise MultispectralStackError(f"{field_name} debe ser entero positivo.")

    raw = np.asarray(source.values)
    if raw.ndim != 2 or raw.shape != (source.height, source.width):
        raise MultispectralStackError(
            f"La banda {source.band.value} no coincide con width/height declarados."
        )
    try:
        declared_dtype = np.dtype(source.dtype)
    except (TypeError, ValueError) as error:
        raise MultispectralStackError("dtype no es reconocido por NumPy.") from error
    if raw.dtype != declared_dtype:
        raise MultispectralStackError(
            f"dtype declarado de {source.band.value} no coincide con el array fuente."
        )

    nodata = _nodata_value(source.nodata)
    scale = _finite_number(source.scale, field_name="scale")
    if scale == 0.0:
        raise MultispectralStackError("scale no puede ser cero.")
    offset = _finite_number(source.offset, field_name="offset")
    _canonical_ref(
        source.calibration_profile_version,
        field_name="calibration_profile_version",
    )
    return crs, transform, raw, scale, offset, nodata


def _same_grid(
    reference: tuple[
        str,
        tuple[float, float, float, float, float, float],
        int,
        int,
    ],
    candidate: tuple[
        str,
        tuple[float, float, float, float, float, float],
        int,
        int,
    ],
) -> bool:
    ref_crs, ref_transform, ref_width, ref_height = reference
    crs, transform, width, height = candidate
    return (
        crs == ref_crs
        and width == ref_width
        and height == ref_height
        and np.allclose(
            np.asarray(transform),
            np.asarray(ref_transform),
            rtol=0.0,
            atol=_TRANSFORM_TOLERANCE,
        )
    )


def _fingerprint_nodata(value: float | int | None) -> float | int | str | None:
    if value is None:
        return None
    number = float(value)
    if math.isnan(number):
        return "NaN"
    return value


def _fingerprint(bands: dict[SpectralBand, PreparedSpectralBand]) -> str:
    material: list[dict[str, object]] = []
    for band in SpectralBand:
        source = bands[band].source
        material.append(
            {
                "band": band.value,
                "source_ref": str(source.source_ref),
                "source_sha256": source.source_sha256,
                "band_index": source.band_index,
                "crs": source.crs,
                "transform": list(source.transform),
                "width": source.width,
                "height": source.height,
                "dtype": np.dtype(source.dtype).name,
                "nodata": _fingerprint_nodata(source.nodata),
                "scale": float(source.scale),
                "offset": float(source.offset),
                "calibration_profile_version": source.calibration_profile_version,
            }
        )
    canonical = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def prepare_multispectral_stack(
    sources: Mapping[SpectralBand | str, SpectralBandSource],
) -> PreparedMultispectralStack:
    """Valida cuatro bandas co-registradas y genera copias calibradas trazables."""

    if not isinstance(sources, Mapping):
        raise MultispectralStackError("sources debe ser un mapping de bandas fuente.")

    prepared: dict[SpectralBand, PreparedSpectralBand] = {}
    reference_grid: tuple[
        str,
        tuple[float, float, float, float, float, float],
        int,
        int,
    ] | None = None

    for band in SpectralBand:
        source = sources.get(band)
        if source is None:
            source = sources.get(band.value)
        if source is None:
            raise MultispectralStackError(f"Falta la banda científica {band.value}.")
        if source.band is not band:
            raise MultispectralStackError(
                f"La clave {band.value} no coincide con source.band."
            )

        crs, transform, raw, scale, offset, nodata = _validate_source(source)
        current_grid = (crs, transform, source.width, source.height)
        if reference_grid is None:
            reference_grid = current_grid
        elif not _same_grid(reference_grid, current_grid):
            raise MultispectralStackError("Las bandas científicas no están co-registradas.")

        calibrated = raw.astype(np.float64, copy=True)
        calibrated *= scale
        calibrated += offset

        invalid = ~np.isfinite(calibrated)
        if nodata is not None:
            if math.isnan(nodata):
                invalid |= np.isnan(raw.astype(np.float64, copy=False))
            else:
                invalid |= raw == nodata
        calibrated[invalid] = np.nan

        prepared[band] = PreparedSpectralBand(
            source=source,
            calibrated_values=calibrated,
            invalid_mask=invalid,
        )

    return PreparedMultispectralStack(
        schema_version=_SCHEMA_VERSION,
        fingerprint=_fingerprint(prepared),
        bands=prepared,
    )


def index_invalid_mask(
    stack: PreparedMultispectralStack,
    index: SpectralIndex,
) -> np.ndarray:
    """Combina sólo QA/nodata de las bandas realmente usadas por el índice."""

    if not isinstance(stack, PreparedMultispectralStack):
        raise MultispectralStackError("stack debe ser PreparedMultispectralStack.")
    definition = index_definition(index)
    mask: np.ndarray | None = None
    for band in definition.required_bands:
        band_mask = stack.bands[band].invalid_mask
        mask = band_mask.copy() if mask is None else (mask | band_mask)
    if mask is None:  # pragma: no cover - todo índice actual requiere bandas.
        raise MultispectralStackError("El índice no declara bandas requeridas.")
    return mask


def compute_initial_indices_from_stack(
    stack: PreparedMultispectralStack,
    *,
    epsilon: float = 1e-8,
) -> dict[SpectralIndex, SpectralIndexResult]:
    """Calcula derivados desde copias calibradas sin mutar la autoridad fuente."""

    if not isinstance(stack, PreparedMultispectralStack):
        raise MultispectralStackError("stack debe ser PreparedMultispectralStack.")
    calibrated = {
        band: prepared.calibrated_values for band, prepared in stack.bands.items()
    }
    return {
        index: compute_index(
            index,
            calibrated,
            invalid_mask=index_invalid_mask(stack, index),
            epsilon=epsilon,
        )
        for index in SpectralIndex
    }
