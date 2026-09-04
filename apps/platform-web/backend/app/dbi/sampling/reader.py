"""Lectura segura de planes Sampling para API/PWA."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.dbi.sampling.contracts import DBISamplingBudget, DBISamplingProfile
from app.dbi.sampling.engine import DBISamplingConflict
from app.dbi.sampling.repository import DBISamplingPlanRepository, point_coordinates
from app.dbi.sampling.service import DBISamplingUnavailable
from app.dbi.spatial import GeoJSONMultiPolygon, boundary_from_database


@dataclass(frozen=True, slots=True)
class DBISamplingPointSnapshot:
    point_id: UUID
    role: str
    sequence: int
    route_order: int | None
    reserve_for_sequence: int | None
    selection_reason: str
    planned_longitude: float
    planned_latitude: float
    observed_longitude: float | None
    observed_latitude: float | None
    status: str
    rejection_reason: str | None
    observed_at: datetime | None


@dataclass(frozen=True, slots=True)
class DBISamplingPlanSnapshot:
    plan_id: UUID
    tenant_ref: str
    organization_ref: str
    farm_id: UUID
    plot_id: UUID
    schema_version: str
    profile_version: str
    profile: DBISamplingProfile
    budget: DBISamplingBudget
    boundary_sha256: str
    exclusions_sha256: str
    boundary: GeoJSONMultiPolygon
    exclusions: GeoJSONMultiPolygon | None
    status: str
    created_at: datetime
    points: tuple[DBISamplingPointSnapshot, ...]


def _decode_json(value: str, *, field: str):
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise DBISamplingConflict(f"{field} persistido no es JSON válido.") from error


class DBISamplingPlanReader:
    """Devuelve únicamente datos de dominio autorizables; nunca infraestructura."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DBISamplingConflict("session debe ser Session.")
        self._repository = DBISamplingPlanRepository(session)

    def read_plan(
        self,
        *,
        plan_id: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> DBISamplingPlanSnapshot:
        row = self._repository.get_plan(
            plan_id=plan_id,
            tenant_ref=tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        if row is None:
            raise DBISamplingUnavailable("Plan Sampling no disponible.")
        boundary = boundary_from_database(row.boundary_snapshot)
        if boundary is None:
            raise DBISamplingConflict("El boundary snapshot no es legible.")
        exclusions = (
            boundary_from_database(row.exclusions_snapshot)
            if row.exclusions_snapshot is not None
            else None
        )
        profile = DBISamplingProfile.model_validate(
            _decode_json(row.profile_json, field="profile_json")
        )
        budget = DBISamplingBudget.model_validate(
            _decode_json(row.budget_json, field="budget_json")
        )

        points: list[DBISamplingPointSnapshot] = []
        for point in self._repository.list_points(plan_id=plan_id):
            planned_lon, planned_lat = point_coordinates(point.planned_point)
            if point.observed_point is not None:
                observed_lon, observed_lat = point_coordinates(point.observed_point)
            else:
                observed_lon = observed_lat = None
            points.append(
                DBISamplingPointSnapshot(
                    point_id=point.id,
                    role=point.role,
                    sequence=point.sequence,
                    route_order=point.route_order,
                    reserve_for_sequence=point.reserve_for_sequence,
                    selection_reason=point.selection_reason,
                    planned_longitude=planned_lon,
                    planned_latitude=planned_lat,
                    observed_longitude=observed_lon,
                    observed_latitude=observed_lat,
                    status=point.status,
                    rejection_reason=point.rejection_reason,
                    observed_at=point.observed_at,
                )
            )
        points.sort(
            key=lambda item: (
                0 if item.role == "primary" else 1,
                item.route_order if item.route_order is not None else 10_000 + item.sequence,
                item.sequence,
            )
        )
        return DBISamplingPlanSnapshot(
            plan_id=row.id,
            tenant_ref=row.tenant_ref,
            organization_ref=row.organization_ref,
            farm_id=row.farm_id,
            plot_id=row.plot_id,
            schema_version=row.schema_version,
            profile_version=row.profile_version,
            profile=profile,
            budget=budget,
            boundary_sha256=row.boundary_sha256,
            exclusions_sha256=row.exclusions_sha256,
            boundary=boundary,
            exclusions=exclusions,
            status=row.status,
            created_at=row.created_at,
            points=tuple(points),
        )


def sampling_plan_geojson(snapshot: DBISamplingPlanSnapshot) -> dict:
    """Contrato GeoJSON simple para PWA; conserva planificado y observado separados."""

    features: list[dict] = [
        {
            "type": "Feature",
            "id": f"boundary:{snapshot.plan_id}",
            "geometry": snapshot.boundary.model_dump(mode="json"),
            "properties": {
                "feature_type": "sampling_boundary",
                "plan_id": str(snapshot.plan_id),
                "status": snapshot.status,
            },
        }
    ]
    if snapshot.exclusions is not None:
        features.append(
            {
                "type": "Feature",
                "id": f"exclusions:{snapshot.plan_id}",
                "geometry": snapshot.exclusions.model_dump(mode="json"),
                "properties": {
                    "feature_type": "sampling_exclusions",
                    "plan_id": str(snapshot.plan_id),
                },
            }
        )

    for point in snapshot.points:
        features.append(
            {
                "type": "Feature",
                "id": str(point.point_id),
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        point.planned_longitude,
                        point.planned_latitude,
                    ],
                },
                "properties": {
                    "feature_type": "sampling_point",
                    "plan_id": str(snapshot.plan_id),
                    "role": point.role,
                    "sequence": point.sequence,
                    "route_order": point.route_order,
                    "reserve_for_sequence": point.reserve_for_sequence,
                    "selection_reason": point.selection_reason,
                    "status": point.status,
                    "rejection_reason": point.rejection_reason,
                    "observed": (
                        {
                            "longitude": point.observed_longitude,
                            "latitude": point.observed_latitude,
                            "observed_at": (
                                point.observed_at.isoformat()
                                if point.observed_at is not None
                                else None
                            ),
                        }
                        if point.observed_longitude is not None
                        else None
                    ),
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
    }
