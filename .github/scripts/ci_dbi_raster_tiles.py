"""CI sintético para renderer aislado y caché privada de tiles DBI."""

from __future__ import annotations

from hashlib import sha256
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import UUID

import numpy as np
import rasterio
from rasterio.transform import from_bounds

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
SERVICE_SRC = ROOT / "services" / "banana-density" / "src"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(SERVICE_SRC))

from app.dbi.raster.tiles import (  # noqa: E402
    DBIRasterTileCache,
    DBIRasterTileCacheValue,
    DBIRasterTileCoordinate,
    DBIRasterTileError,
    DBIRasterTileStyle,
    build_tile_cache_identity,
)
from banana_analyzer.raster_cog import generate_validated_cog  # noqa: E402
from banana_analyzer.raster_tile_renderer import (  # noqa: E402
    RasterTileOutsideExtent,
    RasterTileStyle,
    render_cog_xyz_tile,
)

PRODUCT_ID = UUID("81000000-0000-4000-8000-000000000081")
PRODUCT_SHA = "a" * 64


def _file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _xyz(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 1 << z
    x = int((lon + 180.0) / 360.0 * n)
    latitude = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(latitude)) / math.pi) / 2.0 * n)
    return x, y


def _write_rgb_source(path: Path) -> None:
    width = height = 1024
    transform = from_bounds(-79.90, -3.40, -79.80, -3.30, width, height)
    row = np.linspace(20, 220, width, dtype=np.uint8)
    red = np.tile(row, (height, 1))
    green = np.flipud(red)
    blue = np.full((height, width), 120, dtype=np.uint8)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=3,
        dtype="uint8",
        crs="EPSG:4326",
        transform=transform,
    ) as dataset:
        dataset.write(np.stack((red, green, blue), axis=0))


def _write_scientific_source(path: Path) -> None:
    width = height = 1024
    transform = from_bounds(-79.90, -3.40, -79.80, -3.30, width, height)
    values = np.linspace(0.0, 1.0, width * height, dtype=np.float32).reshape(height, width)
    values[0:20, 0:20] = -9999.0
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999.0,
    ) as dataset:
        dataset.write(values, 1)
        dataset.scales = (1.0,)
        dataset.offsets = (0.0,)


def validate_real_cog_tiles(tmp: Path) -> None:
    rgb_source = tmp / "rgb-source.tif"
    rgb_cog = tmp / "rgb-cog.tif"
    _write_rgb_source(rgb_source)
    manifest = generate_validated_cog(
        rgb_source,
        rgb_cog,
        product_kind="rgb_visual",
        profile_version="rgb-tile-ci-v1",
    )
    assert manifest.descriptor.overview_levels
    before = _file_sha(rgb_cog)
    x, y = _xyz(-79.85, -3.35, 14)
    result = render_cog_xyz_tile(
        rgb_cog,
        z=14,
        x=x,
        y=y,
        style=RasterTileStyle(
            style_id="rgb-natural-ci-v1",
            render_mode="rgb",
            band_indexes=(1, 2, 3),
        ),
    )
    assert result.data.startswith(b"\x89PNG\r\n\x1a\n")
    assert result.content_type == "image/png"
    assert (result.width, result.height) == (256, 256)
    assert result.target_crs == "EPSG:3857"
    assert result.source_band_count == 3
    assert result.source_overview_levels
    assert _file_sha(rgb_cog) == before

    scientific_source = tmp / "scientific-source.tif"
    scientific_cog = tmp / "scientific-cog.tif"
    _write_scientific_source(scientific_source)
    generate_validated_cog(
        scientific_source,
        scientific_cog,
        product_kind="scientific",
        profile_version="scientific-tile-ci-v1",
    )
    scientific_before = _file_sha(scientific_cog)
    scientific = render_cog_xyz_tile(
        scientific_cog,
        z=14,
        x=x,
        y=y,
        style=RasterTileStyle(
            style_id="scientific-band1-ci-v1",
            render_mode="single_band",
            band_indexes=(1,),
            display_min=0.0,
            display_max=1.0,
        ),
    )
    assert scientific.data.startswith(b"\x89PNG\r\n\x1a\n")
    assert scientific.source_dtype == ("float32",)
    assert _file_sha(scientific_cog) == scientific_before

    try:
        render_cog_xyz_tile(
            rgb_cog,
            z=14,
            x=0,
            y=0,
            style=RasterTileStyle(
                style_id="outside-ci-v1",
                render_mode="rgb",
                band_indexes=(1, 2, 3),
            ),
        )
    except RasterTileOutsideExtent:
        pass
    else:
        raise AssertionError("Se esperaba RasterTileOutsideExtent.")


def validate_private_cache() -> None:
    now = [1000.0]
    clock = lambda: now[0]
    coordinate = DBIRasterTileCoordinate(z=14, x=4558, y=8344)
    style = DBIRasterTileStyle(
        style_id="rgb-natural-ci-v1",
        render_mode="rgb",
        band_indexes=(1, 2, 3),
    )
    first = build_tile_cache_identity(
        tenant_ref="tenant-a",
        product_id=PRODUCT_ID,
        product_sha256=PRODUCT_SHA,
        profile_version="rgb-cog-v1",
        style=style,
        coordinate=coordinate,
    )
    replay = build_tile_cache_identity(
        tenant_ref="tenant-a",
        product_id=PRODUCT_ID,
        product_sha256=PRODUCT_SHA,
        profile_version="rgb-cog-v1",
        style=style,
        coordinate=coordinate,
    )
    other_tenant = build_tile_cache_identity(
        tenant_ref="tenant-b",
        product_id=PRODUCT_ID,
        product_sha256=PRODUCT_SHA,
        profile_version="rgb-cog-v1",
        style=style,
        coordinate=coordinate,
    )
    assert first == replay
    assert first.digest != other_tenant.digest
    assert "tenant-a" not in first.digest

    cache = DBIRasterTileCache(
        max_entries=2,
        max_bytes=64,
        max_tile_bytes=32,
        ttl_seconds=10,
        clock=clock,
    )
    value = DBIRasterTileCacheValue(data=b"png-a")
    assert cache.get(first) is None
    cache.put(first, value)
    assert cache.get(first) == value
    assert cache.stats().hits == 1
    assert cache.stats().misses == 1

    now[0] += 11
    assert cache.get(first) is None
    assert cache.stats().expired == 1

    cache.put(first, value)
    assert cache.invalidate_product(PRODUCT_ID) == 1
    assert cache.stats().entries == 0


def validate_coordinate_fail_closed() -> None:
    for values in ((-1, 0, 0), (23, 0, 0), (3, 8, 0), (3, 0, 8)):
        try:
            DBIRasterTileCoordinate(z=values[0], x=values[1], y=values[2])
        except DBIRasterTileError:
            pass
        else:
            raise AssertionError(f"Coordenada inválida aceptada: {values}")


def main() -> None:
    with TemporaryDirectory(prefix="dbi-raster-tiles-") as directory:
        validate_real_cog_tiles(Path(directory))
    validate_private_cache()
    validate_coordinate_fail_closed()
    print(
        "DBI-RASTER-TILE-001 core aprobado: COG real -> PNG Web Mercator, "
        "scientific source intacto, caché tenant-aware TTL/LRU e invalidación."
    )


if __name__ == "__main__":
    main()
