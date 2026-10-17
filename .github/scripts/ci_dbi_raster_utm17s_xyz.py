"""Prueba sintética explícita de alineación interna EPSG:32717 -> XYZ EPSG:3857.

No verifica precisión RTK/GCP ni una coincidencia con fotos de Google; jamás
descarga imágenes externas ni escribe artefactos en almacenamiento productivo.
"""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.warp import transform

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "banana-density" / "src"))

from banana_analyzer.raster_cog import generate_validated_cog  # noqa: E402
from banana_analyzer.raster_tile_renderer import (  # noqa: E402
    RasterTileOutsideExtent,
    RasterTileStyle,
    render_cog_xyz_tile,
)

UTM_LEFT = 620_000.0
UTM_TOP = 9_640_000.0
PIXEL_METERS = 0.25
SIZE = 1024
ZOOM = 18
HALF_WORLD = 20_037_508.342789244
RGB_QUADRANTS = {
    (0, 0): (205, 45, 30),
    (0, 1): (25, 175, 55),
    (1, 0): (50, 60, 210),
    (1, 1): (220, 190, 45),
}


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _utm_sample(row: int, col: int) -> tuple[int, int, int, int]:
    """Ubica el centro de un cuadrante conocido en una celda XYZ.

    El cálculo de z/x/y/píxel es independiente del renderer; la transformación
    geodésica usa PROJ (Rasterio), por lo que el test no certifica un datum real.
    """
    east = UTM_LEFT + PIXEL_METERS * (col * 512 + 256)
    north = UTM_TOP - PIXEL_METERS * (row * 512 + 256)
    longitude, latitude = transform(
        "EPSG:32717", "EPSG:4326", [east], [north],
    )
    assert -82 < longitude[0] < -78 and -5 < latitude[0] < -2
    xx, yy = transform("EPSG:32717", "EPSG:3857", [east], [north])
    x_m, y_m = xx[0], yy[0]
    tile_count = 1 << ZOOM
    tile_span = 2.0 * HALF_WORLD / tile_count
    x = math.floor((x_m + HALF_WORLD) / tile_span)
    y = math.floor((HALF_WORLD - y_m) / tile_span)
    assert 0 <= x < tile_count and 0 <= y < tile_count
    west = -HALF_WORLD + x * tile_span
    north_tile = HALF_WORLD - y * tile_span
    pixel_x = math.floor((x_m - west) * 256 / tile_span)
    pixel_y = math.floor((north_tile - y_m) * 256 / tile_span)
    assert 0 <= pixel_x < 256 and 0 <= pixel_y < 256
    return x, y, pixel_x, pixel_y


def _write_rgb(path: Path) -> None:
    values = np.empty((3, SIZE, SIZE), dtype=np.uint8)
    for (row, col), rgb in RGB_QUADRANTS.items():
        values[:, row * 512:(row + 1) * 512, col * 512:(col + 1) * 512] = (
            np.asarray(rgb, dtype=np.uint8)[:, None, None]
        )
    with rasterio.open(
        path, "w", driver="GTiff", width=SIZE, height=SIZE, count=3,
        dtype="uint8", crs="EPSG:32717",
        transform=from_origin(UTM_LEFT, UTM_TOP, PIXEL_METERS, PIXEL_METERS),
    ) as dataset:
        dataset.write(values)


def _write_scientific(path: Path) -> None:
    values = np.full((SIZE, SIZE), 0.5, dtype=np.float32)
    values[:512, :512] = -9999.0
    with rasterio.open(
        path, "w", driver="GTiff", width=SIZE, height=SIZE, count=1,
        dtype="float32", crs="EPSG:32717", nodata=-9999.0,
        transform=from_origin(UTM_LEFT, UTM_TOP, PIXEL_METERS, PIXEL_METERS),
    ) as dataset:
        dataset.write(values, 1)


def _pixel(result, col: int, row: int) -> tuple[int, int, int, int]:
    assert result.content_type == "image/png"
    assert result.target_crs == "EPSG:3857"
    assert (result.width, result.height) == (256, 256)
    with MemoryFile(BytesIO(result.data).getvalue()) as memory:
        with memory.open() as image:
            assert image.count == 4
            assert image.width == image.height == 256
            return tuple(int(value) for value in image.read()[:, row, col])


def validate_rgb_utm_to_xyz(directory: Path) -> None:
    master = directory / "UTM17S_RGB_SYNTHETIC_MASTER.tif"
    cog = directory / "UTM17S_RGB_SYNTHETIC_COG.tif"
    _write_rgb(master)
    original_sha = _sha(master)
    manifest = generate_validated_cog(
        master, cog, product_kind="rgb_visual",
        profile_version="utm17s-rgb-xyz-test-v1",
    )
    assert manifest.descriptor.crs == "EPSG:32717"
    assert manifest.source_sha256 == original_sha
    assert manifest.descriptor.overview_levels
    cog_sha = _sha(cog)

    style = RasterTileStyle(
        style_id="rgb-natural-utm17s-test-v1",
        render_mode="rgb", band_indexes=(1, 2, 3),
    )
    for (row, col), expected_color in RGB_QUADRANTS.items():
        x, y, px, py = _utm_sample(row, col)
        tile = render_cog_xyz_tile(cog, z=ZOOM, x=x, y=y, style=style)
        assert _pixel(tile, px, py) == (*expected_color, 255), (
            f"RGB UTM 17S desalineado en cuadrante {row, col}"
        )

    try:
        render_cog_xyz_tile(cog, z=ZOOM, x=0, y=0, style=style)
    except RasterTileOutsideExtent:
        pass
    else:
        raise AssertionError("No se puede mostrar RGB fuera del levantamiento.")

    assert _sha(master) == original_sha
    assert _sha(cog) == cog_sha


def validate_scientific_nodata_utm_to_xyz(directory: Path) -> None:
    master = directory / "UTM17S_INDEX_SYNTHETIC_MASTER.tif"
    cog = directory / "UTM17S_INDEX_SYNTHETIC_COG.tif"
    _write_scientific(master)
    original_sha = _sha(master)
    manifest = generate_validated_cog(
        master, cog, product_kind="scientific",
        profile_version="utm17s-scientific-xyz-test-v1",
    )
    assert manifest.descriptor.crs == "EPSG:32717"
    assert manifest.descriptor.nodata == (-9999.0,)
    assert manifest.source_sha256 == original_sha
    cog_sha = _sha(cog)
    style = RasterTileStyle(
        style_id="scientific-gray-utm17s-test-v1",
        render_mode="single_band", band_indexes=(1,),
        display_min=0.0, display_max=1.0,
    )
    for row, col, expected in (
        (0, 0, (0, 0, 0, 0)),
        (1, 1, (128, 128, 128, 255)),
    ):
        x, y, px, py = _utm_sample(row, col)
        tile = render_cog_xyz_tile(cog, z=ZOOM, x=x, y=y, style=style)
        assert tile.source_dtype == ("float32",)
        assert _pixel(tile, px, py) == expected, (
            f"Máscara o escala científica incorrecta en cuadrante {row}, {col}"
        )

    with rasterio.open(master) as original:
        assert original.crs.to_string() == "EPSG:32717"
        assert original.nodata == -9999.0
        assert float(original.read(1)[768, 768]) == 0.5
        assert float(original.read(1)[256, 256]) == -9999.0
    assert _sha(master) == original_sha
    assert _sha(cog) == cog_sha


def main() -> None:
    with TemporaryDirectory(prefix="dbi-utm17s-xyz-ci-") as path:
        root = Path(path)
        validate_rgb_utm_to_xyz(root)
        validate_scientific_nodata_utm_to_xyz(root)
    print(
        "DBI EPSG:32717 -> XYZ EPSG:3857 aprobado con fixtures sintéticos: "
        "cuatro cuadrantes RGB, NoData científico, SHA y fuentes intactas. "
        "No implica certificación de georreferenciación de campo."
    )


if __name__ == "__main__":
    main()
