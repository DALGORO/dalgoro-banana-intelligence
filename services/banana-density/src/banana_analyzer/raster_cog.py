"""Generación y validación COG aislada para DBI-RASTER-001.

Este módulo vive en el entorno geoespacial de ``banana-density`` porque allí
Rasterio/GDAL ya son dependencias controladas. No pertenece al proceso HTTP.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

import rasterio
from rasterio.shutil import copy as raster_copy

ProductKind = Literal["rgb_visual", "scientific"]
_SCHEMA_VERSION = "dbi-raster-flight-test.v1"
_CHUNK_SIZE = 1024 * 1024
_BLOCK_SIZE = 512


class RasterCOGError(RuntimeError):
    """El source o el COG no cumple el contrato mínimo DBI."""


@dataclass(frozen=True, slots=True)
class RasterDescriptor:
    width: int
    height: int
    band_count: int
    dtypes: tuple[str, ...]
    crs: str
    transform: tuple[float, float, float, float, float, float]
    bounds: tuple[float, float, float, float]
    nodata: tuple[float | None, ...]
    scales: tuple[float, ...]
    offsets: tuple[float, ...]
    tiled: bool
    block_shapes: tuple[tuple[int, int], ...]
    overview_levels: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RasterCOGManifest:
    schema_version: str
    product_kind: ProductKind
    profile_version: str
    generator: str
    source_name: str
    source_size_bytes: int
    source_sha256: str
    cog_name: str
    cog_size_bytes: int
    cog_sha256: str
    descriptor: RasterDescriptor


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = sha256()
    total = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
    if total <= 0:
        raise RasterCOGError("El archivo ráster está vacío.")
    return total, digest.hexdigest()


def _descriptor(path: Path) -> RasterDescriptor:
    try:
        with rasterio.open(path) as dataset:
            if dataset.crs is None:
                raise RasterCOGError("El ráster debe contener CRS.")
            if dataset.width <= 0 or dataset.height <= 0 or dataset.count <= 0:
                raise RasterCOGError("Dimensiones o bandas ráster inválidas.")
            transform = dataset.transform
            if transform.a == 0 or transform.e == 0:
                raise RasterCOGError("La resolución geoespacial no puede ser cero.")
            bounds = dataset.bounds
            overviews = tuple(dataset.overviews(1)) if dataset.count else ()
            return RasterDescriptor(
                width=int(dataset.width),
                height=int(dataset.height),
                band_count=int(dataset.count),
                dtypes=tuple(str(value) for value in dataset.dtypes),
                crs=dataset.crs.to_string(),
                transform=(
                    float(transform.a),
                    float(transform.b),
                    float(transform.c),
                    float(transform.d),
                    float(transform.e),
                    float(transform.f),
                ),
                bounds=(
                    float(bounds.left),
                    float(bounds.bottom),
                    float(bounds.right),
                    float(bounds.top),
                ),
                nodata=tuple(
                    None if value is None else float(value)
                    for value in dataset.nodatavals
                ),
                scales=tuple(float(value) for value in dataset.scales),
                offsets=tuple(float(value) for value in dataset.offsets),
                tiled=bool(dataset.is_tiled),
                block_shapes=tuple(
                    (int(rows), int(cols)) for rows, cols in dataset.block_shapes
                ),
                overview_levels=tuple(int(value) for value in overviews),
            )
    except RasterCOGError:
        raise
    except Exception as error:
        raise RasterCOGError("No se pudo abrir el ráster con Rasterio/GDAL.") from error


def _validate_source(descriptor: RasterDescriptor, *, product_kind: ProductKind) -> None:
    if product_kind not in {"rgb_visual", "scientific"}:
        raise RasterCOGError("product_kind no está soportado.")
    if product_kind == "rgb_visual" and descriptor.band_count < 3:
        raise RasterCOGError("rgb_visual requiere al menos tres bandas.")


def _validate_cog(
    source: RasterDescriptor,
    cog: RasterDescriptor,
    *,
    product_kind: ProductKind,
) -> None:
    if not cog.tiled:
        raise RasterCOGError("El derivado no quedó organizado por bloques.")
    if (
        cog.width != source.width
        or cog.height != source.height
        or cog.band_count != source.band_count
        or cog.dtypes != source.dtypes
        or cog.crs != source.crs
        or cog.transform != source.transform
        or cog.bounds != source.bounds
    ):
        raise RasterCOGError("El COG alteró geometría, bandas o dtype del source.")
    if product_kind == "scientific" and (
        cog.nodata != source.nodata
        or cog.scales != source.scales
        or cog.offsets != source.offsets
    ):
        raise RasterCOGError("El COG científico alteró nodata/scale/offset.")
    if max(cog.width, cog.height) > _BLOCK_SIZE and not cog.overview_levels:
        raise RasterCOGError("Un ráster grande debe publicar overviews.")


def generate_validated_cog(
    source_path: str | Path,
    cog_path: str | Path,
    *,
    product_kind: ProductKind = "rgb_visual",
    profile_version: str = "cog_v1",
) -> RasterCOGManifest:
    """Genera un COG completo y lo valida antes de devolver su manifiesto."""

    source = Path(source_path).expanduser().resolve()
    output = Path(cog_path).expanduser().resolve()
    if source == output:
        raise RasterCOGError("Source y COG deben ser archivos distintos.")
    if not source.is_file():
        raise RasterCOGError("El source ráster no existe.")
    if output.exists():
        raise RasterCOGError("El COG destino ya existe; no se sobrescribe.")
    if not profile_version or profile_version.strip() != profile_version:
        raise RasterCOGError("profile_version debe ser canónico.")

    source_descriptor = _descriptor(source)
    _validate_source(source_descriptor, product_kind=product_kind)
    source_size, source_sha = _sha256_file(source)
    output.parent.mkdir(parents=True, exist_ok=True)

    creation_options = {
        "driver": "COG",
        "BLOCKSIZE": _BLOCK_SIZE,
        "COMPRESS": "DEFLATE",
        "BIGTIFF": "IF_SAFER",
        "OVERVIEW_RESAMPLING": "AVERAGE",
        "NUM_THREADS": "ALL_CPUS",
    }
    try:
        raster_copy(source, output, **creation_options)
        cog_descriptor = _descriptor(output)
        _validate_cog(
            source_descriptor,
            cog_descriptor,
            product_kind=product_kind,
        )
        cog_size, cog_sha = _sha256_file(output)
    except Exception:
        output.unlink(missing_ok=True)
        raise

    return RasterCOGManifest(
        schema_version=_SCHEMA_VERSION,
        product_kind=product_kind,
        profile_version=profile_version,
        generator=f"rasterio-{rasterio.__version__}/gdal-{rasterio.__gdal_version__}",
        source_name=source.name,
        source_size_bytes=source_size,
        source_sha256=source_sha,
        cog_name=output.name,
        cog_size_bytes=cog_size,
        cog_sha256=cog_sha,
        descriptor=cog_descriptor,
    )


def write_manifest(manifest: RasterCOGManifest, path: str | Path) -> Path:
    """Escribe JSON determinista sin rutas absolutas ni secretos."""

    destination = Path(path).expanduser().resolve()
    if destination.exists():
        raise RasterCOGError("El manifiesto destino ya existe; no se sobrescribe.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        asdict(manifest),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    destination.write_text(payload + "\n", encoding="utf-8")
    return destination
