"""Valida el motor puro de DBI-SAMPLING-001 sin base, red ni UP previas."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from uuid import UUID

from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "platform-web" / "backend"
sys.path.insert(0, str(BACKEND))

from app.dbi.sampling import (  # noqa: E402
    DBISamplingConflict,
    DBISamplingPlanRequest,
    DBISamplingProfile,
    build_sampling_plan,
)
from app.dbi.spatial import GeoJSONMultiPolygon  # noqa: E402

TENANT = "tenant-sampling-ci"
ORG = "organization-sampling-ci"
FARM = UUID("10000000-0000-4000-8000-000000000078")
PLOT = UUID("20000000-0000-4000-8000-000000000078")


def _multipolygon(min_lon, min_lat, max_lon, max_lat) -> GeoJSONMultiPolygon:
    return GeoJSONMultiPolygon.model_validate(
        {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [
                        [min_lon, min_lat],
                        [max_lon, min_lat],
                        [max_lon, max_lat],
                        [min_lon, max_lat],
                        [min_lon, min_lat],
                    ]
                ]
            ],
        }
    )


BOUNDARY = _multipolygon(-79.8100, -3.3000, -79.8000, -3.2920)
EXCLUSION = _multipolygon(-79.8060, -3.2975, -79.8045, -3.2940)


def _request(*, budget=120.0, seed=17, edge_buffer=8.0):
    return DBISamplingPlanRequest(
        tenant_ref=TENANT,
        organization_ref=ORG,
        farm_id=FARM,
        plot_id=PLOT,
        boundary=BOUNDARY,
        exclusions=(EXCLUSION,),
        profile=DBISamplingProfile(
            profile_version="sampling-v1",
            field_budget_minutes=budget,
            sample_minutes=3.0,
            travel_minutes_per_sample=1.5,
            fixed_overhead_minutes=0,
            edge_buffer_m=edge_buffer,
            min_spacing_m=25,
            candidate_multiplier=24,
            reserve_ratio=0.35,
            min_primary_target=20,
            max_primary_points=35,
            max_reserve_points=12,
            seed=seed,
        ),
    )


def _distance_m(left, right) -> float:
    lat0 = math.radians((left.latitude + right.latitude) / 2)
    dx = math.radians(right.longitude - left.longitude) * 6_371_008.8 * math.cos(lat0)
    dy = math.radians(right.latitude - left.latitude) * 6_371_008.8
    return math.hypot(dx, dy)


def validate_determinism_and_budget() -> None:
    request = _request()
    first = build_sampling_plan(request)
    replay = build_sampling_plan(request)
    assert first == replay
    assert first.plan_id == replay.plan_id
    assert first.budget.capacity_points == 26
    assert first.budget.primary_count == 26
    assert first.budget.reserve_count == 10
    assert first.budget.target_status == "within_target"
    assert len(first.points) == 36

    shorter = build_sampling_plan(_request(budget=60.0))
    assert shorter.budget.capacity_points == 13
    assert shorter.budget.primary_count == 13
    assert shorter.budget.target_status == "below_target"
    assert shorter.plan_id != first.plan_id

    alternate_seed = build_sampling_plan(_request(seed=18))
    assert alternate_seed.plan_id != first.plan_id
    assert alternate_seed.points != first.points


def validate_geometry_and_spacing() -> None:
    plan = build_sampling_plan(_request())
    boundary = shape(BOUNDARY.model_dump(mode="python"))
    exclusion = shape(EXCLUSION.model_dump(mode="python"))
    primaries = [point for point in plan.points if point.role == "primary"]
    reserves = [point for point in plan.points if point.role == "reserve"]

    assert sorted(point.route_order for point in primaries) == list(range(1, 27))
    assert {point.reserve_for_sequence for point in reserves} <= set(range(1, 27))

    for point in plan.points:
        geometry = Point(point.longitude, point.latitude)
        assert boundary.covers(geometry)
        assert not exclusion.covers(geometry)

    for index, left in enumerate(primaries):
        for right in primaries[index + 1 :]:
            assert _distance_m(left, right) >= 24.8

    for reserve in reserves:
        parent = primaries[reserve.reserve_for_sequence - 1]
        distance = _distance_m(reserve, parent)
        assert 2.8 <= distance <= 75.5


def validate_first_visit_boundary() -> None:
    plan = build_sampling_plan(_request())
    payload = plan.model_dump(mode="json")
    serialized = str(payload).lower()
    for forbidden in (
        "up_id",
        "productive_unit",
        "model_version",
        "object_key",
        "bucket",
        "url",
        "credential",
        "local_path",
    ):
        assert forbidden not in serialized


def validate_fail_closed() -> None:
    tiny = _multipolygon(-79.80005, -3.30005, -79.80000, -3.30000)
    request = _request(edge_buffer=200.0).model_copy(update={"boundary": tiny})
    try:
        build_sampling_plan(request)
    except DBISamplingConflict:
        pass
    else:
        raise AssertionError("Un buffer que elimina el lote debía fallar cerrado.")


def main() -> None:
    validate_determinism_and_budget()
    validate_geometry_and_spacing()
    validate_first_visit_boundary()
    validate_fail_closed()
    print(
        "DBI-SAMPLING-001 aprobado: presupuesto, balance espacial, reservas y determinismo."
    )


if __name__ == "__main__":
    main()
