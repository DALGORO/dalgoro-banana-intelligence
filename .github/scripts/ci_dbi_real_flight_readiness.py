"""Gate cruzado para declarar listo el primer flight test RGB real DBI.

No ejecuta ciencia ni modifica datos. Comprueba que el checkout contiene,
simultáneamente, las fronteras ya validadas por sus CI especializados:
GeoTIFF -> COG -> Raster -> Campaign -> tiles -> MapLibre.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

BACKEND = ROOT / "apps" / "platform-web" / "backend"
FRONTEND = ROOT / "apps" / "platform-web" / "frontend"
DENSITY = ROOT / "services" / "banana-density"

FILES = {
    "pilot_builder": BACKEND / "app" / "dbi" / "raster" / "pilot_builder.py",
    "pilot_api": BACKEND / "app" / "api" / "v1" / "dbi_pilot_raster.py",
    "pilot_upload": BACKEND / "app" / "api" / "v1" / "dbi_pilot.py",
    "density_campaign": BACKEND / "app" / "dbi" / "density_campaign.py",
    "map_timeline": BACKEND / "app" / "dbi" / "map_timeline.py",
    "raster_api": BACKEND / "app" / "api" / "v1" / "dbi_raster_products.py",
    "raster_contracts": BACKEND / "app" / "dbi" / "raster" / "contracts.py",
    "raster_local_renderer": (
        BACKEND / "app" / "dbi" / "raster" / "local_tile_renderer.py"
    ),
    "main": BACKEND / "app" / "main.py",
    "raster_cog": DENSITY / "src" / "banana_analyzer" / "raster_cog.py",
    "density_ui": FRONTEND / "src" / "pages" / "DbiDensityPage.tsx",
    "map_ui": FRONTEND / "src" / "pages" / "FarmMapTimeline.tsx",
    "map_client": FRONTEND / "src" / "features" / "mapTimeline.ts",
    "control_center": ROOT / "infra" / "windows-local" / "DBI-ControlCenter.ps1",
    "density_campaign_ci": (
        ROOT / ".github" / "scripts" / "ci_dbi_density_campaign_link.py"
    ),
    "runbook": (
        ROOT / "docs" / "42_REAL_FLIGHT_TEST_DBI-PILOT-RASTER-001.md"
    ),
}


def source(name: str) -> str:
    path = FILES[name]
    if not path.is_file():
        raise AssertionError(f"Falta archivo crítico: {path}")
    return path.read_text(encoding="utf-8")


def require(name: str, *fragments: str) -> None:
    text = source(name)
    for fragment in fragments:
        assert fragment in text, f"{name}: falta contrato {fragment!r}"


def validate_cog_publication() -> None:
    require(
        "pilot_builder",
        "DBIStoragePurpose.RASTER_PRODUCT",
        "prepare_candidate_from_manifest",
        "service.resolve_source(candidate, tenant_ref=tenant_ref)",
        "self._store.put(",
        "service.register_ready(",
        "subprocess.run(",
        "shutil.rmtree(workspace, ignore_errors=True)",
    )
    require(
        "pilot_api",
        '"/companies/{company_id}/farms/{farm_id}/plots/{plot_id}/"',
        '"orthophotos/{asset_id}/rgb-cog"',
        "DBIPilotRasterBuilder(",
        "DBI_RASTER_RENDERER_PYTHON",
        "DBI_DENSITY_PYTHON",
        "flight_test_cog.py",
        "map_path",
    )


def validate_auto_crs_reconciliation() -> None:
    require(
        "pilot_upload",
        'declared_crs == "AUTO_FROM_GEOTIFF"',
        "crs=asset_crs",
        "crs: str | None",
    )
    require(
        "pilot_builder",
        "_validate_source_crs",
        "actual_crs=candidate.crs",
        "actual_crs=row.crs",
        "El CRS declarado de la ortofoto diverge",
    )
    require(
        "pilot_api",
        "_promote_source_crs",
        "asset.crs = actual_crs",
        "actual_crs=result.crs",
        "No se pudo reconciliar la metadata CRS",
    )


def validate_campaign_to_map() -> None:
    campaign = source("density_campaign")
    require(
        "density_campaign",
        "DBICampaignArtifactService",
        "DBICampaignArtifactType.ORTHOPHOTO_SOURCE",
        "DBICampaignArtifactSourceKind.INPUT_ASSET",
        "source_ref=orthophoto_asset_id",
        "sha256=orthophoto_sha256",
        "version=1",
        "orthophoto_campaign_artifact_id",
    )
    link = campaign.split(
        "def link_density_job_to_campaign",
        1,
    )[1].split(
        "def mark_density_campaign_analyzed",
        1,
    )[0]
    assert link.index("register_artifact(") < link.index(
        "target_status=DBICampaignStatus.PROCESSING"
    )
    assert ".commit(" not in link
    assert ".rollback(" not in link

    require(
        "map_timeline",
        'DBICampaignArtifact.artifact_type == "orthophoto_source"',
        'DBICampaignArtifact.technical_status == "current"',
        'DBIRasterProduct.product_kind == "rgb_visual"',
        'DBIRasterProduct.status == "ready"',
        "DBIRasterProduct.source_ref",
        "DBICampaignArtifact.source_ref",
        "DBIRasterProduct.source_sha256",
        "DBICampaignArtifact.sha256",
        "raster_bounds_wgs84(",
        "if bounds is None and viewport_raster is not None:",
        "ST_Transform",
    )


def validate_tiles_and_browser() -> None:
    require(
        "raster_api",
        '"raster-products/{product_id}/tiles/{z}/{x}/{y}.png"',
        "DBIAuthorizationPolicy.require_plot",
        "DBIRasterTileApplication",
        '"X-DBI-Tile-Cache"',
        '"Cache-Control": "private, max-age=60"',
    )
    require(
        "map_ui",
        'type: "raster"',
        "transformRequest",
        "mapLibreDbiHeaders",
        "viewport_bounds",
        "tile_url_template",
    )
    require(
        "map_client",
        '"X-DBI-Tenant"',
        "Authorization",
        "tile_url_template",
        "apiResourceUrl",
    )


def validate_rgb_contract() -> None:
    require(
        "raster_contracts",
        "bands < 3",
        'candidate.dtype != "uint8"',
        "rgb_visual requiere dtype uint8",
    )
    require(
        "raster_cog",
        'product_kind == "rgb_visual"',
        'dtype != "uint8"',
        "rgb_visual requiere bandas uint8",
    )


def validate_local_runtime() -> None:
    require(
        "control_center",
        "DBI_DENSITY_PYTHON",
        "DBI_RASTER_RENDERER_PYTHON",
        '-c "import rasterio"',
        "Get-DbiRepoRevision",
        "repo_revision",
    )
    require(
        "density_ui",
        "Raster / COG",
        "raster_ready",
        "Preparar mapa RGB",
        "Verificar mapa RGB",
        "Abrir mapa RGB",
        "map_path",
    )


def validate_real_integration_evidence() -> None:
    require(
        "density_campaign_ci",
        "AnalysisInputAsset",
        "DBIRasterProduct",
        "DBICampaignArtifactReader",
        "DBIMapTimelineReader",
        "DBICampaignArtifactType.ORTHOPHOTO_SOURCE",
        "entry.raster_product_id == str(RASTER_PRODUCT_ID)",
        'entry.layer_type == "rgb"',
        '"/tiles/{z}/{x}/{y}.png"',
    )
    require(
        "runbook",
        "GeoTIFF real verificado",
        "DBIRasterProduct ready",
        "tiles XYZ privados",
        "MapLibre",
    )


def validate_process_boundaries() -> None:
    # El único módulo aquí autorizado a importar Rasterio es el motor Density.
    forbidden = (
        "import rasterio",
        "from rasterio",
        "import gdal",
        "from osgeo",
    )
    for name in (
        "pilot_builder",
        "pilot_api",
        "density_campaign",
        "map_timeline",
        "raster_api",
        "raster_contracts",
        "raster_local_renderer",
        "main",
    ):
        lowered = source(name).lower()
        for fragment in forbidden:
            assert fragment not in lowered, (
                f"{name}: dependencia geoespacial pesada cruzó a FastAPI: "
                f"{fragment}"
            )

    density_source = source("raster_cog").lower()
    assert "import rasterio" in density_source


def main() -> None:
    validate_cog_publication()
    validate_auto_crs_reconciliation()
    validate_campaign_to_map()
    validate_tiles_and_browser()
    validate_rgb_contract()
    validate_local_runtime()
    validate_real_integration_evidence()
    validate_process_boundaries()
    print(
        "DBI-FLIGHT-READY-002 aprobado: GeoTIFF + CRS AUTO -> COG -> Campaign -> "
        "Raster -> tiles -> MapLibre integrado y con fronteras cerradas."
    )


if __name__ == "__main__":
    main()
