"""Saneamiento conservador del entorno PROJ para el backend DBI local.

Windows puede exponer PROJ_LIB/PROJ_DATA apuntando al PROJ incluido con
PostgreSQL/PostGIS. Ese catálogo puede ser incompatible con rasterio/pyproj del
motor de densidad, y los procesos hijos heredan esas variables desde FastAPI.

Solo retiramos las variables cuando identificamos explícitamente una ruta de
PostgreSQL/PostGIS. Cualquier configuración PROJ ajena se conserva intacta.
"""
from __future__ import annotations

import os


def _looks_like_postgis_proj(value: str) -> bool:
    normalized = value.replace("\\", "/").lower()
    return "postgresql" in normalized or "postgis" in normalized


for _name in ("PROJ_LIB", "PROJ_DATA"):
    _value = os.environ.get(_name, "").strip()
    if _value and _looks_like_postgis_proj(_value):
        os.environ.pop(_name, None)
