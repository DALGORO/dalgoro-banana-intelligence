"""Modelo puro de capacidad y egreso para productos Raster DBI."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from app.dbi.raster.contracts import DBIRasterConflict


@dataclass(frozen=True, slots=True)
class DBIRasterBudgetEstimate:
    """Magnitudes técnicas en bytes; nunca contiene precios de proveedor."""

    master_bytes: int
    cog_bytes: int
    persistent_storage_bytes: int
    full_resolution_uncompressed_bytes: int
    overview_raw_pixel_fraction: float
    overview_uncompressed_equivalent_bytes: int
    range_egress_bytes: int


def _positive_int(value: object, *, field_name: str, allow_zero: bool = False) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or (not allow_zero and value == 0)
    ):
        raise DBIRasterConflict(f"{field_name} debe ser un entero válido.")
    return value


def overview_raw_pixel_fraction(levels: tuple[int, ...]) -> float:
    """Fracción teórica de píxeles extra por pirámide, sin asumir compresión."""

    if not isinstance(levels, tuple) or any(
        not isinstance(level, int)
        or isinstance(level, bool)
        or level <= 1
        for level in levels
    ):
        raise DBIRasterConflict("overview_levels debe contener enteros mayores que uno.")
    if tuple(sorted(set(levels))) != levels:
        raise DBIRasterConflict("overview_levels debe ser creciente y sin duplicados.")
    return sum(1.0 / (level * level) for level in levels)


def estimate_raster_budget(
    *,
    master_bytes: int,
    cog_bytes: int,
    full_resolution_uncompressed_bytes: int,
    overview_levels: tuple[int, ...],
    range_egress_bytes: int,
) -> DBIRasterBudgetEstimate:
    """Calcula capacidad/egreso sin convertir bytes a dinero ni asumir proveedor."""

    master = _positive_int(master_bytes, field_name="master_bytes")
    cog = _positive_int(cog_bytes, field_name="cog_bytes")
    uncompressed = _positive_int(
        full_resolution_uncompressed_bytes,
        field_name="full_resolution_uncompressed_bytes",
    )
    egress = _positive_int(
        range_egress_bytes,
        field_name="range_egress_bytes",
        allow_zero=True,
    )
    fraction = overview_raw_pixel_fraction(overview_levels)
    return DBIRasterBudgetEstimate(
        master_bytes=master,
        cog_bytes=cog,
        persistent_storage_bytes=master + cog,
        full_resolution_uncompressed_bytes=uncompressed,
        overview_raw_pixel_fraction=fraction,
        overview_uncompressed_equivalent_bytes=ceil(uncompressed * fraction),
        range_egress_bytes=egress,
    )
