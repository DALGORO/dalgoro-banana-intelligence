"""Validación acotada de GeoJSON de visualización; nunca toca el archivo fuente."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass

from shapely.geometry import shape
from shapely.errors import GEOSException

MAX_VECTOR_BYTES = 2 * 1024 * 1024
MAX_VECTOR_FEATURES = 2500
MAX_VECTOR_VERTICES = 50000
_ALLOWED_GEOMETRIES = frozenset({
    "Point", "MultiPoint", "LineString", "MultiLineString",
    "Polygon", "MultiPolygon",
})
_BLOCKED_FIELDS = ("password", "secret", "token", "object_key", "path", "bucket", "credential", "sha", "file_url")


class DBIPortalVectorInvalid(ValueError):
    pass


@dataclass(frozen=True)
class ParsedVector:
    feature_count: int
    source_sha256: str
    geojson_text: str


def _coordinate_count(coords: object, *, depth: int = 0) -> int:
    if depth > 8 or not isinstance(coords, list) or not coords:
        raise DBIPortalVectorInvalid("Coordenadas GeoJSON inválidas.")
    if isinstance(coords[0], (int, float)) and not isinstance(coords[0], bool):
        if len(coords) not in (2, 3) or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in coords
        ):
            raise DBIPortalVectorInvalid("Coordenada inválida.")
        lon, lat = coords[:2]
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise DBIPortalVectorInvalid("El GeoJSON debe utilizar longitud/latitud WGS84.")
        return 1
    return sum(_coordinate_count(x, depth=depth + 1) for x in coords)


def _safe_properties(raw: object) -> dict[str, str | float | int | bool | None]:
    if not isinstance(raw, dict) or len(raw) > 50:
        raise DBIPortalVectorInvalid("Atributos GeoJSON inválidos.")
    safe = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not re.fullmatch(r"[\w -]{1,60}", key, flags=re.UNICODE):
            continue
        if any(part in key.lower() for part in _BLOCKED_FIELDS):
            continue
        if value is None or isinstance(value, bool):
            safe[key] = value
        elif isinstance(value, int) and abs(value) <= 10**12:
            safe[key] = value
        elif isinstance(value, float) and math.isfinite(value) and abs(value) <= 10**12:
            safe[key] = value
        elif isinstance(value, str) and len(value) <= 200 and "\x00" not in value:
            safe[key] = value
    return safe


def validate_portal_geojson(source: bytes) -> ParsedVector:
    if not (20 <= len(source) <= MAX_VECTOR_BYTES):
        raise DBIPortalVectorInvalid("El archivo excede 2 MB o está vacío.")
    try:
        data = json.loads(source.decode("utf-8-sig"), parse_constant=lambda _: None)
    except (UnicodeError, ValueError) as error:
        raise DBIPortalVectorInvalid("GeoJSON UTF-8 inválido.") from error

    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise DBIPortalVectorInvalid("Se requiere un GeoJSON FeatureCollection.")
    if data.get("crs") is not None:
        raise DBIPortalVectorInvalid("Se requiere GeoJSON RFC 7946 en WGS84, sin CRS heredado.")
    features = data.get("features")
    if not isinstance(features, list) or not 1 <= len(features) <= MAX_VECTOR_FEATURES:
        raise DBIPortalVectorInvalid("Se requieren 1 a 2500 entidades.")

    normalized = []
    total_vertices = 0
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise DBIPortalVectorInvalid("Entidad GeoJSON inválida.")
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") not in _ALLOWED_GEOMETRIES:
            raise DBIPortalVectorInvalid("Tipo de geometría no permitido.")
        total_vertices += _coordinate_count(geometry.get("coordinates"))
        if total_vertices > MAX_VECTOR_VERTICES:
            raise DBIPortalVectorInvalid("Demasiados vértices para el visor inicial.")
        try:
            geom = shape(geometry)
            if geom.is_empty or not geom.is_valid:
                raise DBIPortalVectorInvalid("Geometría inválida o vacía.")
        except (ValueError, TypeError, GEOSException, IndexError) as error:
            raise DBIPortalVectorInvalid("No se pudo validar la geometría.") from error
        normalized.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": _safe_properties(feature.get("properties") or {}),
        })
    output = json.dumps(
        {"type": "FeatureCollection", "features": normalized},
        separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    )
    if len(output.encode("utf-8")) > MAX_VECTOR_BYTES:
        raise DBIPortalVectorInvalid("La capa excede el límite de visualización.")
    return ParsedVector(
        feature_count=len(normalized),
        source_sha256=hashlib.sha256(source).hexdigest(),
        geojson_text=output,
    )
