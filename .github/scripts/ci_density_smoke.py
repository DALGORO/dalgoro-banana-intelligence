"""Smoke test del motor geoespacial sin modelos ni ortofotos."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path


DIRECT_IMPORTS = (
    "affine",
    "cv2",
    "geopandas",
    "matplotlib",
    "numpy",
    "openpyxl",
    "pandas",
    "PIL",
    "pyogrio",
    "pyproj",
    "rasterio",
    "reportlab",
    "scipy",
    "shapely",
    "torch",
    "torchvision",
    "ultralytics",
    "xlrd",
    "yaml",
)


def main() -> None:
    """Valida importaciones, CLI y un caso negativo que no escribe archivos."""

    project_root = Path.cwd().resolve()
    source_directory = project_root / "src"

    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(source_directory))

    temporary_root = Path(tempfile.gettempdir())
    os.environ["MPLBACKEND"] = "Agg"
    os.environ["MPLCONFIGDIR"] = str(temporary_root / "dbi-ci-matplotlib")
    os.environ["YOLO_CONFIG_DIR"] = str(
        temporary_root / "dbi-ci-ultralytics"
    )

    for module_name in DIRECT_IMPORTS:
        importlib.import_module(module_name)

    import main as density_cli
    from banana_analyzer import __version__
    from banana_analyzer.validation import inspect_raster

    parser = density_cli.build_argument_parser()
    parsed = parser.parse_args(["system-check"])
    missing_raster = inspect_raster(project_root / "__dbi_ci_missing__.tif")

    assert parsed.command == "system-check"
    assert __version__
    assert missing_raster.valid is False
    assert missing_raster.errors == ["El archivo raster no existe."]

    print("Density smoke test: dependencias, paquete y CLI aprobados.")


if __name__ == "__main__":
    main()
