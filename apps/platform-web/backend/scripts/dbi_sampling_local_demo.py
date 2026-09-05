"""Genera una demostración local y segura de DBI-SAMPLING-001.

No abre red, no usa PostgreSQL/PostGIS y no necesita credenciales. Produce un
GeoJSON determinista con un lote sintético ecuatoriano, una exclusión, puntos
principales y reservas para inspección visual en QGIS.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(BACKEND_ROOT))

from app.dbi.sampling import (  # noqa: E402
    DBISamplingPlanRequest,
    DBISamplingProfile,
    build_sampling_plan,
)
from app.dbi.spatial import GeoJSONMultiPolygon  # noqa: E402

TENANT_REF = "tenant-local-demo"
ORGANIZATION_REF = "organization-local-demo"
FARM_ID = UUID("10000000-0000-4000-8000-000000000084")
PLOT_ID = UUID("20000000-0000-4000-8000-000000000084")
DEFAULT_OUTPUT = REPOSITORY_ROOT / "tmp" / "dbi_sampling_demo.geojson"


def _multipolygon(
    min_longitude: float,
    min_latitude: float,
    max_longitude: float,
    max_latitude: float,
) -> GeoJSONMultiPolygon:
    return GeoJSONMultiPolygon.model_validate(
        {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [
                        [min_longitude, min_latitude],
                        [max_longitude, min_latitude],
                        [max_longitude, max_latitude],
                        [min_longitude, max_latitude],
                        [min_longitude, min_latitude],
                    ]
                ]
            ],
        }
    )


BOUNDARY = _multipolygon(-79.8100, -3.3000, -79.8000, -3.2920)
EXCLUSION = _multipolygon(-79.8060, -3.2975, -79.8045, -3.2940)


def demo_request() -> DBISamplingPlanRequest:
    """Devuelve el escenario fijo usado por la prueba local reproducible."""

    return DBISamplingPlanRequest(
        tenant_ref=TENANT_REF,
        organization_ref=ORGANIZATION_REF,
        farm_id=FARM_ID,
        plot_id=PLOT_ID,
        boundary=BOUNDARY,
        exclusions=(EXCLUSION,),
        profile=DBISamplingProfile(
            profile_version="sampling-local-demo-v1",
            field_budget_minutes=120.0,
            sample_minutes=3.0,
            travel_minutes_per_sample=1.5,
            fixed_overhead_minutes=0.0,
            edge_buffer_m=8.0,
            min_spacing_m=25.0,
            search_radius_m=12.0,
            candidate_multiplier=24,
            reserve_ratio=0.35,
            min_primary_target=20,
            max_primary_points=35,
            max_reserve_points=12,
            seed=17,
        ),
    )


def build_demo_feature_collection() -> dict[str, Any]:
    """Construye el GeoJSON completo sin escribir archivos."""

    request = demo_request()
    plan = build_sampling_plan(request)
    features: list[dict[str, Any]] = [
        {
            "type": "Feature",
            "id": "boundary",
            "geometry": request.boundary.model_dump(mode="json"),
            "properties": {
                "feature_kind": "boundary",
                "label": "Lote sintético para prueba local",
            },
        }
    ]

    for index, exclusion in enumerate(request.exclusions, start=1):
        features.append(
            {
                "type": "Feature",
                "id": f"exclusion-{index}",
                "geometry": exclusion.model_dump(mode="json"),
                "properties": {
                    "feature_kind": "exclusion",
                    "label": f"Exclusión sintética {index}",
                },
            }
        )

    for point in plan.points:
        features.append(
            {
                "type": "Feature",
                "id": str(point.point_id),
                "geometry": {
                    "type": "Point",
                    "coordinates": [point.longitude, point.latitude],
                },
                "properties": {
                    "feature_kind": "sampling_point",
                    "point_id": str(point.point_id),
                    "role": point.role,
                    "sequence": point.sequence,
                    "route_order": point.route_order,
                    "reserve_for_sequence": point.reserve_for_sequence,
                    "status": point.status,
                    "selection_reason": point.selection_reason,
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "metadata": {
            "demo": "DBI-SAMPLING-001 local",
            "schema_version": plan.schema_version,
            "plan_id": str(plan.plan_id),
            "profile_version": plan.profile_version,
            "tenant_ref": plan.tenant_ref,
            "organization_ref": plan.organization_ref,
            "farm_id": str(plan.farm_id),
            "plot_id": str(plan.plot_id),
            "boundary_sha256": plan.boundary_sha256,
            "exclusions_sha256": plan.exclusions_sha256,
            "budget": plan.budget.model_dump(mode="json"),
        },
        "features": features,
    }


def write_demo(output_path: Path) -> dict[str, Any]:
    """Escribe el GeoJSON de forma explícita y devuelve el payload generado."""

    if not isinstance(output_path, Path):
        output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_demo_feature_collection()
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Genera un GeoJSON determinista de DBI-SAMPLING-001 para abrir en QGIS."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Ruta de salida. Por defecto: {DEFAULT_OUTPUT}",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output = args.output.expanduser().resolve()
    payload = write_demo(output)
    budget = payload["metadata"]["budget"]
    point_features = [
        feature
        for feature in payload["features"]
        if feature["properties"]["feature_kind"] == "sampling_point"
    ]
    primary_count = sum(
        feature["properties"]["role"] == "primary" for feature in point_features
    )
    reserve_count = sum(
        feature["properties"]["role"] == "reserve" for feature in point_features
    )

    print("DBI-SAMPLING-001 · demo local generado correctamente")
    print(f"plan_id: {payload['metadata']['plan_id']}")
    print(f"principales: {primary_count}")
    print(f"reservas: {reserve_count}")
    print(f"estado_presupuesto: {budget['target_status']}")
    print(f"archivo: {output}")
    print("Abra ese archivo .geojson en QGIS para revisar lote, exclusión y puntos.")


if __name__ == "__main__":
    main()
