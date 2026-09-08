"""Inicialización del backend DALGORO Banana Intelligence."""
from __future__ import annotations

import os


def _looks_like_postgis_proj(value: str) -> bool:
    normalized = value.replace("\\", "/").lower()
    return "postgresql" in normalized or "postgis" in normalized


# El backend puede arrancar desde una sesión de Windows donde PROJ_LIB/PROJ_DATA
# apuntan al catálogo incluido con PostgreSQL/PostGIS. Rasterio/pyproj del motor
# de densidad necesitan su propio catálogo PROJ, por lo que retiramos únicamente
# esas rutas incompatibles antes de lanzar cualquier subproceso del analizador.
for _name in ("PROJ_LIB", "PROJ_DATA"):
    _value = os.environ.get(_name, "").strip()
    if _value and _looks_like_postgis_proj(_value):
        os.environ.pop(_name, None)


__all__ = ["api", "core", "db", "models", "services"]
__version__ = "0.1.0"
