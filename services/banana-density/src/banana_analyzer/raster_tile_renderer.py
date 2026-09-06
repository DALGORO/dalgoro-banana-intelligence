"""Renderer aislado de tiles para COG privados DBI.

Rasterio/GDAL permanece en ``banana-density``. La ruta recibida por este módulo es
un detalle interno ya resuelto por infraestructura autorizada; nunca proviene del
cliente HTTP ni se devuelve en el resultado.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds

_WEB_MERCATOR_CRS = "EPSG:3857"
_WEB_MERCATOR_HALF_WORLD = 20037508.342789244
_DEFAULT_TILE_SIZE = 256
_MAX_ZOOM = 22


class RasterTileRenderError(RuntimeError):
    """El producto o la solicitud interna no puede renderizarse con seguridad."""


class RasterTileOutsideExtent(RasterTileRenderError):
    """El tile XYZ no intersecta el producto fuente."""


@dataclass(frozen=True, slots=True)
class RasterTileStyle:
    style_id: str
    render_mode: Literal["rgb", "single_band"]
    band_indexes: tuple[int, ...]
    display_min: float | None = None
    display_max: float | None = None


@dataclass(frozen=True, slots=True)
class RasterTileRenderResult:
    data: bytes
    content_type: Literal["image/png"]
    width: int
    height: int
    target_crs: Literal["EPSG:3857"]
    source_band_count: int
    source_dtype: tuple[str, ...]
    source_overview_levels: tuple[int, ...]


def xyz_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Devuelve bounds Web Mercator para un tile XYZ validado."""

    if not isinstance(z, int) or isinstance(z, bool) or z < 0 or z > _MAX_ZOOM:
        raise RasterTileRenderError("z queda fuera de política.")
    limit = 1 << z
    for name, value in (("x", x), ("y", y)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value >= limit:
            raise RasterTileRenderError(f"{name} queda fuera del rango XYZ.")

    span = (2.0 * _WEB_MERCATOR_HALF_WORLD) / limit
    left = -_WEB_MERCATOR_HALF_WORLD + x * span
    right = left + span
    top = _WEB_MERCATOR_HALF_WORLD - y * span
    bottom = top - span
    return (left, bottom, right, top)


def _validate_style(style: RasterTileStyle, *, band_count: int) -> RasterTileStyle:
    if not isinstance(style, RasterTileStyle):
        raise RasterTileRenderError("style debe ser RasterTileStyle.")
    if not style.style_id or style.style_id != style.style_id.strip():
        raise RasterTileRenderError("style_id no es canónico.")
    if any(
        not isinstance(index, int)
        or isinstance(index, bool)
        or index <= 0
        or index > band_count
        for index in style.band_indexes
    ):
        raise RasterTileRenderError("El estilo referencia una banda inexistente.")
    if style.render_mode == "rgb":
        if len(style.band_indexes) != 3 or style.display_min is not None or style.display_max is not None:
            raise RasterTileRenderError("rgb requiere tres bandas sin stretch científico.")
    elif style.render_mode == "single_band":
        if len(style.band_indexes) != 1:
            raise RasterTileRenderError("single_band requiere una banda.")
        if style.display_min is None or style.display_max is None:
            raise RasterTileRenderError("single_band requiere límites de visualización.")
        if float(style.display_max) <= float(style.display_min):
            raise RasterTileRenderError("display_max debe superar display_min.")
    else:
        raise RasterTileRenderError("render_mode no soportado.")
    return style


def _intersects(
    left: float,
    bottom: float,
    right: float,
    top: float,
    other: tuple[float, float, float, float],
) -> bool:
    o_left, o_bottom, o_right, o_top = other
    return not (
        right <= o_left
        or left >= o_right
        or top <= o_bottom
        or bottom >= o_top
    )


def _rgba_from_rgb(tile: np.ma.MaskedArray, *, dtypes: tuple[str, ...]) -> np.ndarray:
    if any(np.dtype(dtype) != np.dtype("uint8") for dtype in dtypes):
        raise RasterTileRenderError(
            "El perfil rgb inicial requiere un producto visual uint8."
        )
    values = np.asarray(tile.filled(0), dtype=np.uint8)
    masks = np.ma.getmaskarray(tile)
    invalid = np.any(masks, axis=0)
    alpha = np.where(invalid, 0, 255).astype(np.uint8)
    return np.concatenate((values, alpha[np.newaxis, :, :]), axis=0)


def _rgba_from_single_band(
    tile: np.ma.MaskedArray,
    *,
    display_min: float,
    display_max: float,
) -> np.ndarray:
    values = np.asarray(tile.filled(np.nan), dtype=np.float64)[0]
    invalid = np.ma.getmaskarray(tile)[0] | ~np.isfinite(values)
    scaled = (values - float(display_min)) / (float(display_max) - float(display_min))
    scaled = np.clip(scaled, 0.0, 1.0)
    gray = np.where(invalid, 0, np.rint(scaled * 255.0)).astype(np.uint8)
    alpha = np.where(invalid, 0, 255).astype(np.uint8)
    return np.stack((gray, gray, gray, alpha), axis=0)


def _encode_png(rgba: np.ndarray) -> bytes:
    if rgba.shape[0] != 4 or rgba.dtype != np.uint8:
        raise RasterTileRenderError("La salida RGBA interna no es válida.")
    height, width = int(rgba.shape[1]), int(rgba.shape[2])
    try:
        with MemoryFile() as memory:
            with memory.open(
                driver="PNG",
                width=width,
                height=height,
                count=4,
                dtype="uint8",
            ) as destination:
                destination.write(rgba)
            payload = memory.read()
    except Exception as error:
        raise RasterTileRenderError("GDAL no pudo codificar el tile PNG.") from error
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RasterTileRenderError("La salida no contiene una firma PNG válida.")
    return payload


def render_cog_xyz_tile(
    source_path: str | Path,
    *,
    z: int,
    x: int,
    y: int,
    style: RasterTileStyle,
    tile_size: int = _DEFAULT_TILE_SIZE,
) -> RasterTileRenderResult:
    """Renderiza una sola tesela reproyectada; nunca reescribe el COG fuente."""

    if (
        not isinstance(tile_size, int)
        or isinstance(tile_size, bool)
        or tile_size not in {256, 512}
    ):
        raise RasterTileRenderError("tile_size debe ser 256 o 512.")
    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise RasterTileRenderError("El COG interno no está disponible.")

    tile_bounds = xyz_bounds_3857(z, x, y)
    try:
        with rasterio.open(source) as dataset:
            if dataset.crs is None:
                raise RasterTileRenderError("El COG debe declarar CRS.")
            prepared_style = _validate_style(style, band_count=dataset.count)
            source_bounds = transform_bounds(
                dataset.crs,
                _WEB_MERCATOR_CRS,
                *dataset.bounds,
                densify_pts=21,
            )
            if not _intersects(*tile_bounds, source_bounds):
                raise RasterTileOutsideExtent("El tile no intersecta el producto.")

            transform = from_bounds(*tile_bounds, tile_size, tile_size)
            resampling = (
                Resampling.bilinear
                if prepared_style.render_mode == "rgb"
                else Resampling.nearest
            )
            with WarpedVRT(
                dataset,
                crs=_WEB_MERCATOR_CRS,
                transform=transform,
                width=tile_size,
                height=tile_size,
                resampling=resampling,
            ) as vrt:
                tile = vrt.read(
                    indexes=list(prepared_style.band_indexes),
                    masked=True,
                )

            selected_dtypes = tuple(
                str(dataset.dtypes[index - 1]) for index in prepared_style.band_indexes
            )
            if prepared_style.render_mode == "rgb":
                rgba = _rgba_from_rgb(tile, dtypes=selected_dtypes)
            else:
                assert prepared_style.display_min is not None
                assert prepared_style.display_max is not None
                rgba = _rgba_from_single_band(
                    tile,
                    display_min=float(prepared_style.display_min),
                    display_max=float(prepared_style.display_max),
                )
            payload = _encode_png(rgba)
            overviews = tuple(int(value) for value in dataset.overviews(1))
            return RasterTileRenderResult(
                data=payload,
                content_type="image/png",
                width=tile_size,
                height=tile_size,
                target_crs=_WEB_MERCATOR_CRS,
                source_band_count=int(dataset.count),
                source_dtype=tuple(str(value) for value in dataset.dtypes),
                source_overview_levels=overviews,
            )
    except (RasterTileRenderError, RasterTileOutsideExtent):
        raise
    except Exception as error:
        raise RasterTileRenderError("No se pudo renderizar el COG autorizado.") from error
