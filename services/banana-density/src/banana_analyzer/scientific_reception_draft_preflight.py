"""Puente OFFLINE desde el borrador H14 al preflight REAL COG/QML H13.

No usa HTTP, DB, permisos de publicación ni modifica archivos fuente. Identidades
Campaign/tenant/org son declaraciones hasta cotejo transaccional con DBI.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
from pathlib import Path
import re
from typing import Mapping
from uuid import UUID

import rasterio
from rasterio.warp import transform_bounds

from banana_analyzer.multispectral_indices import SpectralIndex
from banana_analyzer.multispectral_map_preflight import (
    DBISixIndexMapPreflight,
    inspect_six_index_maps,
)

_SHA = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_FLAGS = (
    "scientific_validated", "server_received", "institutional_approved", "published",
)
_EXPECTED_ROLES = {("rgb", None)} | {
    (role, index.value)
    for index in SpectralIndex
    for role in ("scientific_cog", "qml_style")
}


class DBIScientificDraftPreflightError(ValueError):
    """El borrador local o los archivos originales no pueden validarse."""


@dataclass(frozen=True, slots=True)
class DBIScientificDraftPreflightEvidence:
    schema_version: str
    disposition: str
    campaign_id_claimed: str
    tenant_ref_claimed: str
    organization_ref_claimed: str
    farm_id_claimed: str
    plot_id_claimed: str
    campaign_link_verified: bool
    source_provenance_verified: bool
    rgb_semantic_bands_verified: bool
    institutional_publication_authorized: bool
    rgb_source_sha256: str
    rgb_source_bytes: int
    rgb_source_crs: str
    rgb_source_bounds: tuple[float, float, float, float]
    rgb_multispectral_extent_intersects: bool
    index_map_preflight: DBISixIndexMapPreflight


def _require_mapping(value: object, expected: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise DBIScientificDraftPreflightError(f"{label} contiene campos inesperados o faltantes.")
    return value


def _canonical_label(value: object, label: str) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= 128
            or value != value.strip() or "*" in value
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
        raise DBIScientificDraftPreflightError(f"{label} no es canónico.")
    return value


def _uuid(value: object, label: str) -> UUID:
    if not isinstance(value, str):
        raise DBIScientificDraftPreflightError(f"{label} no es UUID.")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise DBIScientificDraftPreflightError(f"{label} no es UUID.") from error
    if str(parsed) != value.lower():
        raise DBIScientificDraftPreflightError(f"{label} debe ser UUID canónico.")
    return parsed


def _local_root(value: object, declared: object, label: str) -> Path:
    if not isinstance(value, (str, Path)) or not isinstance(declared, str):
        raise DBIScientificDraftPreflightError(f"{label} no identifica una carpeta.")
    if declared in {"", ".", ".."} or "/" in declared or "\\" in declared:
        raise DBIScientificDraftPreflightError(f"{label} de carpeta inválido.")
    root = Path(value).expanduser()
    if not root.is_dir() or root.is_symlink() or root.name != declared:
        raise DBIScientificDraftPreflightError(f"{label} real no coincide con el borrador.")
    return root.resolve(strict=True)


def _safe_original(root: Path, prefix: str, value: object) -> Path:
    if not isinstance(value, str) or not value.startswith(prefix + "/") or "\\" in value:
        raise DBIScientificDraftPreflightError("Ruta de archivo no pertenece a su carpeta.")
    segments = value.split("/")
    if (len(segments) < 2 or any(
        segment in {"", ".", ".."} or
        any(ord(ch) < 32 or ord(ch) == 127 for ch in segment)
        for segment in segments
    )):
        raise DBIScientificDraftPreflightError("Ruta relativa insegura en borrador.")
    target = root
    for segment in segments[1:]:
        target = target / segment
        if target.is_symlink():
            raise DBIScientificDraftPreflightError("No se admiten enlaces simbólicos del archivo.")
    if not target.is_file() or not target.resolve(strict=True).is_relative_to(root):
        raise DBIScientificDraftPreflightError("Original no encontrado dentro de su carpeta.")
    return target


def _rgb_source_metadata(path: Path) -> tuple[str, int, str, tuple[float, float, float, float]]:
    digest = sha256()
    total = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            total += len(chunk)
            digest.update(chunk)
    if total <= 0:
        raise DBIScientificDraftPreflightError("Ortofoto RGB vacía.")
    try:
        with rasterio.open(path) as ds:
            if (ds.driver != "GTiff" or ds.count not in {3, 4}
                    or any(dtype not in {"uint8", "uint16"} for dtype in ds.dtypes)
                    or ds.crs is None or ds.transform.is_identity
                    or ds.width <= 0 or ds.height <= 0):
                raise DBIScientificDraftPreflightError("RGB debe ser GeoTIFF de 3/4 bandas y CRS real.")
            bounds = tuple(float(x) for x in ds.bounds)
            if (not all(math.isfinite(x) for x in bounds)
                    or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
                raise DBIScientificDraftPreflightError("Extensión RGB inválida.")
            return digest.hexdigest(), total, ds.crs.to_string(), bounds
    except DBIScientificDraftPreflightError:
        raise
    except (rasterio.errors.RasterioError, OSError, ValueError) as error:
        raise DBIScientificDraftPreflightError("No se pudo leer la ortofoto RGB.") from error


def inspect_scientific_reception_draft(
    *,
    draft: Mapping[str, object],
    geospatial_root: str | Path,
    multispectral_root: str | Path,
    stack_fingerprint_claimed: str,
) -> DBIScientificDraftPreflightEvidence:
    """Exige 13 originales, valida RGB y seis COG/QML, NO firma su Campaign."""
    if not isinstance(draft, Mapping):
        raise DBIScientificDraftPreflightError("Borrador JSON inválido.")
    _require_mapping(draft, {
        "schema_version", "state", "scope", "folders", "files", "blockers",
        "structural_ready", *_EXPECTED_FLAGS,
    }, "Borrador")
    if (draft["schema_version"] != "dbi-h14-scientific-reception-draft.v1"
            or draft["state"] != "local_metadata_only_not_uploaded"
            or draft["structural_ready"] is not True
            or draft["blockers"] != []
            or any(draft[flag] is not False for flag in _EXPECTED_FLAGS)):
        raise DBIScientificDraftPreflightError("Borrador no está completo o afirma publicación.")
    if not isinstance(stack_fingerprint_claimed, str) or not _SHA.fullmatch(stack_fingerprint_claimed):
        raise DBIScientificDraftPreflightError("Fingerprint declarado no canónico.")
    scope = _require_mapping(draft["scope"], {
        "tenant_ref", "organization_ref", "farm_id", "plot_id", "campaign_id",
    }, "Scope")
    tenant = _canonical_label(scope["tenant_ref"], "tenant_ref")
    organization = _canonical_label(scope["organization_ref"], "organization_ref")
    farm = _uuid(scope["farm_id"], "farm_id")
    plot = _uuid(scope["plot_id"], "plot_id")
    campaign = _uuid(scope["campaign_id"], "campaign_id")
    folders = _require_mapping(draft["folders"], {"geospatial", "multispectral"}, "Carpetas")
    roots = {
        "geospatial": _local_root(geospatial_root, folders["geospatial"], "geospatial"),
        "multispectral": _local_root(multispectral_root, folders["multispectral"], "multispectral"),
    }
    if roots["geospatial"] == roots["multispectral"]:
        raise DBIScientificDraftPreflightError("Las dos carpetas no pueden ser idénticas.")
    records = draft["files"]
    if not isinstance(records, list) or len(records) != 13:
        raise DBIScientificDraftPreflightError("Se requieren exactamente 13 originales.")
    seen_roles: set[tuple[str, str | None]] = set()
    seen_paths: set[str] = set()
    paths: dict[tuple[str, str | None], Path] = {}
    for record in records:
        item = _require_mapping(record, {
            "folder", "role", "index", "relative_path", "size_bytes",
            "sha256", "file_content_verified",
        }, "Archivo")
        kind, role, index = item["folder"], item["role"], item["index"]
        if (not isinstance(kind, str) or kind not in roots
                or not isinstance(role, str) or not (index is None or isinstance(index, str))
                or (role, index) not in _EXPECTED_ROLES
                or kind != ("geospatial" if role == "rgb" else "multispectral")
                or (role, index) in seen_roles):
            raise DBIScientificDraftPreflightError("Rol o índice duplicado/ilegítimo.")
        if (item["sha256"] is not None or item["file_content_verified"] is not False
                or type(item["size_bytes"]) is not int or item["size_bytes"] <= 0):
            raise DBIScientificDraftPreflightError("Un borrador no acredita hashes ni admite tamaño inválido.")
        path = _safe_original(roots[kind], folders[kind], item["relative_path"])
        key = str(path).casefold()
        if key in seen_paths or path.stat().st_size != item["size_bytes"]:
            raise DBIScientificDraftPreflightError("Archivo duplicado o tamaño cambiado desde selección.")
        suffix = path.suffix.lower()
        if (role in {"rgb", "scientific_cog"} and suffix not in {".tif", ".tiff"}) or (
            role == "qml_style" and suffix != ".qml"
        ):
            raise DBIScientificDraftPreflightError("Formato no corresponde al rol declarado.")
        seen_roles.add((role, index))
        seen_paths.add(key)
        paths[(role, index)] = path
    if seen_roles != _EXPECTED_ROLES:
        raise DBIScientificDraftPreflightError("Faltan roles obligatorios en el borrador.")
    index_files = {
        idx.value: {
            "raster": paths[("scientific_cog", idx.value)],
            "qml": paths[("qml_style", idx.value)],
        }
        for idx in SpectralIndex
    }
    result = inspect_six_index_maps(
        campaign_id=campaign, stack_fingerprint=stack_fingerprint_claimed,
        files=index_files,
    )
    rgb_sha, rgb_bytes, rgb_crs, rgb_bounds = _rgb_source_metadata(paths[("rgb", None)])
    rgb_extent = transform_bounds(rgb_crs, "EPSG:4326", *rgb_bounds, densify_pts=21)
    index0 = result.indexes[0]
    multi_extent = transform_bounds(index0.crs, "EPSG:4326", *index0.bounds, densify_pts=21)
    intersection = (
        min(rgb_extent[2], multi_extent[2]) > max(rgb_extent[0], multi_extent[0])
        and min(rgb_extent[3], multi_extent[3]) > max(rgb_extent[1], multi_extent[1])
    )
    if not intersection:
        raise DBIScientificDraftPreflightError("RGB y seis índices no se superponen geográficamente.")
    if paths[("rgb", None)].stat().st_size != rgb_bytes:
        raise DBIScientificDraftPreflightError("El original RGB cambió durante la inspección.")
    return DBIScientificDraftPreflightEvidence(
        schema_version="dbi-h14-scientific-draft-preflight.v1",
        disposition="offline_technical_evidence_only_not_published",
        campaign_id_claimed=str(campaign),
        tenant_ref_claimed=tenant, organization_ref_claimed=organization,
        farm_id_claimed=str(farm), plot_id_claimed=str(plot),
        campaign_link_verified=False, source_provenance_verified=False,
        rgb_semantic_bands_verified=False, institutional_publication_authorized=False,
        rgb_source_sha256=rgb_sha, rgb_source_bytes=rgb_bytes,
        rgb_source_crs=rgb_crs, rgb_source_bounds=rgb_bounds,
        rgb_multispectral_extent_intersects=True, index_map_preflight=result,
    )
