"""Valida estáticamente el runtime Windows del piloto Raster DBI."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / "infra" / "windows-local" / "DBI-ControlCenter.ps1"
INSTALLER = ROOT / "infra" / "windows-local" / "Install-DBI-ControlCenter.ps1"
MAIN = ROOT / "apps" / "platform-web" / "backend" / "app" / "main.py"
PILOT = ROOT / "apps" / "platform-web" / "backend" / "app" / "api" / "v1" / "dbi_pilot_raster.py"


def main() -> None:
    control = CONTROL.read_text(encoding="utf-8")
    installer = INSTALLER.read_text(encoding="utf-8")
    main_source = MAIN.read_text(encoding="utf-8")
    pilot_source = PILOT.read_text(encoding="utf-8")

    for token in (
        "DBI_DENSITY_PYTHON",
        "DBI_RASTER_RENDERER_PYTHON",
        'import rasterio',
        "repo_revision",
        "Get-DbiRepoRevision",
        "Get-DbiDensityPython",
    ):
        assert token in control, token

    assert "density_python = $densityPython" in installer
    assert 'import rasterio' in installer

    assert 'os.environ.get("DBI_RASTER_RENDERER_PYTHON", "").strip()' in main_source
    assert "or sys.executable" not in main_source
    assert "if not python_raw:" in main_source

    assert "DBI_RASTER_RENDERER_PYTHON" in pilot_source
    assert "DBI_DENSITY_PYTHON" in pilot_source
    assert "density_python()" not in pilot_source

    print(
        "DBI local Raster runtime aprobado: Python geoespacial explícito, "
        "probe Rasterio y restart por revisión Git."
    )


if __name__ == "__main__":
    main()
