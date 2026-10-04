"""Valida estáticamente el runtime Windows del piloto Raster DBI."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / "infra" / "windows-local" / "DBI-ControlCenter.ps1"
INSTALLER = ROOT / "infra" / "windows-local" / "Install-DBI-ControlCenter.ps1"
MAIN = ROOT / "apps" / "platform-web" / "backend" / "app" / "main.py"
PILOT = ROOT / "apps" / "platform-web" / "backend" / "app" / "api" / "v1" / "dbi_pilot_raster.py"
PILOT_UPLOAD = ROOT / "apps" / "platform-web" / "backend" / "app" / "api" / "v1" / "dbi_pilot.py"
BUILDER = ROOT / "apps" / "platform-web" / "backend" / "app" / "dbi" / "raster" / "pilot_builder.py"
PILOT_UI = ROOT / "apps" / "platform-web" / "frontend" / "src" / "pages" / "DbiPilotPage.tsx"
DENSITY_UI = ROOT / "apps" / "platform-web" / "frontend" / "src" / "pages" / "DbiDensityPage.tsx"
RUNBOOK = ROOT / "docs" / "42_REAL_FLIGHT_TEST_DBI-PILOT-RASTER-001.md"


def main() -> None:
    control = CONTROL.read_text(encoding="utf-8")
    installer = INSTALLER.read_text(encoding="utf-8")
    main_source = MAIN.read_text(encoding="utf-8")
    pilot_source = PILOT.read_text(encoding="utf-8")
    pilot_upload = PILOT_UPLOAD.read_text(encoding="utf-8")
    builder_source = BUILDER.read_text(encoding="utf-8")
    pilot_ui = PILOT_UI.read_text(encoding="utf-8")
    density_ui = DENSITY_UI.read_text(encoding="utf-8")
    runbook = RUNBOOK.read_text(encoding="utf-8")

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
    assert "orthophotos/{asset_id}/rgb-cog" in pilot_source
    assert "DBIPilotRasterBuilder" in pilot_source
    assert "flight_test_cog.py" in pilot_source

    for source in (pilot_source, builder_source, main_source):
        lowered = source.lower()
        assert "import rasterio" not in lowered
        assert "from rasterio" not in lowered
        assert "from osgeo" not in lowered

    assert "Preparar mapa RGB" in pilot_ui
    assert "Abrir mapa" in pilot_ui
    assert "Raster / COG" in pilot_ui
    assert "Preparar mapa RGB" in density_ui
    assert "Verificar mapa RGB" in density_ui
    assert "Raster / COG" in density_ui
    assert "map_path" in density_ui
    assert "GeoTIFF real verificado" in runbook
    assert "DBIRasterProduct ready" in runbook

    assert 'declared_crs == "AUTO_FROM_GEOTIFF"' in pilot_upload
    assert "crs=asset_crs" in pilot_upload
    assert "crs: str | None" in pilot_upload
    assert "_reconcile_source_crs" in builder_source
    assert "actual_crs=candidate.crs" in builder_source
    assert "actual_crs=row.crs" in builder_source
    assert "El CRS declarado de la ortofoto diverge" in builder_source

    print(
        "DBI local Raster runtime aprobado: Python geoespacial explícito, "
        "probe Rasterio y restart por revisión Git."
    )


if __name__ == "__main__":
    main()
