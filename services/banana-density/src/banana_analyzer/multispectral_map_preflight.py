"""Preflight offline de seis COG científicos y seis estilos QML DBI.

No comprueba aprobación institucional ni vinculación real con Campaign.
Opera sólo en el worker geoespacial, jamás desde un endpoint público.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
from pathlib import Path
import re
from typing import Mapping
from uuid import UUID
from xml.etree import ElementTree

import numpy as np
import rasterio

from banana_analyzer.multispectral_indices import SpectralIndex, index_definition

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INDEX_NAMES = frozenset(index.value for index in SpectralIndex)
_MAX_QML_BYTES = 1024 * 1024


class DBIIndexMapPreflightError(ValueError):
    """Los archivos no superan el control técnico previo a revisión."""


@dataclass(frozen=True, slots=True)
class DBIIndexMapTechnicalEvidence:
    index: str
    formula_version: str
    formula: str
    raster_sha256: str
    raster_bytes: int
    qml_sha256: str
    qml_color_stops: int
    crs: str
    transform: tuple[float, float, float, float, float, float]
    bounds: tuple[float, float, float, float]
    width: int
    height: int
    nodata: float
    valid_pixels: int
    masked_pixels: int


@dataclass(frozen=True, slots=True)
class DBISixIndexMapPreflight:
    schema_version: str
    campaign_id_claimed: str
    stack_fingerprint_claimed: str
    disposition: str
    campaign_link_verified: bool
    source_calibration_verified: bool
    institutional_publication_authorized: bool
    indexes: tuple[DBIIndexMapTechnicalEvidence, ...]


def _file_sha(path: Path) -> tuple[int, str]:
    digest = sha256()
    total = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            total += len(chunk)
            digest.update(chunk)
    if total == 0:
        raise DBIIndexMapPreflightError("Archivo vacío.")
    return total, digest.hexdigest()


def _local_tag(tag: str) -> str:
    return tag.rpartition("}")[2] if "}" in tag else tag


def _inspect_qml(path: Path) -> tuple[str, int]:
    if not path.is_file() or path.suffix.lower() != ".qml":
        raise DBIIndexMapPreflightError("Falta archivo QML local para el índice.")
    size = path.stat().st_size
    if size <= 0 or size > _MAX_QML_BYTES:
        raise DBIIndexMapPreflightError("Tamaño QML fuera de política.")
    payload = path.read_bytes()
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise DBIIndexMapPreflightError("QML no puede incluir entidades/DTD.")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise DBIIndexMapPreflightError("QML inválido.") from error
    if _local_tag(root.tag).lower() != "qgis":
        raise DBIIndexMapPreflightError("El estilo debe ser un proyecto QML QGIS.")
    renderers = [el for el in root.iter() if _local_tag(el.tag) == "rasterrenderer"]
    if (
        len(renderers) != 1
        or renderers[0].get("type") != "singlebandpseudocolor"
        or renderers[0].get("band") != "1"
    ):
        raise DBIIndexMapPreflightError("QML debe simbolizar una banda científica pseudocolor.")
    shaders = [el for el in renderers[0].iter() if _local_tag(el.tag) == "colorrampshader"]
    if len(shaders) != 1:
        raise DBIIndexMapPreflightError("El QML carece de una única rampa de color.")
    stops = [el for el in shaders[0] if _local_tag(el.tag) == "item"]
    if not 2 <= len(stops) <= 256:
        raise DBIIndexMapPreflightError("La rampa QML requiere 2–256 paradas.")
    try:
        values = [float(el.attrib["value"]) for el in stops]
    except (KeyError, ValueError) as error:
        raise DBIIndexMapPreflightError("Los valores QML no son numéricos.") from error
    if not all(math.isfinite(v) for v in values) or values != sorted(set(values)):
        raise DBIIndexMapPreflightError("Los valores QML deben ser finitos y crecientes.")
    return sha256(payload).hexdigest(), len(stops)


def _inspect_cog(path: Path) -> tuple[str, int, str, tuple[float, ...], tuple[float, ...], int, int, float, int, int]:
    if not path.is_file() or path.suffix.lower() not in {".tif", ".tiff"}:
        raise DBIIndexMapPreflightError("Falta COG TIFF local del índice.")
    size, digest = _file_sha(path)
    try:
        with rasterio.open(path) as ds:
            if ds.driver != "GTiff" or ds.count != 1 or ds.dtypes[0] != "float32":
                raise DBIIndexMapPreflightError("El índice debe ser GeoTIFF Float32 monobanda.")
            if ds.crs is None or ds.transform.is_identity or not ds.is_tiled:
                raise DBIIndexMapPreflightError("El COG exige CRS y grilla georreferenciada en bloques.")
            if ds.width <= 0 or ds.height <= 0 or not math.isfinite(float(ds.transform.determinant)) or abs(ds.transform.determinant) < 1e-18:
                raise DBIIndexMapPreflightError("Grilla ráster inválida.")
            if max(ds.width, ds.height) > 512 and not ds.overviews(1):
                raise DBIIndexMapPreflightError("COG grande sin overviews.")
            compression = str(getattr(ds.compression, "value", ds.compression)).lower()
            if compression not in {"deflate", "lzw", "zstd", "none"}:
                raise DBIIndexMapPreflightError("El índice científico no admite compresión con pérdida.")
            if ds.nodata is None or not math.isfinite(float(ds.nodata)):
                raise DBIIndexMapPreflightError("NoData científico finito obligatorio.")
            if ds.scales != (1.0,) or ds.offsets != (0.0,):
                raise DBIIndexMapPreflightError("La banda Float32 requiere escala 1 y offset 0.")
            bounds = tuple(float(v) for v in ds.bounds)
            transform = tuple(float(v) for v in ds.transform)[:6]
            if not all(math.isfinite(v) for v in bounds + transform) or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
                raise DBIIndexMapPreflightError("Extensión geográfica inválida.")
            valid = 0
            masked = 0
            for _, window in ds.block_windows(1):
                tile = ds.read(1, window=window, masked=True)
                good = ~np.ma.getmaskarray(tile)
                if not np.all(np.isfinite(np.asarray(tile)[good])):
                    raise DBIIndexMapPreflightError("Píxel científico válido no finito.")
                count = int(np.count_nonzero(good))
                valid += count
                masked += tile.size - count
            if valid <= 0:
                raise DBIIndexMapPreflightError("Índice sin píxeles científicos válidos.")
            return (digest, size, ds.crs.to_string(), transform, bounds, ds.width, ds.height, float(ds.nodata), valid, masked)
    except DBIIndexMapPreflightError:
        raise
    except (rasterio.errors.RasterioError, ValueError, OSError) as error:
        raise DBIIndexMapPreflightError("No se pudo validar COG científico.") from error


def inspect_six_index_maps(
    *,
    campaign_id: UUID,
    stack_fingerprint: str,
    files: Mapping[str, Mapping[str, str | Path]],
) -> DBISixIndexMapPreflight:
    """Valida seis pares COG/QML sin enlazar Campaign ni autorizar publicación."""
    if not isinstance(campaign_id, UUID) or not isinstance(stack_fingerprint, str) or not _SHA256_RE.fullmatch(stack_fingerprint):
        raise DBIIndexMapPreflightError("Identidad de Campaign o stack no canónica.")
    if not isinstance(files, Mapping) or set(files) != _INDEX_NAMES:
        raise DBIIndexMapPreflightError("Se exigen exactamente los seis índices registrados.")
    records: list[DBIIndexMapTechnicalEvidence] = []
    baseline: tuple[object, ...] | None = None
    raster_digests: set[str] = set()
    for index in SpectralIndex:
        spec = files[index.value]
        if not isinstance(spec, Mapping) or set(spec) != {"raster", "qml"}:
            raise DBIIndexMapPreflightError("Cada índice requiere raster y qml, sin campos adicionales.")
        raw_raster, raw_qml = spec["raster"], spec["qml"]
        if not all(isinstance(p, (str, Path)) for p in (raw_raster, raw_qml)):
            raise DBIIndexMapPreflightError("Las rutas locales deben ser texto o Path.")
        raster = Path(raw_raster)
        qml = Path(raw_qml)
        if raster.resolve() == qml.resolve():
            raise DBIIndexMapPreflightError("El COG y QML deben ser archivos distintos.")
        raster_sha, bytes_count, crs, affine, bounds, width, height, nodata, valid, masked = _inspect_cog(raster)
        style_sha, stop_count = _inspect_qml(qml)
        current_grid = (crs, affine, width, height, bounds)
        if baseline is None:
            baseline = current_grid
        elif current_grid != baseline:
            raise DBIIndexMapPreflightError("Los seis índices no comparten idéntica grilla geoespacial.")
        if raster_sha in raster_digests:
            raise DBIIndexMapPreflightError("Dos índices no pueden usar el mismo ráster científico.")
        raster_digests.add(raster_sha)
        definition = index_definition(index)
        records.append(DBIIndexMapTechnicalEvidence(
            index=index.value, formula_version=definition.formula_version,
            formula=definition.formula, raster_sha256=raster_sha, raster_bytes=bytes_count,
            qml_sha256=style_sha, qml_color_stops=stop_count,
            crs=crs, transform=affine, bounds=bounds, width=width, height=height,
            nodata=nodata, valid_pixels=valid, masked_pixels=masked,
        ))
    return DBISixIndexMapPreflight(
        schema_version="dbi-multi-six-maps-preflight.v1",
        campaign_id_claimed=str(campaign_id),
        stack_fingerprint_claimed=stack_fingerprint,
        disposition="technical_preflight_only_not_published",
        campaign_link_verified=False,
        source_calibration_verified=False,
        institutional_publication_authorized=False,
        indexes=tuple(records),
    )
