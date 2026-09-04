"""Contratos frozen para registrar productos COG privados DBI."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid5

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PRODUCT_NAMESPACE = UUID("7f52914c-6a68-4f08-96cf-8221d0749615")


class DBIRasterError(RuntimeError):
    """Error base de Raster; los detalles no contienen secretos ni rutas."""


class DBIRasterConflict(DBIRasterError):
    """La identidad solicitada diverge de una autoridad DBI existente."""


class DBIRasterSourceKind(StrEnum):
    INPUT_ASSET = "input_asset"
    ANALYSIS_ARTIFACT = "analysis_artifact"


class DBIRasterProductKind(StrEnum):
    RGB_VISUAL = "rgb_visual"
    SCIENTIFIC = "scientific"


@dataclass(frozen=True, slots=True)
class DBIRasterSource:
    tenant_ref: str
    farm_id: UUID
    plot_id: UUID
    source_kind: DBIRasterSourceKind
    source_ref: UUID
    source_sha256: str


@dataclass(frozen=True, slots=True)
class DBIRasterProductCandidate:
    source_kind: DBIRasterSourceKind
    source_ref: UUID
    source_sha256: str
    product_kind: DBIRasterProductKind
    profile_version: str
    generator_version: str
    object_id: UUID
    content_type: str
    size_bytes: int
    sha256: str
    crs: str
    width: int
    height: int
    band_count: int
    dtype: str
    transform: tuple[float, float, float, float, float, float]
    bounds: tuple[float, float, float, float]
    nodata: tuple[float | None, ...]
    scales: tuple[float, ...]
    offsets: tuple[float, ...]
    block_width: int
    block_height: int
    compression: str
    overview_levels: tuple[int, ...]


def _canonical_ref(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not _REF_RE.fullmatch(value):
        raise DBIRasterConflict(f"{field_name} no es una referencia canónica.")
    return value


def _sha(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise DBIRasterConflict(f"{field_name} debe ser SHA-256 canónico.")
    return value


def _positive_int(value: object, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise DBIRasterConflict(f"{field_name} debe ser entero positivo.")
    return value


def _finite_tuple(
    values: object,
    *,
    field_name: str,
    length: int | None = None,
    allow_none: bool = False,
) -> tuple[float | None, ...]:
    if not isinstance(values, tuple) or (length is not None and len(values) != length):
        raise DBIRasterConflict(f"{field_name} no cumple la forma esperada.")
    normalized: list[float | None] = []
    for value in values:
        if allow_none and value is None:
            normalized.append(None)
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise DBIRasterConflict(f"{field_name} contiene un valor inválido.")
        number = float(value)
        if not math.isfinite(number):
            raise DBIRasterConflict(f"{field_name} contiene un valor no finito.")
        normalized.append(number)
    return tuple(normalized)


def raster_product_id(
    *,
    source_kind: DBIRasterSourceKind,
    source_ref: UUID,
    source_sha256: str,
    product_kind: DBIRasterProductKind,
    profile_version: str,
) -> UUID:
    """Identidad estable: una misma fuente/perfil nunca genera dos oficiales."""

    if not isinstance(source_kind, DBIRasterSourceKind):
        raise DBIRasterConflict("source_kind inválido.")
    if not isinstance(source_ref, UUID):
        raise DBIRasterConflict("source_ref debe ser UUID.")
    digest = _sha(source_sha256, field_name="source_sha256")
    if not isinstance(product_kind, DBIRasterProductKind):
        raise DBIRasterConflict("product_kind inválido.")
    profile = _canonical_ref(profile_version, field_name="profile_version")
    material = (
        f"dbi:raster-product:v1:{source_kind.value}:{source_ref}:"
        f"{digest}:{product_kind.value}:{profile}"
    )
    return uuid5(_PRODUCT_NAMESPACE, material)


def validate_candidate(candidate: DBIRasterProductCandidate) -> DBIRasterProductCandidate:
    if not isinstance(candidate, DBIRasterProductCandidate):
        raise DBIRasterConflict("candidate debe ser DBIRasterProductCandidate.")
    expected_id = raster_product_id(
        source_kind=candidate.source_kind,
        source_ref=candidate.source_ref,
        source_sha256=candidate.source_sha256,
        product_kind=candidate.product_kind,
        profile_version=candidate.profile_version,
    )
    if candidate.object_id != expected_id:
        raise DBIRasterConflict("object_id no coincide con la identidad determinista.")
    _canonical_ref(candidate.generator_version, field_name="generator_version")
    if candidate.content_type != "image/tiff":
        raise DBIRasterConflict("El COG oficial debe usar image/tiff.")
    _positive_int(candidate.size_bytes, field_name="size_bytes")
    _sha(candidate.sha256, field_name="sha256")
    _canonical_ref(candidate.crs, field_name="crs")
    _positive_int(candidate.width, field_name="width")
    _positive_int(candidate.height, field_name="height")
    bands = _positive_int(candidate.band_count, field_name="band_count")
    if candidate.product_kind is DBIRasterProductKind.RGB_VISUAL and bands < 3:
        raise DBIRasterConflict("rgb_visual requiere al menos tres bandas.")
    _canonical_ref(candidate.dtype, field_name="dtype")
    _finite_tuple(candidate.transform, field_name="transform", length=6)
    _finite_tuple(candidate.bounds, field_name="bounds", length=4)
    nodata = _finite_tuple(candidate.nodata, field_name="nodata", allow_none=True)
    scales = _finite_tuple(candidate.scales, field_name="scales")
    offsets = _finite_tuple(candidate.offsets, field_name="offsets")
    if not (len(nodata) == len(scales) == len(offsets) == bands):
        raise DBIRasterConflict("Metadatos por banda no coinciden con band_count.")
    for field_name, value in (
        ("block_width", candidate.block_width),
        ("block_height", candidate.block_height),
    ):
        block = _positive_int(value, field_name=field_name)
        if block < 64 or block > 4096:
            raise DBIRasterConflict(f"{field_name} queda fuera de política.")
    _canonical_ref(candidate.compression.lower(), field_name="compression")
    previous = 1
    for level in candidate.overview_levels:
        if not isinstance(level, int) or isinstance(level, bool) or level <= previous:
            raise DBIRasterConflict("overview_levels debe ser estrictamente creciente.")
        previous = level
    if max(candidate.width, candidate.height) > max(candidate.block_width, candidate.block_height):
        if not candidate.overview_levels:
            raise DBIRasterConflict("Un COG grande debe contener overviews.")
    return candidate


def canonical_json(value: object) -> str:
    """JSON compacto y reproducible para metadatos persistentes."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise DBIRasterConflict("Metadata Raster no es JSON canónico.") from error
