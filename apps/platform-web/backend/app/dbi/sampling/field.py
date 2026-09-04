"""Mutaciones transaccionales de verdad-terreno para Sampling DBI."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy.orm import Session

from app.dbi.models.sampling import DBISamplingPlanRecord, DBISamplingPointRecord
from app.dbi.sampling.contracts import DBISamplingProfile
from app.dbi.sampling.engine import DBISamplingConflict
from app.dbi.sampling.repository import DBISamplingPlanRepository, point_coordinates
from app.dbi.sampling.service import DBISamplingUnavailable
from app.dbi.spatial import DBI_SPATIAL_SRID

_EARTH_RADIUS_M = 6_371_008.8
_REJECTION_REASONS = frozenset(
    {
        "road",
        "infrastructure",
        "canal_or_drain",
        "non_banana",
        "missing_plant",
        "inaccessible",
        "unsafe",
        "other",
    }
)


@dataclass(frozen=True, slots=True)
class DBISamplingPointMutationEvidence:
    plan_id: UUID
    point_id: UUID
    status: str
    changed: bool
    observed_at: datetime
    reserve_point_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class DBISamplingPlanCompletionEvidence:
    plan_id: UUID
    status: str
    changed: bool


def _aware(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DBISamplingConflict("observed_at debe incluir zona horaria.")
    return value


def _coordinate(value: float, *, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DBISamplingConflict(f"{field} debe ser numérico.")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise DBISamplingConflict(f"{field} está fuera de rango.")
    return round(result, 7)


def _distance_m(
    left_lon: float,
    left_lat: float,
    right_lon: float,
    right_lat: float,
) -> float:
    latitude0 = math.radians((left_lat + right_lat) / 2.0)
    dx = (
        math.radians(right_lon - left_lon)
        * _EARTH_RADIUS_M
        * math.cos(latitude0)
    )
    dy = math.radians(right_lat - left_lat) * _EARTH_RADIUS_M
    return math.hypot(dx, dy)


def _profile(plan: DBISamplingPlanRecord) -> DBISamplingProfile:
    try:
        payload = json.loads(plan.profile_json)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise DBISamplingConflict("profile_json persistido no es válido.") from error
    return DBISamplingProfile.model_validate(payload)


def _same_time(left: datetime | None, right: datetime) -> bool:
    return left is not None and left == right


class DBISamplingFieldService:
    """Aplica mutaciones de campo con locks y replay exacto."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DBISamplingConflict("session debe ser Session.")
        self._repository = DBISamplingPlanRepository(session)

    def _plan_for_update(
        self,
        *,
        plan_id: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> DBISamplingPlanRecord:
        plan = self._repository.get_plan_for_update(
            plan_id=plan_id,
            tenant_ref=tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        if plan is None:
            raise DBISamplingUnavailable("Plan Sampling no disponible.")
        return plan

    @staticmethod
    def _assert_mutable_plan(plan: DBISamplingPlanRecord, observed_at: datetime) -> None:
        if plan.status not in {"planned", "in_field"}:
            raise DBISamplingConflict("El plan Sampling ya no admite observaciones.")
        if observed_at < plan.created_at:
            raise DBISamplingConflict("La observación no puede preceder al plan.")

    @staticmethod
    def _mark_in_field(plan: DBISamplingPlanRecord) -> None:
        if plan.status == "planned":
            plan.status = "in_field"

    def _point_for_update(
        self,
        *,
        plan_id: UUID,
        point_id: UUID,
    ) -> DBISamplingPointRecord:
        points = self._repository.get_points_for_update(
            plan_id=plan_id,
            point_ids=(point_id,),
        )
        if len(points) != 1:
            raise DBISamplingUnavailable("Punto Sampling no disponible.")
        return points[0]

    @staticmethod
    def _validate_observed_location(
        plan: DBISamplingPlanRecord,
        point: DBISamplingPointRecord,
        *,
        longitude: float,
        latitude: float,
    ) -> None:
        observed = Point(longitude, latitude)
        boundary = to_shape(plan.boundary_snapshot)
        if not boundary.covers(observed):
            raise DBISamplingConflict("La coordenada observada está fuera del lote.")
        if plan.exclusions_snapshot is not None:
            exclusions = to_shape(plan.exclusions_snapshot)
            if exclusions.covers(observed):
                raise DBISamplingConflict("La coordenada observada cae en una exclusión.")
        planned_lon, planned_lat = point_coordinates(point.planned_point)
        if (
            _distance_m(planned_lon, planned_lat, longitude, latitude)
            > _profile(plan).search_radius_m
        ):
            raise DBISamplingConflict("La coordenada observada supera el radio GPS del perfil.")

    def validate_point(
        self,
        *,
        plan_id: UUID,
        point_id: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        longitude: float,
        latitude: float,
        observed_at: datetime,
    ) -> DBISamplingPointMutationEvidence:
        observed_at = _aware(observed_at)
        longitude = _coordinate(longitude, field="longitude", minimum=-180, maximum=180)
        latitude = _coordinate(latitude, field="latitude", minimum=-90, maximum=90)
        plan = self._plan_for_update(
            plan_id=plan_id,
            tenant_ref=tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        self._assert_mutable_plan(plan, observed_at)
        point = self._point_for_update(plan_id=plan_id, point_id=point_id)

        if point.status == "validated":
            if (
                point.observed_point is not None
                and point_coordinates(point.observed_point) == (longitude, latitude)
                and _same_time(point.observed_at, observed_at)
            ):
                return DBISamplingPointMutationEvidence(
                    plan_id=plan.id,
                    point_id=point.id,
                    status=point.status,
                    changed=False,
                    observed_at=observed_at,
                )
            raise DBISamplingConflict("El punto ya fue validado con evidencia divergente.")
        if point.status != "planned":
            raise DBISamplingConflict("El punto ya tiene una decisión de campo.")

        self._validate_observed_location(
            plan,
            point,
            longitude=longitude,
            latitude=latitude,
        )
        self._mark_in_field(plan)
        point.status = "validated"
        point.observed_point = from_shape(
            Point(longitude, latitude),
            srid=DBI_SPATIAL_SRID,
            extended=True,
        )
        point.rejection_reason = None
        point.observed_at = observed_at
        self._repository.flush()
        return DBISamplingPointMutationEvidence(
            plan_id=plan.id,
            point_id=point.id,
            status=point.status,
            changed=True,
            observed_at=observed_at,
        )

    def reject_point(
        self,
        *,
        plan_id: UUID,
        point_id: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        rejection_reason: str,
        observed_at: datetime,
    ) -> DBISamplingPointMutationEvidence:
        observed_at = _aware(observed_at)
        if rejection_reason not in _REJECTION_REASONS:
            raise DBISamplingConflict("rejection_reason no está normalizado.")
        plan = self._plan_for_update(
            plan_id=plan_id,
            tenant_ref=tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        self._assert_mutable_plan(plan, observed_at)
        point = self._point_for_update(plan_id=plan_id, point_id=point_id)

        if point.status == "rejected":
            if point.rejection_reason == rejection_reason and _same_time(
                point.observed_at,
                observed_at,
            ):
                return DBISamplingPointMutationEvidence(
                    plan_id=plan.id,
                    point_id=point.id,
                    status=point.status,
                    changed=False,
                    observed_at=observed_at,
                )
            raise DBISamplingConflict("El rechazo persistido diverge del replay.")
        if point.status != "planned":
            raise DBISamplingConflict("El punto ya tiene una decisión de campo.")

        self._mark_in_field(plan)
        point.status = "rejected"
        point.rejection_reason = rejection_reason
        point.observed_point = None
        point.observed_at = observed_at
        self._repository.flush()
        return DBISamplingPointMutationEvidence(
            plan_id=plan.id,
            point_id=point.id,
            status=point.status,
            changed=True,
            observed_at=observed_at,
        )

    def substitute_point(
        self,
        *,
        plan_id: UUID,
        primary_point_id: UUID,
        reserve_point_id: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        rejection_reason: str,
        longitude: float,
        latitude: float,
        observed_at: datetime,
    ) -> DBISamplingPointMutationEvidence:
        observed_at = _aware(observed_at)
        longitude = _coordinate(longitude, field="longitude", minimum=-180, maximum=180)
        latitude = _coordinate(latitude, field="latitude", minimum=-90, maximum=90)
        if rejection_reason not in _REJECTION_REASONS:
            raise DBISamplingConflict("rejection_reason no está normalizado.")
        if primary_point_id == reserve_point_id:
            raise DBISamplingConflict("La reserva debe ser un punto distinto.")

        plan = self._plan_for_update(
            plan_id=plan_id,
            tenant_ref=tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        self._assert_mutable_plan(plan, observed_at)
        rows = self._repository.get_points_for_update(
            plan_id=plan_id,
            point_ids=(primary_point_id, reserve_point_id),
        )
        if len(rows) != 2:
            raise DBISamplingUnavailable("Principal/reserva Sampling no disponibles.")
        by_id = {row.id: row for row in rows}
        primary = by_id[primary_point_id]
        reserve = by_id[reserve_point_id]
        if (
            primary.role != "primary"
            or reserve.role != "reserve"
            or reserve.reserve_for_sequence != primary.sequence
        ):
            raise DBISamplingConflict("La reserva no pertenece al punto principal indicado.")

        if primary.status == "substituted" and reserve.status == "validated":
            if (
                primary.rejection_reason == rejection_reason
                and _same_time(primary.observed_at, observed_at)
                and reserve.observed_point is not None
                and point_coordinates(reserve.observed_point) == (longitude, latitude)
                and _same_time(reserve.observed_at, observed_at)
            ):
                return DBISamplingPointMutationEvidence(
                    plan_id=plan.id,
                    point_id=primary.id,
                    reserve_point_id=reserve.id,
                    status=primary.status,
                    changed=False,
                    observed_at=observed_at,
                )
            raise DBISamplingConflict("La sustitución persistida diverge del replay.")
        if primary.status != "planned" or reserve.status != "planned":
            raise DBISamplingConflict("Principal o reserva ya tienen decisión de campo.")

        self._validate_observed_location(
            plan,
            reserve,
            longitude=longitude,
            latitude=latitude,
        )
        self._mark_in_field(plan)
        primary.status = "substituted"
        primary.rejection_reason = rejection_reason
        primary.observed_point = None
        primary.observed_at = observed_at
        reserve.status = "validated"
        reserve.rejection_reason = None
        reserve.observed_point = from_shape(
            Point(longitude, latitude),
            srid=DBI_SPATIAL_SRID,
            extended=True,
        )
        reserve.observed_at = observed_at
        self._repository.flush()
        return DBISamplingPointMutationEvidence(
            plan_id=plan.id,
            point_id=primary.id,
            reserve_point_id=reserve.id,
            status=primary.status,
            changed=True,
            observed_at=observed_at,
        )

    def complete_plan(
        self,
        *,
        plan_id: UUID,
        tenant_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> DBISamplingPlanCompletionEvidence:
        plan = self._plan_for_update(
            plan_id=plan_id,
            tenant_ref=tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        if plan.status == "completed":
            return DBISamplingPlanCompletionEvidence(
                plan_id=plan.id,
                status=plan.status,
                changed=False,
            )
        if plan.status not in {"planned", "in_field"}:
            raise DBISamplingConflict("El plan no puede completarse desde su estado actual.")

        snapshot = self._repository.list_points(plan_id=plan_id)
        locked = self._repository.get_points_for_update(
            plan_id=plan_id,
            point_ids=(point.id for point in snapshot),
        )
        primaries = [point for point in locked if point.role == "primary"]
        reserves = [point for point in locked if point.role == "reserve"]
        if any(point.status == "planned" for point in primaries):
            raise DBISamplingConflict("Aún existen puntos principales sin decisión de campo.")
        for primary in primaries:
            if primary.status == "substituted" and not any(
                reserve.reserve_for_sequence == primary.sequence
                and reserve.status == "validated"
                for reserve in reserves
            ):
                raise DBISamplingConflict("Una sustitución no tiene reserva validada.")

        plan.status = "completed"
        self._repository.flush()
        return DBISamplingPlanCompletionEvidence(
            plan_id=plan.id,
            status=plan.status,
            changed=True,
        )
