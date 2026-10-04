"""Valida contratos cartográficos DBI sin servicios externos."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from pydantic import ValidationError


EXPECTED_LAYER_TYPES = {
    "rgb",
    "ndvi",
    "ndre",
    "density",
    "anomalies",
    "inspections",
    "production",
    "sst",
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ORG = "organization-map-ci"
TENANT = "tenant-map-ci"
FARM = UUID("61000000-0000-4000-8000-000000000061")
PLOT = UUID("62000000-0000-4000-8000-000000000062")
CAMPAIGN = UUID("63000000-0000-4000-8000-000000000063")
ARTIFACT = UUID("64000000-0000-4000-8000-000000000064")
RASTER = UUID("65000000-0000-4000-8000-000000000065")


def validate_contract() -> None:
    """Comprueba legado v1 y nuevo contrato Raster estricto."""

    from app.schemas.dbi_map import (
        FarmMapTimelineResponse,
        MAP_LAYER_CATALOG,
        PlotMapTimelineResponse,
        ProfessionalReviewStatus,
        RasterTileTimelineEntry,
        build_empty_farm_map_timeline,
    )

    response = build_empty_farm_map_timeline("farm-contract-check")
    payload = response.model_dump(mode="json")

    assert payload["schema_version"] == "farm-map-timeline.v1"
    assert payload["farm_id"] == "farm-contract-check"
    assert payload["status"] == "awaiting_data"
    assert payload["timeline"] == []
    assert payload["comparison"] == {
        "minimum_dates": 2,
        "available_dates": [],
        "enabled": False,
    }
    assert {
        item["layer_type"] for item in payload["available_layers"]
    } == EXPECTED_LAYER_TYPES

    try:
        FarmMapTimelineResponse.model_validate(
            {**payload, "unexpected_contract_field": True}
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("El contrato legacy aceptó un campo desconocido.")

    captured = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    real = PlotMapTimelineResponse(
        organization_ref=ORG,
        farm_id=str(FARM),
        plot_id=str(PLOT),
        status="ready",
        available_layers=list(MAP_LAYER_CATALOG),
        timeline=[
            RasterTileTimelineEntry(
                entry_id=f"rgb:{CAMPAIGN}:{RASTER}",
                campaign_id=str(CAMPAIGN),
                plot_id=str(PLOT),
                captured_at=captured,
                title="Vuelo RGB CI",
                source_artifact_id=str(ARTIFACT),
                raster_product_id=str(RASTER),
                tile_url_template=(
                    f"/api/v1/dbi/organizations/{ORG}/farms/{FARM}/plots/"
                    f"{PLOT}/raster-products/{RASTER}/tiles/"
                    "{z}/{x}/{y}.png"
                ),
                professional_review_status=ProfessionalReviewStatus.PENDING,
            )
        ],
        comparison={
            "minimum_dates": 2,
            "available_dates": [captured],
            "enabled": False,
        },
        viewport_bounds=(-79.95, -3.40, -79.90, -3.35),
    )
    real_payload = real.model_dump(mode="json")
    assert real_payload["schema_version"] == "plot-map-timeline.v1"
    assert real_payload["timeline"][0]["layer_type"] == "rgb"
    assert real_payload["timeline"][0]["classification"] == "observed"
    assert real_payload["timeline"][0]["tile_url_template"].endswith(
        "/tiles/{z}/{x}/{y}.png"
    )

    serialized = real.model_dump_json()
    for forbidden in (
        "file://",
        "localhost",
        "object_key",
        "bucket",
        "credentials",
        "\\",
    ):
        assert forbidden not in serialized


def _context():
    from app.dbi.authorization import (
        DBIAccessContext,
        DBIFarmScope,
        DBIPermission,
        DBIPlotScope,
    )

    return DBIAccessContext(
        principal_ref="principal-map-ci",
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG}),
        farm_scopes=frozenset({DBIFarmScope(ORG, FARM)}),
        plot_scopes=frozenset({DBIPlotScope(ORG, FARM, PLOT)}),
        permissions=frozenset({DBIPermission.READ}),
    )


def _real_response():
    from app.schemas.dbi_map import (
        MAP_LAYER_CATALOG,
        PlotMapTimelineResponse,
        ProfessionalReviewStatus,
        RasterTileTimelineEntry,
    )

    captured = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    return PlotMapTimelineResponse(
        organization_ref=ORG,
        farm_id=str(FARM),
        plot_id=str(PLOT),
        status="ready",
        available_layers=list(MAP_LAYER_CATALOG),
        timeline=[
            RasterTileTimelineEntry(
                entry_id=f"rgb:{CAMPAIGN}:{RASTER}",
                campaign_id=str(CAMPAIGN),
                plot_id=str(PLOT),
                captured_at=captured,
                title="Vuelo RGB CI",
                source_artifact_id=str(ARTIFACT),
                raster_product_id=str(RASTER),
                tile_url_template=(
                    f"/api/v1/dbi/organizations/{ORG}/farms/{FARM}/plots/"
                    f"{PLOT}/raster-products/{RASTER}/tiles/"
                    "{z}/{x}/{y}.png"
                ),
                professional_review_status=ProfessionalReviewStatus.PENDING,
            )
        ],
        comparison={
            "minimum_dates": 2,
            "available_dates": [captured],
            "enabled": False,
        },
        viewport_bounds=(-79.95, -3.40, -79.90, -3.35),
    )


class _FakeTimelineReader:
    def __init__(self, session) -> None:
        assert session is not None

    def read_plot_timeline(self, **kwargs):
        assert kwargs == {
            "tenant_ref": TENANT,
            "organization_ref": ORG,
            "farm_id": FARM,
            "plot_id": PLOT,
        }
        return _real_response()


def validate_viewport_contract() -> None:
    """Comprueba el fallback sin exigir PostGIS para casos directos/invalidos."""

    from app.dbi.map_timeline import raster_bounds_wgs84

    direct = raster_bounds_wgs84(
        object(),  # no se consulta para EPSG:4326
        crs="EPSG:4326",
        bounds_json="[-79.95,-3.40,-79.90,-3.35]",
    )
    assert direct == (-79.95, -3.40, -79.90, -3.35)

    for crs, bounds_json in (
        ("EPSG:4326", "[10,10,9,11]"),
        ("EPSG:4326", "[181,-3,182,-2]"),
        ("EPSG:4326", "[1,2,3]"),
        ("EPSG:4326", "[1,2,3,\"bad\"]"),
        ("WGS84", "[-79.95,-3.40,-79.90,-3.35]"),
    ):
        assert raster_bounds_wgs84(
            object(),
            crs=crs,
            bounds_json=bounds_json,
        ) is None

    source = (
        REPOSITORY_ROOT
        / "apps"
        / "platform-web"
        / "backend"
        / "app"
        / "dbi"
        / "map_timeline.py"
    ).read_text(encoding="utf-8")
    assert "if bounds is None and viewport_raster is not None:" in source
    assert "raster_bounds_wgs84(" in source
    assert "ST_Transform" in source
    assert "import rasterio" not in source.lower()
    assert "from rasterio" not in source.lower()


def validate_endpoint() -> None:
    """Comprueba legacy y nueva ruta autorizada sin tocar una base."""

    os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
    os.environ["JWT_SECRET"] = "dbi-map-ci-placeholder"
    os.environ["ENABLE_DOCS"] = "0"

    from fastapi.testclient import TestClient

    from app.api.deps import current_user
    from app.api.v1 import dbi_map
    from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
    from app.main import app

    with TestClient(app) as anonymous_client:
        anonymous = anonymous_client.get(
            "/api/v1/dbi/farms/farm-contract-check/map/timeline"
        )
    assert anonymous.status_code in {401, 403}, anonymous.text

    app.dependency_overrides[current_user] = lambda: object()
    try:
        with TestClient(app) as client:
            valid = client.get(
                "/api/v1/dbi/farms/farm-contract-check/map/timeline"
            )
            invalid = client.get(
                "/api/v1/dbi/farms/farm%20with%20spaces/map/timeline"
            )
    finally:
        app.dependency_overrides.clear()

    assert valid.status_code == 200, valid.text
    assert valid.json()["timeline"] == []
    assert invalid.status_code == 422, invalid.text

    app.dependency_overrides[get_dbi_session] = lambda: object()
    app.dependency_overrides[get_dbi_access_context] = _context
    try:
        with patch.object(dbi_map, "DBIMapTimelineReader", _FakeTimelineReader):
            with TestClient(app) as client:
                response = client.get(
                    f"/api/v1/dbi/organizations/{ORG}/farms/{FARM}/plots/"
                    f"{PLOT}/map/timeline",
                    headers={"X-DBI-Tenant": TENANT},
                )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ready"
    assert len(payload["timeline"]) == 1
    assert payload["timeline"][0]["raster_product_id"] == str(RASTER)


def validate_frontend_contract() -> None:
    """Evita divergencia entre contratos Python, cliente y MapLibre."""

    feature_path = (
        REPOSITORY_ROOT
        / "apps"
        / "platform-web"
        / "frontend"
        / "src"
        / "features"
        / "mapTimeline.ts"
    )
    page_path = (
        REPOSITORY_ROOT
        / "apps"
        / "platform-web"
        / "frontend"
        / "src"
        / "pages"
        / "FarmMapTimeline.tsx"
    )
    routes_path = (
        REPOSITORY_ROOT
        / "apps"
        / "platform-web"
        / "frontend"
        / "src"
        / "app"
        / "routes.tsx"
    )
    feature_source = feature_path.read_text(encoding="utf-8")
    page_source = page_path.read_text(encoding="utf-8")
    routes_source = routes_path.read_text(encoding="utf-8")

    assert "farm-map-timeline.v1" in feature_source
    assert "plot-map-timeline.v1" in feature_source
    assert "X-DBI-Tenant" in feature_source
    assert "tile_url_template" in feature_source
    for layer_type in EXPECTED_LAYER_TYPES:
        assert f'"{layer_type}"' in feature_source

    assert "sources: {}" in page_source
    assert 'type: "raster"' in page_source
    assert "transformRequest" in page_source
    assert "mapLibreDbiHeaders" in page_source
    assert "viewport_bounds" in page_source
    assert (
        "dbi/organizations/:organizationRef/farms/:farmId/plots/:plotId/mapa"
        in routes_source
    )

    for forbidden in ("file://", "presigned", "signed_url"):
        assert forbidden not in feature_source.lower()
        assert forbidden not in page_source.lower()


def main() -> None:
    validate_contract()
    validate_viewport_contract()
    validate_endpoint()
    validate_frontend_contract()
    print(
        "DBI-MAP offline aprobado: contrato real, autorización, viewport Raster, "
        "tile template privado y MapLibre Raster."
    )


if __name__ == "__main__":
    main()
