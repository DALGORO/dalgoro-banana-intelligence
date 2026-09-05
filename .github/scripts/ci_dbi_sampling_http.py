"""Valida frontera HTTP/GeoJSON de Sampling sin DB ni red."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("DATABASE_URL", "sqlite:///./ci_dbi_sampling_http.db")
os.environ.setdefault("JWT_SECRET", "ci-only-dbi-sampling-http-secret")

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.api.v1 import dbi_sampling, get_api_router  # noqa: E402
from app.dbi.authorization import (  # noqa: E402
    DBIAccessContext,
    DBIFarmScope,
    DBIPermission,
    DBIPlotScope,
)
from app.dbi.sampling.api_schemas import DBISamplingPlanCreateRequest  # noqa: E402
from app.dbi.sampling.contracts import DBISamplingBudget, DBISamplingProfile  # noqa: E402
from app.dbi.sampling.reader import (  # noqa: E402
    DBISamplingPlanSnapshot,
    DBISamplingPointSnapshot,
    sampling_plan_geojson,
)
from app.dbi.spatial import GeoJSONMultiPolygon  # noqa: E402

ORG = "organization-sampling-http"
TENANT = "tenant-sampling-http"
FARM = UUID("10000000-0000-4000-8000-000000000088")
PLOT = UUID("20000000-0000-4000-8000-000000000088")
PLAN = UUID("30000000-0000-4000-8000-000000000088")
POINT = UUID("40000000-0000-4000-8000-000000000088")
NOW = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)


def _boundary() -> GeoJSONMultiPolygon:
    return GeoJSONMultiPolygon.model_validate(
        {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [
                        [-79.81, -3.30],
                        [-79.80, -3.30],
                        [-79.80, -3.29],
                        [-79.81, -3.29],
                        [-79.81, -3.30],
                    ]
                ]
            ],
        }
    )


def _context(*, authorized: bool = True, write: bool = True) -> DBIAccessContext:
    permissions = {DBIPermission.READ}
    if write:
        permissions.add(DBIPermission.WRITE)
    return DBIAccessContext(
        principal_ref="principal-sampling-http",
        tenant_ref=TENANT,
        organization_refs=frozenset({ORG}),
        farm_scopes=(
            frozenset({DBIFarmScope(ORG, FARM)})
            if authorized
            else frozenset()
        ),
        plot_scopes=(
            frozenset({DBIPlotScope(ORG, FARM, PLOT)})
            if authorized
            else frozenset()
        ),
        permissions=frozenset(permissions),
    )


def _profile() -> DBISamplingProfile:
    return DBISamplingProfile(
        profile_version="sampling-http-v1",
        field_budget_minutes=120,
        sample_minutes=3,
        travel_minutes_per_sample=1.5,
        search_radius_m=12,
        seed=17,
    )


def validate_create_contract_has_no_boundary_authority() -> None:
    fields = set(DBISamplingPlanCreateRequest.model_fields)
    assert fields == {"profile", "exclusions"}
    for forbidden in (
        "boundary",
        "tenant_ref",
        "organization_ref",
        "farm_id",
        "plot_id",
        "up_id",
        "object_key",
        "bucket",
        "url",
    ):
        assert forbidden not in fields


def validate_routes_registered() -> None:
    routes = {
        (route.path, method)
        for route in get_api_router().routes
        if "sampling-plans" in route.path
        for method in route.methods
    }
    base = (
        "/dbi/organizations/{organization_ref}/farms/{farm_id}/plots/"
        "{plot_id}/sampling-plans"
    )
    item = base + "/{plan_id}"
    assert (base, "POST") in routes
    assert (item, "GET") in routes
    assert (item + "/geojson", "GET") in routes
    assert (item + "/points/{point_id}/validate", "POST") in routes
    assert (item + "/points/{point_id}/reject", "POST") in routes
    assert (item + "/points/{point_id}/substitute", "POST") in routes
    assert (item + "/complete", "POST") in routes


def validate_authorization_precedes_resolution() -> None:
    touched = False

    def forbidden_read(*args, **kwargs):
        nonlocal touched
        touched = True
        raise AssertionError("Sampling no debe resolverse antes de autorización.")

    with patch.object(dbi_sampling, "_read_response", side_effect=forbidden_read):
        try:
            dbi_sampling.get_sampling_plan(
                ORG,
                FARM,
                PLOT,
                PLAN,
                object(),
                _context(authorized=False),
            )
        except HTTPException as error:
            assert error.status_code == 404
        else:
            raise AssertionError("El lote no autorizado debía ocultarse.")
    assert touched is False

    with patch.object(dbi_sampling, "DBISamplingPlanService") as service:
        try:
            dbi_sampling.create_sampling_plan(
                ORG,
                FARM,
                PLOT,
                DBISamplingPlanCreateRequest(profile=_profile()),
                object(),
                _context(write=False),
            )
        except HTTPException as error:
            assert error.status_code == 404
        else:
            raise AssertionError("WRITE ausente debía ocultar creación Sampling.")
        service.assert_not_called()


def validate_geojson_contract() -> None:
    snapshot = DBISamplingPlanSnapshot(
        plan_id=PLAN,
        tenant_ref=TENANT,
        organization_ref=ORG,
        farm_id=FARM,
        plot_id=PLOT,
        schema_version="dbi-sampling-plan.v1",
        profile_version="sampling-http-v1",
        profile=_profile(),
        budget=DBISamplingBudget(
            field_budget_minutes=120,
            fixed_overhead_minutes=0,
            usable_minutes=120,
            minutes_per_primary=4.5,
            capacity_points=26,
            primary_count=1,
            reserve_count=0,
            target_status="within_target",
        ),
        boundary_sha256="a" * 64,
        exclusions_sha256="b" * 64,
        boundary=_boundary(),
        exclusions=None,
        status="in_field",
        created_at=NOW,
        points=(
            DBISamplingPointSnapshot(
                point_id=POINT,
                role="primary",
                sequence=1,
                route_order=1,
                reserve_for_sequence=None,
                selection_reason="balanced",
                planned_longitude=-79.805,
                planned_latitude=-3.295,
                observed_longitude=-79.80501,
                observed_latitude=-3.29501,
                status="validated",
                rejection_reason=None,
                observed_at=NOW,
            ),
        ),
    )
    payload = sampling_plan_geojson(snapshot)
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 2
    point = payload["features"][1]
    assert point["geometry"]["coordinates"] == [-79.805, -3.295]
    assert point["properties"]["observed"]["longitude"] == -79.80501
    serialized = str(payload).lower()
    for forbidden in ("object_key", "bucket", "credential", "local_path"):
        assert forbidden not in serialized


def validate_static_boundaries() -> None:
    source = (BACKEND / "app" / "api" / "v1" / "dbi_sampling.py").read_text(
        encoding="utf-8"
    ).lower()
    assert "dbiauthorizationpolicy.require_plot" in source
    assert "dbipermission.write" in source
    assert "dbipermission.read" in source
    assert "boundary=" not in source.split("create_plan(", 1)[1].split(")", 1)[0]
    for forbidden in ("rasterio", "gdal", "bucket", "presigned", "local_path"):
        assert forbidden not in source


def main() -> None:
    validate_create_contract_has_no_boundary_authority()
    validate_routes_registered()
    validate_authorization_precedes_resolution()
    validate_geojson_contract()
    validate_static_boundaries()
    print("DBI-SAMPLING-001 HTTP aprobado: auth previa, payload seguro y GeoJSON PWA.")


if __name__ == "__main__":
    main()
