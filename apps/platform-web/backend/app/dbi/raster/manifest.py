"""Adaptador estricto del manifiesto worker-side al dominio Raster DBI."""

from __future__ import annotations

import json
from uuid import UUID

from app.dbi.raster.contracts import (
    DBIRasterConflict,
    DBIRasterProductCandidate,
    DBIRasterProductKind,
    DBIRasterSourceKind,
    raster_product_id,
    validate_candidate,
)

_SCHEMA = "dbi-raster-flight-test.v1"
_MAX_MANIFEST_BYTES = 64 * 1024
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "product_kind",
        "profile_version",
        "generator",
        "source_name",
        "source_size_bytes",
        "source_sha256",
        "cog_name",
        "cog_size_bytes",
        "cog_sha256",
        "descriptor",
    }
)
_DESCRIPTOR_KEYS = frozenset(
    {
        "width",
        "height",
        "band_count",
        "dtypes",
        "crs",
        "transform",
        "bounds",
        "nodata",
        "scales",
        "offsets",
        "tiled",
        "block_shapes",
        "compression",
        "overview_levels",
    }
)


def _tuple_numbers(value, *, field_name: str, allow_none: bool = False):
    if not isinstance(value, list):
        raise DBIRasterConflict(f"{field_name} debe ser una lista JSON.")
    result = []
    for item in value:
        if allow_none and item is None:
            result.append(None)
            continue
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise DBIRasterConflict(f"{field_name} contiene un valor inválido.")
        result.append(float(item))
    return tuple(result)


def prepare_candidate_from_manifest(
    manifest_json: str,
    *,
    source_kind: DBIRasterSourceKind,
    source_ref: UUID,
) -> DBIRasterProductCandidate:
    """Acepta sólo el manifiesto canónico esperado; identidad source viene del servidor."""

    if not isinstance(manifest_json, str):
        raise DBIRasterConflict("manifest_json debe ser texto.")
    encoded = manifest_json.encode("utf-8")
    if not encoded or len(encoded) > _MAX_MANIFEST_BYTES:
        raise DBIRasterConflict("El manifiesto Raster queda fuera del límite permitido.")
    if not isinstance(source_kind, DBIRasterSourceKind) or not isinstance(source_ref, UUID):
        raise DBIRasterConflict("La identidad source debe resolverse server-side.")
    try:
        payload = json.loads(manifest_json)
    except (TypeError, ValueError) as error:
        raise DBIRasterConflict("El manifiesto Raster no es JSON válido.") from error
    if not isinstance(payload, dict) or frozenset(payload) != _TOP_LEVEL_KEYS:
        raise DBIRasterConflict("El manifiesto Raster contiene campos inesperados.")
    if payload["schema_version"] != _SCHEMA:
        raise DBIRasterConflict("schema_version Raster no está soportado.")
    if not isinstance(payload["source_name"], str) or not isinstance(payload["cog_name"], str):
        raise DBIRasterConflict("Los nombres del manifiesto no son válidos.")
    for filename in (payload["source_name"], payload["cog_name"]):
        if (
            not filename
            or filename.strip() != filename
            or "/" in filename
            or "\\" in filename
            or filename in {".", ".."}
        ):
            raise DBIRasterConflict("El manifiesto no puede contener rutas.")

    descriptor = payload["descriptor"]
    if not isinstance(descriptor, dict) or frozenset(descriptor) != _DESCRIPTOR_KEYS:
        raise DBIRasterConflict("descriptor Raster contiene campos inesperados.")
    if descriptor["tiled"] is not True:
        raise DBIRasterConflict("El producto oficial debe ser tiled.")
    dtypes = descriptor["dtypes"]
    blocks = descriptor["block_shapes"]
    if (
        not isinstance(dtypes, list)
        or not dtypes
        or any(not isinstance(value, str) for value in dtypes)
        or len(set(dtypes)) != 1
    ):
        raise DBIRasterConflict("Las bandas COG deben compartir un dtype explícito.")
    if (
        not isinstance(blocks, list)
        or not blocks
        or any(
            not isinstance(value, list)
            or len(value) != 2
            or any(not isinstance(number, int) or isinstance(number, bool) for number in value)
            for value in blocks
        )
        or len({tuple(value) for value in blocks}) != 1
    ):
        raise DBIRasterConflict("Las bandas COG deben compartir bloques homogéneos.")
    block_height, block_width = blocks[0]

    try:
        product_kind = DBIRasterProductKind(payload["product_kind"])
    except (TypeError, ValueError) as error:
        raise DBIRasterConflict("product_kind Raster no está soportado.") from error

    candidate = DBIRasterProductCandidate(
        source_kind=source_kind,
        source_ref=source_ref,
        source_sha256=payload["source_sha256"],
        product_kind=product_kind,
        profile_version=payload["profile_version"],
        generator_version=payload["generator"],
        object_id=raster_product_id(
            source_kind=source_kind,
            source_ref=source_ref,
            source_sha256=payload["source_sha256"],
            product_kind=product_kind,
            profile_version=payload["profile_version"],
        ),
        content_type="image/tiff",
        size_bytes=payload["cog_size_bytes"],
        sha256=payload["cog_sha256"],
        crs=descriptor["crs"],
        width=descriptor["width"],
        height=descriptor["height"],
        band_count=descriptor["band_count"],
        dtype=dtypes[0],
        transform=_tuple_numbers(descriptor["transform"], field_name="transform"),
        bounds=_tuple_numbers(descriptor["bounds"], field_name="bounds"),
        nodata=_tuple_numbers(descriptor["nodata"], field_name="nodata", allow_none=True),
        scales=_tuple_numbers(descriptor["scales"], field_name="scales"),
        offsets=_tuple_numbers(descriptor["offsets"], field_name="offsets"),
        block_width=block_width,
        block_height=block_height,
        compression=descriptor["compression"],
        overview_levels=tuple(descriptor["overview_levels"]),
    )
    return validate_candidate(candidate)
