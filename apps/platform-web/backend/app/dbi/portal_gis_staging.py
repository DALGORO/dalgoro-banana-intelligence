"""Validación binaria ligera del archivo GIS ANTES de colocarlo en cuarentena privada.

No importa GDAL, no descomprime el ZIP, no analiza geometrías.
La conversión final queda reservada al worker aislado.
"""
from __future__ import annotations
from pathlib import Path
import re
import stat
from typing import BinaryIO
from zipfile import ZipFile, BadZipFile

MAX_GIS_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_GIS_ZIP_EXPANDED_BYTES = 100 * 1024 * 1024
_MAX_ENTRIES = 30
_ALLOWED_SHP = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn", ".sbx"}
_REQUIRED_SHP = {".shp", ".shx", ".dbf", ".prj"}


class PortalGISSourceInvalid(ValueError):
    pass


def normalize_upload_filename(filename: str) -> tuple[str, str, str]:
    if (
        not filename or len(filename) > 100
        or filename in (".", "..")
        or any(ord(c) < 32 or ord(c) == 127 for c in filename)
        or "/" in filename or "\\" in filename or ":" in filename
        or not re.fullmatch(r"[\w .()-]{1,100}", filename, flags=re.UNICODE)
    ):
        raise PortalGISSourceInvalid("Nombre de archivo inválido.")
    suffix = Path(filename).suffix.lower()
    if suffix == ".gpkg":
        return filename, "gpkg", "application/geopackage+sqlite3"
    if suffix == ".zip":
        return filename, "shp_zip", "application/zip"
    raise PortalGISSourceInvalid("Selecciona un GeoPackage .gpkg o Shapefile .zip.")


def validate_staged_source(content: BinaryIO, source_format: str) -> None:
    content.seek(0)
    signature = content.read(16)
    content.seek(0)
    if source_format == "gpkg":
        if signature != b"SQLite format 3\x00":
            raise PortalGISSourceInvalid("El archivo no tiene cabecera GeoPackage válida.")
        return
    if source_format != "shp_zip" or not signature.startswith(b"PK\x03\x04"):
        raise PortalGISSourceInvalid("El archivo no es un ZIP Shapefile válido.")

    try:
        with ZipFile(content) as archive:
            entries = archive.infolist()
            if len(entries) < 4 or len(entries) > _MAX_ENTRIES:
                raise PortalGISSourceInvalid("El ZIP debe contener un único Shapefile completo.")
            total = 0
            names: set[str] = set()
            stems: set[str] = set()
            suffixes: set[str] = set()
            for item in entries:
                filename = item.filename
                if (
                    item.is_dir() or item.flag_bits & 1
                    or "/" in filename or "\\" in filename or ":" in filename
                    or filename.startswith(".")
                    or (item.external_attr >> 16) & 0o170000 == stat.S_IFLNK
                ):
                    raise PortalGISSourceInvalid("ZIP con ruta, enlace o archivo cifrado inseguro.")
                suffix = Path(filename).suffix.lower()
                if suffix not in _ALLOWED_SHP:
                    raise PortalGISSourceInvalid("ZIP contiene archivos ajenos a Shapefile.")
                key = filename.casefold()
                if key in names:
                    raise PortalGISSourceInvalid("ZIP contiene nombres duplicados.")
                names.add(key)
                stems.add(Path(filename).stem.casefold())
                suffixes.add(suffix)
                total += item.file_size
                if (
                    item.file_size <= 0
                    or total > MAX_GIS_ZIP_EXPANDED_BYTES
                    or item.file_size > 100 * max(item.compress_size, 1)
                ):
                    raise PortalGISSourceInvalid("ZIP demasiado grande o comprimido.")
            if len(stems) != 1 or not _REQUIRED_SHP.issubset(suffixes):
                raise PortalGISSourceInvalid("Faltan .shp, .shx, .dbf o .prj.")
    except (BadZipFile, OSError, EOFError) as exc:
        raise PortalGISSourceInvalid("No se pudo abrir el ZIP de Shapefile.") from exc
    finally:
        content.seek(0)
