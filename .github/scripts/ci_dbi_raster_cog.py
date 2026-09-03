"""Smoke real de COG para DBI-RASTER-001 con Rasterio/GDAL."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[2]
ENGINE_SRC = ROOT / "services" / "banana-density" / "src"
sys.path.insert(0, str(ENGINE_SRC))

from banana_analyzer.raster_cog import (  # noqa: E402
    RasterCOGError,
    generate_validated_cog,
    write_manifest,
)


def _make_rgb(path: Path) -> None:
    transform = from_origin(620000.0, 9640000.0, 0.03, 0.03)
    rows, cols = 768, 1024
    yy, xx = np.mgrid[0:rows, 0:cols]
    data = np.stack(
        (
            (xx % 256).astype("uint8"),
            (yy % 256).astype("uint8"),
            ((xx + yy) % 256).astype("uint8"),
        )
    )
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=cols,
        height=rows,
        count=3,
        dtype="uint8",
        crs="EPSG:32717",
        transform=transform,
    ) as dataset:
        dataset.write(data)


def _make_scientific(path: Path) -> None:
    transform = from_origin(620000.0, 9640000.0, 0.10, 0.10)
    rows, cols = 600, 700
    values = np.linspace(-1.0, 1.0, rows * cols, dtype="float32").reshape(rows, cols)
    values[0, 0] = -9999.0
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=cols,
        height=rows,
        count=1,
        dtype="float32",
        crs="EPSG:32717",
        transform=transform,
        nodata=-9999.0,
    ) as dataset:
        dataset.write(values, 1)
        dataset.scales = (0.0001,)
        dataset.offsets = (0.0,)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="dbi-raster-") as raw_dir:
        root = Path(raw_dir)
        rgb = root / "rgb.tif"
        rgb_cog = root / "rgb.cog.tif"
        scientific = root / "ndvi.tif"
        scientific_cog = root / "ndvi.cog.tif"
        _make_rgb(rgb)
        _make_scientific(scientific)

        rgb_manifest = generate_validated_cog(rgb, rgb_cog, product_kind="rgb_visual")
        assert rgb_manifest.descriptor.crs == "EPSG:32717"
        assert rgb_manifest.descriptor.width == 1024
        assert rgb_manifest.descriptor.height == 768
        assert rgb_manifest.descriptor.band_count == 3
        assert rgb_manifest.descriptor.tiled is True
        assert rgb_manifest.descriptor.overview_levels
        assert rgb_manifest.source_sha256 != rgb_manifest.cog_sha256

        science_manifest = generate_validated_cog(
            scientific,
            scientific_cog,
            product_kind="scientific",
        )
        assert science_manifest.descriptor.dtypes == ("float32",)
        assert science_manifest.descriptor.nodata == (-9999.0,)
        assert science_manifest.descriptor.scales == (0.0001,)
        assert science_manifest.descriptor.offsets == (0.0,)
        assert science_manifest.descriptor.overview_levels

        manifest_file = root / "flight.manifest.json"
        write_manifest(rgb_manifest, manifest_file)
        decoded = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert decoded["schema_version"] == "dbi-raster-flight-test.v1"
        assert "/" not in decoded["source_name"]
        assert "\\" not in decoded["source_name"]

        try:
            generate_validated_cog(rgb, rgb_cog, product_kind="rgb_visual")
        except RasterCOGError:
            pass
        else:
            raise AssertionError("El generador no debe sobrescribir un COG existente.")

    print("DBI-RASTER-001 COG aprobado: RGB + científico preservan contrato geoespacial.")


if __name__ == "__main__":
    main()
