"""Conversor GIS offline seguro para publicar datos históricos en el visor DALGORO.

Ejecutar desde el entorno GeoPandas/Pyogrio del motor geoespacial, jamás desde
el proceso FastAPI. No crea Campaigns ni concede permisos a clientes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import struct
import sys
from tempfile import TemporaryDirectory, NamedTemporaryFile
from zipfile import ZipFile, BadZipFile

import pyogrio
from shapely import get_num_coordinates
from shapely.geometry import mapping

MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_ZIP_ENTRIES = 16
MAX_FEATURES = 2500
MAX_VERTICES = 50000
MAX_GEOJSON_BYTES = 2 * 1024 * 1024
ALLOWED_GEOMETRIES = frozenset({
    "Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon",
})
ALLOWED_SHP_EXTENSIONS = frozenset({".shp", ".shx", ".dbf", ".prj", ".cpg"})
PRIVATE_ATTRIBUTE_TOKENS = (
    "password", "secret", "token", "object_key", "path", "bucket",
    "credential", "sha", "file_url",
)


class PortalConversionError(ValueError):
    """Archivo geográfico no apto para publicar."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_source_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise PortalConversionError("Selecciona un archivo local regular, no un enlace.")
    if not 0 < path.stat().st_size <= MAX_SOURCE_BYTES:
        raise PortalConversionError("El archivo supera 128 MiB o está vacío.")
    if path.suffix.lower() not in (".gpkg", ".zip"):
        raise PortalConversionError("Solo se admiten .gpkg y .zip con un Shapefile completo.")


def _extract_shapefile(source: Path, directory: Path) -> Path:
    """Extrae una sola capa SHP con rutas y tamaños estrictamente limitados."""
    try:
        archive = ZipFile(source, "r")
    except BadZipFile as error:
        raise PortalConversionError("El ZIP no es válido.") from error

    with archive:
        items = [entry for entry in archive.infolist() if not entry.is_dir()]
        if not items or len(items) > MAX_ZIP_ENTRIES:
            raise PortalConversionError("El ZIP debe contener una única capa SHP (máximo 16 archivos).")

        logical_names: set[str] = set()
        shape_groups: dict[str, dict[str, object]] = {}
        total = 0
        for entry in items:
            name = entry.filename.replace("\\", "/")
            rel = PurePosixPath(name)
            mode = entry.external_attr >> 16
            if (
                name.startswith("/")
                or any(part in ("", ".", "..") for part in rel.parts)
                or ":" in name
                or stat.S_ISLNK(mode)
                or entry.flag_bits & 0x1
            ):
                raise PortalConversionError("ZIP con entrada insegura o cifrada.")
            extension = rel.suffix.lower()
            if extension not in ALLOWED_SHP_EXTENSIONS:
                raise PortalConversionError("El ZIP contiene archivos ajenos al Shapefile.")
            unique_name = str(rel).casefold()
            if unique_name in logical_names:
                raise PortalConversionError("Nombres duplicados en el ZIP.")
            logical_names.add(unique_name)
            stem = str(rel.with_suffix("")).casefold()
            shape_groups.setdefault(stem, {})[extension] = entry
            total += entry.file_size
            if (
                entry.file_size < 0
                or total > MAX_EXPANDED_BYTES
                or (entry.file_size > 0 and entry.file_size > max(entry.compress_size, 1) * 100)
            ):
                raise PortalConversionError("ZIP demasiado grande o potencial bomba ZIP.")

        if len(shape_groups) != 1:
            raise PortalConversionError("El ZIP debe incluir exactamente un Shapefile.")
        group = next(iter(shape_groups.values()))
        if not {".shp", ".shx", ".dbf", ".prj"}.issubset(group):
            raise PortalConversionError("Faltan .shp, .shx, .dbf o .prj.")

        shp_path: Path | None = None
        written = 0
        for entry in items:
            rel = PurePosixPath(entry.filename.replace("\\", "/"))
            target = directory.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry, "r") as reader, target.open("xb") as writer:
                while chunk := reader.read(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_EXPANDED_BYTES or writer.tell() + len(chunk) > entry.file_size:
                        raise PortalConversionError("Contenido expandido supera el límite autorizado.")
                    writer.write(chunk)
            if target.suffix.lower() == ".shp":
                shp_path = target

        if shp_path is None:
            raise PortalConversionError("No se encontró la geometría SHP.")
        with shp_path.open("rb") as stream:
            if struct.unpack(">I", stream.read(4))[0] != 9994:
                raise PortalConversionError("La firma del Shapefile es inválida.")
        return shp_path


def _selected_gpkg_layer(path: Path, wanted: str | None) -> str:
    with path.open("rb") as stream:
        if stream.read(16) != b"SQLite format 3\x00":
            raise PortalConversionError("El GeoPackage no tiene una cabecera SQLite válida.")
    try:
        available = [(str(row[0]), row[1]) for row in pyogrio.list_layers(path)]
    except Exception as error:
        raise PortalConversionError("No se pudo inspeccionar el catálogo GeoPackage.") from error

    spatial = [name for name, geometry_kind in available if geometry_kind is not None]
    if not spatial:
        raise PortalConversionError("El GeoPackage no contiene capas vectoriales.")
    if wanted is not None:
        if wanted not in spatial:
            raise PortalConversionError("La capa solicitada no existe o carece de geometrías.")
        return wanted
    if len(spatial) != 1:
        raise PortalConversionError(
            "Este GeoPackage tiene varias capas: indica --layer con el nombre exacto."
        )
    return spatial[0]


def _safe_properties(row: dict[str, object]) -> dict[str, object]:
    attrs: dict[str, object] = {}
    for name, original in row.items():
        if len(attrs) >= 50:
            break
        if not isinstance(name, str) or not 1 <= len(name) <= 60:
            continue
        if any(token in name.lower() for token in PRIVATE_ATTRIBUTE_TOKENS):
            continue
        value = original.item() if hasattr(original, "item") else original
        if value is None:
            attrs[name] = None
        elif isinstance(value, bool):
            attrs[name] = value
        elif isinstance(value, int) and abs(value) <= 10**12:
            attrs[name] = value
        elif isinstance(value, float) and math.isfinite(value) and abs(value) <= 10**12:
            attrs[name] = value
        elif isinstance(value, str) and len(value) <= 200 and "\x00" not in value:
            attrs[name] = value
    return attrs


def _write_exclusive_atomic(path: Path, data: bytes) -> None:
    """Crea un derivado nuevo sin sustituir archivos existentes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".dbi-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)  # Falla si ya existe: no modifica datos anteriores.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def convert_vector_for_portal(source: Path, output: Path, *, layer: str | None = None) -> dict[str, object]:
    """Convierte GPKG/ZIP SHP existente a FeatureCollection WGS84 pequeña.

    No publica automáticamente la capa: un administrador autorizado debe
    vincular el GeoJSON a la Campaign real en el portal.
    """
    source = source.resolve(strict=True)
    _validate_source_file(source)
    if output.suffix.lower() != ".geojson":
        raise PortalConversionError("El archivo resultante debe terminar en .geojson.")
    if output.exists() or output.with_suffix(".manifest.json").exists():
        raise PortalConversionError("El derivado o su manifiesto ya existen; no se sobrescriben.")

    with TemporaryDirectory(prefix="dbi-portal-gis-") as scratch:
        import_path: Path = source
        requested_layer = layer
        if source.suffix.lower() == ".zip":
            if layer is not None:
                raise PortalConversionError("--layer se utiliza solo con GeoPackage.")
            import_path = _extract_shapefile(source, Path(scratch))
            requested_layer = None
        else:
            requested_layer = _selected_gpkg_layer(source, layer)

        try:
            df = pyogrio.read_dataframe(
                import_path, layer=requested_layer, max_features=MAX_FEATURES + 1,
            )
        except Exception as error:
            raise PortalConversionError("No se pudieron leer las geometrías GIS.") from error

        if len(df) == 0 or len(df) > MAX_FEATURES:
            raise PortalConversionError("Solo se aceptan capas con 1 a 2500 entidades.")
        if df.crs is None:
            raise PortalConversionError("No existe CRS confiable; se requiere .prj o SRS GPKG.")
        source_crs = str(df.crs)
        try:
            projected = df.to_crs("EPSG:4326")
        except Exception as error:
            raise PortalConversionError("No se pudo reproyectar de forma verificable a WGS84.") from error

        features = []
        vertices = 0
        data_columns = [col for col in projected.columns if col != projected.geometry.name]
        for _, row in projected.iterrows():
            geom = row[projected.geometry.name]
            if (
                geom is None or geom.is_empty or not geom.is_valid
                or geom.geom_type not in ALLOWED_GEOMETRIES
            ):
                raise PortalConversionError("La capa contiene geometrías nulas, inválidas o incompatibles.")
            left, bottom, right, top = geom.bounds
            if not all(math.isfinite(v) for v in (left, bottom, right, top)):
                raise PortalConversionError("Geometrías con coordenadas no finitas.")
            if not (-180 <= left <= right <= 180 and -90 <= bottom <= top <= 90):
                raise PortalConversionError("Las geometrías no tienen coordenadas válidas WGS84.")
            vertices += int(get_num_coordinates(geom))
            if vertices > MAX_VERTICES:
                raise PortalConversionError("Demasiados vértices; simplifica o divide la capa en QGIS.")
            properties = _safe_properties({column: row[column] for column in data_columns})
            features.append({
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": properties,
            })

    raw = json.dumps(
        {"type": "FeatureCollection", "features": features},
        ensure_ascii=False, allow_nan=False, separators=(",", ":"),
    ).encode("utf-8")
    if len(raw) > MAX_GEOJSON_BYTES:
        raise PortalConversionError("Resultado mayor a 2 MiB; divide la capa para el visor.")
    manifest = {
        "schema_version": "dbi-portal-gis-conversion.v1",
        "input_format": "shapefile_zip" if source.suffix.lower() == ".zip" else "geopackage",
        "input_layer": requested_layer if source.suffix.lower() == ".gpkg" else None,
        "original_crs": source_crs,
        "output_crs": "EPSG:4326",
        "feature_count": len(features),
        "vertex_count": vertices,
        "source_sha256": _sha256(source),
        "output_sha256": hashlib.sha256(raw).hexdigest(),
    }
    metadata_path = output.with_suffix(".manifest.json")
    _write_exclusive_atomic(output, raw)
    try:
        _write_exclusive_atomic(
            metadata_path, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convertir GeoPackage o ZIP Shapefile a GeoJSON para DALGORO.",
    )
    parser.add_argument("--input", required=True, type=Path, help="Ruta local .gpkg o .zip SHP")
    parser.add_argument("--output", required=True, type=Path, help="GeoJSON de salida (nuevo)")
    parser.add_argument("--layer", help="Capa concreta cuando el GPKG tiene varias")
    options = parser.parse_args()
    try:
        info = convert_vector_for_portal(options.input, options.output, layer=options.layer)
    except (PortalConversionError, OSError) as error:
        parser.exit(2, f"No se publicó ningún archivo. {error}\n")
    print(f"GeoJSON listo: {info['feature_count']} elementos, WGS84. Requiere publicación autorizada en el portal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
