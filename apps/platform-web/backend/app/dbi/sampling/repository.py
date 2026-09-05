"""Persistencia idempotente de planes y puntos Sampling DBI."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from uuid import UUID

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import MultiPolygon, Point, shape
from shapely.ops import unary_union
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.dbi.models.sampling import DBISamplingPlanRecord, DBISamplingPointRecord
from app.dbi.sampling.contracts import DBISamplingPlan, DBISamplingPlanRequest
from app.dbi.sampling.engine import DBISamplingConflict
from app.dbi.spatial import DBI_SPATIAL_SRID


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _exclusions_geometry(request: DBISamplingPlanRequest) -> MultiPolygon | None:
    if not request.exclusions:
        return None
    combined = unary_union(
        [shape(item.model_dump(mode="python")) for item in request.exclusions]
    )
    if combined.is_empty:
        return None
    if combined.geom_type == "Polygon":
        return MultiPolygon([combined])
    if combined.geom_type == "MultiPolygon":
        return combined
    polygons = [geometry for geometry in combined.geoms if geometry.geom_type == "Polygon"]
    if not polygons:
        return None
    merged = unary_union(polygons)
    if merged.geom_type == "Polygon":
        return MultiPolygon([merged])
    if merged.geom_type != "MultiPolygon":
        raise DBISamplingConflict("Las exclusiones no producen una geometría poligonal válida.")
    return merged


def point_coordinates(value) -> tuple[float, float]:
    geometry = to_shape(value)
    if geometry.geom_type != "Point":
        raise DBISamplingConflict("La geometría persistida del punto no es POINT.")
    return round(float(geometry.x), 7), round(float(geometry.y), 7)


class DBISamplingPlanRepository:
    """Escribe y bloquea Sampling sin commit/rollback propios."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DBISamplingConflict("session debe ser Session.")
        self._session = session

    def flush(self) -> None:
        self._session.flush()

    def persist_plan(
        self,
        request: DBISamplingPlanRequest,
        plan: DBISamplingPlan,
        *,
        created_by_ref: str,
    ) -> tuple[DBISamplingPlanRecord, bool]:
        if not isinstance(request, DBISamplingPlanRequest):
            request = DBISamplingPlanRequest.model_validate(request)
        if not isinstance(plan, DBISamplingPlan):
            plan = DBISamplingPlan.model_validate(plan)
        if (
            plan.tenant_ref != request.tenant_ref
            or plan.organization_ref != request.organization_ref
            or plan.farm_id != request.farm_id
            or plan.plot_id != request.plot_id
            or plan.profile_version != request.profile.profile_version
        ):
            raise DBISamplingConflict("El plan diverge de la solicitud autoritativa.")
        if (
            not isinstance(created_by_ref, str)
            or not created_by_ref
            or created_by_ref.strip() != created_by_ref
            or len(created_by_ref) > 128
        ):
            raise DBISamplingConflict("created_by_ref no es canónico.")

        profile_json = canonical_json(request.profile.model_dump(mode="json"))
        profile_sha256 = sha256_text(profile_json)
        budget_json = canonical_json(plan.budget.model_dump(mode="json"))
        boundary = shape(request.boundary.model_dump(mode="python"))
        exclusions = _exclusions_geometry(request)

        inserted = self._session.execute(
            postgresql_insert(DBISamplingPlanRecord)
            .values(
                id=plan.plan_id,
                tenant_ref=plan.tenant_ref,
                organization_ref=plan.organization_ref,
                farm_id=plan.farm_id,
                plot_id=plan.plot_id,
                schema_version=plan.schema_version,
                profile_version=plan.profile_version,
                profile_json=profile_json,
                profile_sha256=profile_sha256,
                boundary_sha256=plan.boundary_sha256,
                exclusions_sha256=plan.exclusions_sha256,
                budget_json=budget_json,
                boundary_snapshot=from_shape(
                    boundary,
                    srid=DBI_SPATIAL_SRID,
                    extended=True,
                ),
                exclusions_snapshot=(
                    from_shape(exclusions, srid=DBI_SPATIAL_SRID, extended=True)
                    if exclusions is not None
                    else None
                ),
                status="planned",
                created_by_ref=created_by_ref,
            )
            .on_conflict_do_nothing()
            .returning(DBISamplingPlanRecord.id)
        ).scalar_one_or_none()

        if plan.points:
            point_values = []
            for point in plan.points:
                point_values.append(
                    {
                        "id": point.point_id,
                        "plan_id": plan.plan_id,
                        "role": point.role,
                        "sequence": point.sequence,
                        "route_order": point.route_order,
                        "reserve_for_sequence": point.reserve_for_sequence,
                        "selection_reason": point.selection_reason,
                        "planned_point": from_shape(
                            Point(point.longitude, point.latitude),
                            srid=DBI_SPATIAL_SRID,
                            extended=True,
                        ),
                        "observed_point": None,
                        "status": "planned",
                        "rejection_reason": None,
                        "observed_at": None,
                    }
                )
            self._session.execute(
                postgresql_insert(DBISamplingPointRecord)
                .values(point_values)
                .on_conflict_do_nothing()
            )

        self._session.flush()
        row = self._session.get(DBISamplingPlanRecord, plan.plan_id)
        if row is None:
            raise DBISamplingConflict("El plan no quedó persistido.")

        immutable_exact = (
            row.tenant_ref == plan.tenant_ref
            and row.organization_ref == plan.organization_ref
            and row.farm_id == plan.farm_id
            and row.plot_id == plan.plot_id
            and row.schema_version == plan.schema_version
            and row.profile_version == plan.profile_version
            and row.profile_json == profile_json
            and row.profile_sha256 == profile_sha256
            and row.boundary_sha256 == plan.boundary_sha256
            and row.exclusions_sha256 == plan.exclusions_sha256
            and row.budget_json == budget_json
            and to_shape(row.boundary_snapshot).equals_exact(boundary, tolerance=1e-12)
        )
        if exclusions is None:
            immutable_exact = immutable_exact and row.exclusions_snapshot is None
        else:
            immutable_exact = (
                immutable_exact
                and row.exclusions_snapshot is not None
                and to_shape(row.exclusions_snapshot).equals(exclusions)
            )
        if not immutable_exact:
            raise DBISamplingConflict(
                "La identidad Sampling ya representa un snapshot divergente."
            )

        persisted_points = self.list_points(plan_id=plan.plan_id)
        expected = sorted(plan.points, key=lambda point: (point.role, point.sequence))
        if len(persisted_points) != len(expected):
            raise DBISamplingConflict("El conjunto persistido de puntos está incompleto.")
        for actual, planned in zip(persisted_points, expected, strict=True):
            if (
                actual.id != planned.point_id
                or actual.role != planned.role
                or actual.sequence != planned.sequence
                or actual.route_order != planned.route_order
                or actual.reserve_for_sequence != planned.reserve_for_sequence
                or actual.selection_reason != planned.selection_reason
                or point_coordinates(actual.planned_point)
                != (round(planned.longitude, 7), round(planned.latitude, 7))
            ):
                raise DBISamplingConflict(
                    "La identidad de un punto Sampling diverge del plan reproducible."
                )

        return row, inserted is not None

    def get_plan(
        self,
        *,
        plan_id: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> DBISamplingPlanRecord | None:
        return self._session.execute(
            select(DBISamplingPlanRecord).where(
                DBISamplingPlanRecord.id == plan_id,
                DBISamplingPlanRecord.tenant_ref == tenant_ref,
                DBISamplingPlanRecord.farm_id == farm_id,
                DBISamplingPlanRecord.plot_id == plot_id,
                DBISamplingPlanRecord.status != "retired",
            )
        ).scalar_one_or_none()

    def get_plan_for_update(
        self,
        *,
        plan_id: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> DBISamplingPlanRecord | None:
        return self._session.execute(
            select(DBISamplingPlanRecord)
            .where(
                DBISamplingPlanRecord.id == plan_id,
                DBISamplingPlanRecord.tenant_ref == tenant_ref,
                DBISamplingPlanRecord.farm_id == farm_id,
                DBISamplingPlanRecord.plot_id == plot_id,
                DBISamplingPlanRecord.status != "retired",
            )
            .with_for_update()
        ).scalar_one_or_none()

    def list_points(self, *, plan_id: UUID) -> list[DBISamplingPointRecord]:
        return list(
            self._session.execute(
                select(DBISamplingPointRecord)
                .where(DBISamplingPointRecord.plan_id == plan_id)
                .order_by(DBISamplingPointRecord.role, DBISamplingPointRecord.sequence)
            ).scalars().all()
        )

    def get_points_for_update(
        self,
        *,
        plan_id: UUID,
        point_ids: Iterable[UUID],
    ) -> list[DBISamplingPointRecord]:
        ids = sorted(set(point_ids), key=str)
        if not ids:
            return []
        return list(
            self._session.execute(
                select(DBISamplingPointRecord)
                .where(
                    DBISamplingPointRecord.plan_id == plan_id,
                    DBISamplingPointRecord.id.in_(ids),
                )
                .order_by(DBISamplingPointRecord.id)
                .with_for_update()
            ).scalars().all()
        )
