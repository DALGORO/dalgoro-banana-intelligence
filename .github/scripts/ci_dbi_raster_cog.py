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


def _make_rgb_photo_like(path: Path) -> None:
    """Textura de color determinista para comprobar la compresión visual."""
    rows, cols = 768, 1024
    rng = np.random.default_rng(2026)
    yy, xx = np.mgrid[0:rows, 0:cols]
    noise = rng.integers(-35, 36, size=(rows, cols), dtype=np.int16)
    values = np.stack([
        np.clip(95 + xx // 40 + noise, 0, 255),
        np.clip(125 + yy // 55 + noise, 0, 255),
        np.clip(65 + (xx + yy) // 70 + noise, 0, 255),
    ]).astype("uint8")
    with rasterio.open(
        path, "w", driver="GTiff", width=cols, height=rows,
        count=3, dtype="uint8", crs="EPSG:32717",
        transform=from_origin(620000.0, 9640000.0, .03, .03),
    ) as ds:
        ds.write(values)


def _make_rgb_uint16(path: Path) -> None:
    transform = from_origin(620000.0, 9640000.0, 0.03, 0.03)
    rows, cols = 128, 128
    data = np.zeros((3, rows, cols), dtype="uint16")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=cols,
        height=rows,
        count=3,
        dtype="uint16",
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
        rgb_uint16 = root / "rgb_uint16.tif"
        rgb_uint16_cog = root / "rgb_uint16.cog.tif"
        _make_rgb(rgb)
        _make_rgb_uint16(rgb_uint16)
        textured_rgb = root / "rgb_texture.tif"
        textured_default = root / "rgb_texture.lossless.cog.tif"
        textured_preview = root / "rgb_texture.preview.cog.tif"
        _make_rgb_photo_like(textured_rgb)
        _make_scientific(scientific)

        rgb_manifest = generate_validated_cog(rgb, rgb_cog, product_kind="rgb_visual")
        assert rgb_manifest.descriptor.crs == "EPSG:32717"
        assert rgb_manifest.descriptor.width == 1024
        assert rgb_manifest.descriptor.height == 768
        assert rgb_manifest.descriptor.band_count == 3
        assert rgb_manifest.descriptor.tiled is True
        assert rgb_manifest.descriptor.overview_levels
        assert rgb_manifest.source_sha256 != rgb_manifest.cog_sha256

        # El perfil JPEG es voluntario, crea identidad nueva por profile_version
        # y mantiene los originales y los COG anteriores SIN sobrescribir.
        full = generate_validated_cog(
            textured_rgb, textured_default, product_kind="rgb_visual",
        )
        preview = generate_validated_cog(
            textured_rgb, textured_preview, product_kind="rgb_visual",
            profile_version="cog_rgb_preview_jpeg_v1",
        )
        assert preview.descriptor.compression == "jpeg"
        assert preview.profile_version == "cog_rgb_preview_jpeg_v1"
        assert preview.source_sha256 == full.source_sha256
        assert preview.descriptor.width == full.descriptor.width
        assert preview.descriptor.height == full.descriptor.height
        assert preview.descriptor.crs == full.descriptor.crs
        assert preview.descriptor.transform == full.descriptor.transform
        assert preview.descriptor.bounds == full.descriptor.bounds
        assert preview.descriptor.overview_levels
        assert preview.cog_size_bytes < full.cog_size_bytes, (
            "La muestra RGB sintética debe ser más liviana en JPEG."
        )
        with rasterio.open(textured_rgb) as master, rasterio.open(textured_preview) as lite:
            a = master.read().astype("int16")
            b = lite.read().astype("int16")
            assert a.shape == b.shape
            assert np.mean(np.abs(a - b)) < 25, (
                "La vista RGB es con pérdida controlada, no puede deformar excesivamente el color."
            )

        # Nunca usar JPEG/YCBCR para productos científicos (Float32/NoData).
        try:
            generate_validated_cog(
                scientific, root / "invalid-science.preview.tif",
                product_kind="scientific",
                profile_version="cog_rgb_preview_jpeg_v1",
            )
        except RasterCOGError:
            assert not (root / "invalid-science.preview.tif").exists()
        else:
            raise AssertionError("Perfil JPEG debe rechazar insumos científicos.")


        try:
            generate_validated_cog(
                rgb_uint16,
                rgb_uint16_cog,
                product_kind="rgb_visual",
            )
        except RasterCOGError:
            assert not rgb_uint16_cog.exists()
        else:
            raise AssertionError("rgb_visual uint16 debía rechazarse.")

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
