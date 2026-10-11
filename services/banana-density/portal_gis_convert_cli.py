"""Conversor LOCAL aislado de GeoPackage y Shapefile ZIP a GeoJSON DBI.

No importa este módulo desde FastAPI. Utiliza el entorno geoespacial
existente en services/banana-density, sin ejecutar análisis de densidad.
Los archivos fuente nunca se modifican.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pyogrio
from shapely.geometry import mapping

MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_GEOJSON_BYTES = 2 * 1024 * 1024
MAX_FEATURES = 2500
MAX_VERTICES = 50000
ALLOWED_GEOMETRIES = frozenset({
    "Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon",
})
ALLOWED_SIDECARS = frozenset({
    ".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn", ".sbx",
})
REQUIRED_SIDECARS = frozenset({".shp", ".shx", ".dbf", ".prj"})
PRIVATE_PROPERTY_FRAGMENTS = (
    "password", "secret", "token", "object_key", "path", "bucket",
    "credential", "sha", "file_url",
)


class PortalGISConversionError(ValueError):
    pass


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_stem(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-")
    return normalized[:80] or "capa"


def _prepare_shapefile(source: Path, dest: Path) -> Path:
    """Valida y descomprime exclusivamente un Shapefile plano y único."""
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as error:
        raise PortalGISConversionError("ZIP de Shapefile corrupto.") from error

    with archive:
        entries = [info for info in archive.infolist() if not info.is_dir()]
        if not 4 <= len(entries) <= 30:
            raise PortalGISConversionError("El ZIP debe contener un Shapefile y sus archivos asociados.")
        total = 0
        names = set()
        stems: set[str] = set()
        suffixes: set[str] = set()
        for info in entries:
            if info.flag_bits & 0x1:
                raise PortalGISConversionError("No se admiten ZIP cifrados.")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise PortalGISConversionError("El ZIP usa una compresión no admitida.")
            name = info.filename
            posix = Path(name)
            if (
                name.startswith(("/", "\\"))
                or "\\" in name
                or len(posix.parts) != 1
                or posix.name in {"", ".", ".."}
                or name.startswith(".")
                or (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK
            ):
                raise PortalGISConversionError("El ZIP contiene rutas o enlaces no permitidos.")
            if posix.suffix.lower() not in ALLOWED_SIDECARS:
                raise PortalGISConversionError("El ZIP contiene archivos que no son parte del Shapefile.")
            if posix.name.lower() in names:
                raise PortalGISConversionError("El ZIP contiene nombres duplicados.")
            names.add(posix.name.lower())
            stems.add(posix.stem.lower())
            suffixes.add(posix.suffix.lower())
            total += info.file_size
            if (
                info.file_size <= 0
                or info.file_size > MAX_SOURCE_BYTES
                or total > MAX_UNCOMPRESSED_BYTES
                or info.file_size > 100 * max(info.compress_size, 1)
            ):
                raise PortalGISConversionError("ZIP excesivamente grande o comprimido.")
        if len(stems) != 1 or not REQUIRED_SIDECARS.issubset(suffixes):
            raise PortalGISConversionError("Se requiere un único .shp/.shx/.dbf/.prj con el mismo nombre.")

        for info in entries:
            target = dest / Path(info.filename).name
            with archive.open(info) as raw, target.open("wb") as out:
                shutil.copyfileobj(raw, out, length=1024 * 1024)
            if target.stat().st_size != info.file_size:
                raise PortalGISConversionError("La extracción del ZIP quedó incompleta.")
        return next(dest.glob("*.shp")) if list(dest.glob("*.shp")) else next(
            p for p in dest.iterdir() if p.suffix.lower() == ".shp"
        )


def _safe_properties(properties: dict) -> dict:
    if len(properties) > 50:
        raise PortalGISConversionError("Demasiados atributos en la capa.")
    result: dict = {}
    for key, value in properties.items():
        if not isinstance(value, (type(None), bool, int, float, str)) and hasattr(value, "item"):
            try:
                value = value.item()
            except (TypeError, ValueError):
                continue
        if not isinstance(key, str) or not re.fullmatch(r"[\w -]{1,60}", key, flags=re.UNICODE):
            continue
        if any(frag in key.lower() for frag in PRIVATE_PROPERTY_FRAGMENTS):
            continue
        if value is None or isinstance(value, bool):
            result[key] = value
        elif isinstance(value, int) and abs(value) <= 10**12:
            result[key] = value
        elif isinstance(value, float) and math.isfinite(value) and abs(value) <= 10**12:
            result[key] = value
        elif isinstance(value, str) and len(value) <= 200 and "\x00" not in value:
            result[key] = value
    return result


def _count_vertices(coords: object, depth: int = 0) -> int:
    if depth > 8 or not isinstance(coords, (tuple, list)) or not coords:
        raise PortalGISConversionError("La geometría tiene coordenadas inválidas.")
    if isinstance(coords[0], (int, float)):
        if len(coords) not in (2, 3) or not all(
            isinstance(x, (int, float)) and math.isfinite(x) for x in coords
        ):
            raise PortalGISConversionError("Se detectaron coordenadas no finitas.")
        x, y = coords[:2]
        if not (-180 <= x <= 180 and -90 <= y <= 90):
            raise PortalGISConversionError("La reproyección WGS84 produjo coordenadas inválidas.")
        return 1
    return sum(_count_vertices(part, depth + 1) for part in coords)


def _read_vector(input_path: Path, layer: str | None):
    layers = [
        str(name) for name, geometry_type in pyogrio.list_layers(input_path)
        if geometry_type is not None
    ]
    if not layers:
        raise PortalGISConversionError("El archivo no contiene capas vectoriales geométricas.")
    if layer is None:
        if len(layers) != 1:
            raise PortalGISConversionError(
                "El GeoPackage contiene varias capas; indica --layer. Opciones: "
                + ", ".join(layers[:10])
            )
        layer = layers[0]
    elif layer not in layers:
        raise PortalGISConversionError("La capa solicitada no existe en el archivo.")

    try:
        frame = pyogrio.read_dataframe(input_path, layer=layer, max_features=MAX_FEATURES + 1)
    except Exception as error:
        raise PortalGISConversionError("No se pudo leer la capa mediante Pyogrio.") from error

    if len(frame) < 1 or len(frame) > MAX_FEATURES:
        raise PortalGISConversionError("La capa debe contener entre 1 y 2500 entidades.")
    if frame.crs is None:
        raise PortalGISConversionError("La capa carece de CRS verificable (.prj en SHP).")
    source_crs = str(frame.crs)
    try:
        frame = frame.to_crs("EPSG:4326")
    except Exception as error:
        raise PortalGISConversionError("No fue posible reproyectar a EPSG:4326.") from error
    return frame, source_crs, layer


def convert_vector(source: Path, output_dir: Path, *, layer: str | None = None) -> tuple[Path, Path]:
    """Crea derivado visual y manifiesto, sin tocar el GPKG/ZIP original."""
    source = Path(source)
    output_dir = Path(output_dir)
    if not source.is_file() or source.is_symlink():
        raise PortalGISConversionError("Selecciona un archivo local válido.")
    if source.suffix.lower() not in {".gpkg", ".zip"}:
        raise PortalGISConversionError("Admite GeoPackage .gpkg o Shapefile empaquetado .zip.")
    if not 1 <= source.stat().st_size <= MAX_SOURCE_BYTES:
        raise PortalGISConversionError("El archivo fuente supera el límite de 50 MB.")
    if source.suffix.lower() == ".gpkg":
        with source.open("rb") as inp:
            if inp.read(16) != b"SQLite format 3\x00":
                raise PortalGISConversionError("No es un GeoPackage SQLite válido.")

    original_hash = _hash_file(source)
    with tempfile.TemporaryDirectory(prefix="dbi-gis-") as stage:
        input_path = (
            _prepare_shapefile(source, Path(stage))
            if source.suffix.lower() == ".zip" else source
        )
        frame, source_crs, layer_name = _read_vector(input_path, layer)

        features: list[dict] = []
        vertex_count = 0
        for _, row in frame.iterrows():
            geometry = row.geometry
            if geometry is None or geometry.is_empty or not geometry.is_valid:
                raise PortalGISConversionError("La capa contiene geometrías inválidas.")
            if geometry.geom_type not in ALLOWED_GEOMETRIES:
                raise PortalGISConversionError("Se encontraron tipos geométricos no admitidos.")
            geo = mapping(geometry)
            vertex_count += _count_vertices(geo["coordinates"])
            if vertex_count > MAX_VERTICES:
                raise PortalGISConversionError("La capa supera 50.000 vértices.")
            features.append({
                "type": "Feature",
                "geometry": geo,
                "properties": _safe_properties(
                    {key: value for key, value in row.items() if key != frame.geometry.name}
                ),
            })
        payload = json.dumps(
            {"type": "FeatureCollection", "features": features},
            ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        if len(payload) > MAX_GEOJSON_BYTES:
            raise PortalGISConversionError(
                "El GeoJSON supera 2 MB; divide la capa para importarla al portal."
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        stem = _safe_stem(source.stem) + "-" + _safe_stem(layer_name) + "-" + original_hash[:12]
        output_path = output_dir / f"{stem}.geojson"
        manifest_path = output_dir / f"{stem}.manifest.json"
        manifest = {
            "schema_version": "dbi-portal-gis-conversion.v1",
            "source_filename": source.name,
            "source_sha256": original_hash,
            "source_crs": source_crs,
            "source_layer": layer_name,
            "source_size_bytes": source.stat().st_size,
            "output_sha256": hashlib.sha256(payload).hexdigest(),
            "feature_count": len(features),
            "output_crs": "EPSG:4326",
            "converted_at_utc": datetime.now(timezone.utc).isoformat(),
            "captured_at": None,
            "note": "La fecha de vuelo debe verificarse antes de asociar la Campaign.",
        }
        manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")

        # El derivado tiene nombre determinado por la huella de fuente:
        # un reintento no altera los bytes de un archivo previo diferente.
        if output_path.exists() and output_path.read_bytes() != payload:
            raise PortalGISConversionError("Conflicto con un derivado existente; no se sobrescribe.")
        if not output_path.exists():
            with tempfile.NamedTemporaryFile(
                dir=output_dir, prefix=".dbi-", suffix=".tmp", delete=False
            ) as temporary:
                temporary.write(payload)
                staging = Path(temporary.name)
            try:
                staging.replace(output_path)
            finally:
                staging.unlink(missing_ok=True)
        if not manifest_path.exists():
            manifest_path.write_bytes(manifest_bytes)
        return output_path, manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Convertir SHP ZIP o GPKG a GeoJSON para el portal DALGORO.")
    parser.add_argument("source", type=Path, help="Archivo original .gpkg o .zip")
    parser.add_argument("--output-dir", type=Path, required=True, help="Carpeta donde guardar el derivado")
    parser.add_argument("--layer", type=str, help="Nombre exacto de capa en un GeoPackage multicapa")
    args = parser.parse_args()
    try:
        output, manifest = convert_vector(args.source, args.output_dir, layer=args.layer)
    except (PortalGISConversionError, OSError) as error:
        parser.exit(2, f"Error de conversión: {error}\n")
    print(f"GeoJSON preparado: {output}")
    print(f"Ficha de procedencia: {manifest}")
    print("Conserva el archivo original. Sube el GeoJSON desde el visor de la Campaign correcta.")


if __name__ == "__main__":
    main()
