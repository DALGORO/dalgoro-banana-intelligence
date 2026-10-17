"""CI sintético: seis COG de índice y QML son evidencia, NO publicación."""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import UUID

import numpy as np
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "services" / "banana-density"
sys.path.insert(0, str(SERVICE / "src"))

from banana_analyzer.multispectral_indices import SpectralIndex, index_definition  # noqa: E402
from banana_analyzer.multispectral_map_preflight import (  # noqa: E402
    DBIIndexMapPreflightError, inspect_six_index_maps,
)
from banana_analyzer.raster_cog import generate_validated_cog  # noqa: E402

CAMPAIGN = UUID("63000000-0000-4000-8000-000000000063")
FINGERPRINT = "b" * 64
TRANSFORM = from_origin(620000.0, 9640000.0, .25, .25)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _create_cog(tmp: Path, *, label: str, n: int, transform=TRANSFORM, nodata=-9999.0, valid=True) -> Path:
    source = tmp / f"{label}.source.tif"
    target = tmp / f"{label}.cog.tif"
    values = np.full((1024, 1024), np.float32(.07 + n * .07 if valid else -9999), dtype=np.float32)
    values[:80, :80] = -9999.0
    with rasterio.open(
        source, "w", driver="GTiff", width=1024, height=1024,
        count=1, dtype="float32", crs="EPSG:32717", nodata=nodata,
        transform=transform,
    ) as ds:
        ds.write(values, 1)
    generate_validated_cog(source, target, product_kind="scientific", profile_version="multi-map-ci-v1")
    return target


def _qml(tmp: Path, label: str) -> Path:
    path = tmp / f"{label}.qml"
    path.write_text(
        '<qgis version="3.34"><pipe><rasterrenderer type="singlebandpseudocolor" '
        'band="1"><rastershader><colorrampshader colorRampType="INTERPOLATED">'
        '<item value="-1" color="#ff0000" label="Inferior"/>'
        '<item value="1" color="#00ff00" label="Superior"/>'
        '</colorrampshader></rastershader></rasterrenderer></pipe></qgis>',
        encoding="utf-8",
    )
    return path


def _raises(call, label: str) -> None:
    try:
        call()
    except DBIIndexMapPreflightError:
        return
    raise AssertionError(f"Preflight debía denegar: {label}")


def main() -> None:
    with TemporaryDirectory(prefix="dbi-multi-index-map-ci-") as folder:
        root = Path(folder)
        paths = {}
        for ordinal, index in enumerate(SpectralIndex, start=1):
            paths[index.value] = {
                "raster": _create_cog(root, label=index.value, n=ordinal),
                "qml": _qml(root, index.value),
            }
        original_sha = {
            (index, key): _sha(value)
            for index, pair in paths.items() for key, value in pair.items()
        }
        report = inspect_six_index_maps(
            campaign_id=CAMPAIGN, stack_fingerprint=FINGERPRINT, files=paths,
        )
        assert report.schema_version == "dbi-multi-six-maps-preflight.v1"
        assert report.disposition == "technical_preflight_only_not_published"
        assert not report.campaign_link_verified
        assert not report.source_calibration_verified
        assert not report.institutional_publication_authorized
        assert [x.index for x in report.indexes] == [i.value for i in SpectralIndex]
        assert len({x.raster_sha256 for x in report.indexes}) == 6
        assert all(x.valid_pixels > 0 and x.masked_pixels > 0 for x in report.indexes)
        assert all(x.crs == "EPSG:32717" and x.qml_color_stops == 2 for x in report.indexes)
        for entry in report.indexes:
            assert entry.formula_version == index_definition(SpectralIndex(entry.index)).formula_version
            assert entry.raster_sha256 == original_sha[(entry.index, "raster")]
            assert entry.qml_sha256 == original_sha[(entry.index, "qml")]

        # CLI sin acceso a red, rutas relativas al JSON de configuración.
        config = root / "input.json"
        config.write_text(json.dumps({
            "campaign_id": str(CAMPAIGN), "stack_fingerprint": FINGERPRINT,
            "files": {k: {t: v.name for t, v in entry.items()} for k, entry in paths.items()},
        }), encoding="utf-8")
        cli = SERVICE / "multi_map_preflight.py"
        run = subprocess.run([sys.executable, str(cli), "--input", str(config)],
                             capture_output=True, text=True, check=False)
        assert run.returncode == 0, run.stderr
        assert json.loads(run.stdout) == json.loads(json.dumps(asdict(report)))
        output = root / "evidence.json"
        first = subprocess.run(
            [sys.executable, str(cli), "--input", str(config), "--output", str(output)],
            capture_output=True, text=True, check=False,
        )
        assert first.returncode == 0 and output.is_file()
        second = subprocess.run(
            [sys.executable, str(cli), "--input", str(config), "--output", str(output)],
            capture_output=True, text=True, check=False,
        )
        assert second.returncode == 2 and "Preflight rechazado" in second.stderr

        _raises(lambda: inspect_six_index_maps(
            campaign_id=CAMPAIGN, stack_fingerprint=FINGERPRINT,
            files={k: v for k, v in paths.items() if k != "ndvi"},
        ), "índice faltante")
        _raises(lambda: inspect_six_index_maps(
            campaign_id=CAMPAIGN, stack_fingerprint="bogus", files=paths,
        ), "fingerprint inválido")
        duplicated = {k: dict(v) for k, v in paths.items()}
        duplicated["ndre"]["raster"] = paths["ndvi"]["raster"]
        _raises(lambda: inspect_six_index_maps(
            campaign_id=CAMPAIGN, stack_fingerprint=FINGERPRINT, files=duplicated,
        ), "mismo COG para dos índices")
        wrong_grid = {k: dict(v) for k, v in paths.items()}
        wrong_grid["ndvi"]["raster"] = _create_cog(
            root, label="wrong_grid", n=1,
            transform=from_origin(620010.0, 9640000.0, .25, .25),
        )
        _raises(lambda: inspect_six_index_maps(
            campaign_id=CAMPAIGN, stack_fingerprint=FINGERPRINT, files=wrong_grid,
        ), "desfase de grilla")
        not_cog = root / "tiled-but-not-cog.tif"
        with rasterio.open(
            not_cog, "w", driver="GTiff", width=1024, height=1024,
            count=1, dtype="float32", crs="EPSG:32717", nodata=-9999.0,
            transform=TRANSFORM, tiled=True, blockxsize=256, blockysize=256,
            compress="deflate",
        ) as ds:
            ds.write(np.ones((1024, 1024), dtype=np.float32), 1)
        wrong_layout = {k: dict(v) for k, v in paths.items()}
        wrong_layout["ndvi"]["raster"] = not_cog
        _raises(lambda: inspect_six_index_maps(
            campaign_id=CAMPAIGN, stack_fingerprint=FINGERPRINT, files=wrong_layout,
        ), "GeoTIFF en bloques sin layout COG")
        no_nodata = {k: dict(v) for k, v in paths.items()}
        no_nodata["ndvi"]["raster"] = _create_cog(
            root, label="no_nodata", n=1, nodata=None,
        )
        _raises(lambda: inspect_six_index_maps(
            campaign_id=CAMPAIGN, stack_fingerprint=FINGERPRINT, files=no_nodata,
        ), "NoData ausente")
        no_valid = {k: dict(v) for k, v in paths.items()}
        no_valid["ndvi"]["raster"] = _create_cog(
            root, label="no_valid", n=1, valid=False,
        )
        _raises(lambda: inspect_six_index_maps(
            campaign_id=CAMPAIGN, stack_fingerprint=FINGERPRINT, files=no_valid,
        ), "sin píxeles válidos")
        invalid_qml = {k: dict(v) for k, v in paths.items()}
        false_style = root / "invalid.qml"
        false_style.write_text('<qgis><rasterrenderer type="paletted" band="1"/></qgis>', encoding="utf-8")
        invalid_qml["ndvi"]["qml"] = false_style
        _raises(lambda: inspect_six_index_maps(
            campaign_id=CAMPAIGN, stack_fingerprint=FINGERPRINT, files=invalid_qml,
        ), "QML sin pseudocolor")
        false_style.write_text('<!DOCTYPE foo [<!ENTITY x "unsafe">]><qgis/>', encoding="utf-8")
        _raises(lambda: inspect_six_index_maps(
            campaign_id=CAMPAIGN, stack_fingerprint=FINGERPRINT, files=invalid_qml,
        ), "QML con DTD")
        for (index, key), digest in original_sha.items():
            assert _sha(paths[index][key]) == digest, "Preflight alteró original"
    print(
        "DBI MULTI H13 aprobado: seis COG Float32/QML sintéticos, grilla, NoData, "
        "hash y fail-closed; NO acreditación institucional ni publicación."
    )


if __name__ == "__main__":
    main()
