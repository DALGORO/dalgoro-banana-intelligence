"""Motor puro y determinista de planificación espacial de muestras DBI."""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from uuid import UUID, uuid5

from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union
from shapely.prepared import prep

from app.dbi.sampling.contracts import (
    DBISamplingBudget,
    DBISamplingPlan,
    DBISamplingPlanRequest,
    DBISamplingPoint,
)

_EARTH_RADIUS_M = 6_371_008.8
_PLAN_NAMESPACE = UUID("34751c27-b426-5ec6-96ec-1972e63bec50")
_POINT_NAMESPACE = UUID("1597888a-1e9c-5fd1-af0f-8f697448bb36")
_MAX_LOCAL_EXTENT_M = 100_000.0
_MAX_GRID_CANDIDATES = 50_000


class DBISamplingConflict(ValueError):
    """La solicitud no permite construir un plan seguro y reproducible."""


@dataclass(frozen=True, slots=True)
class _MetricFrame:
    longitude0: float
    latitude0: float

    @property
    def _cos_latitude0(self) -> float:
        return math.cos(math.radians(self.latitude0))

    def forward_xy(self, longitude: float, latitude: float) -> tuple[float, float]:
        x = (
            _EARTH_RADIUS_M
            * math.radians(longitude - self.longitude0)
            * self._cos_latitude0
        )
        y = _EARTH_RADIUS_M * math.radians(latitude - self.latitude0)
        return x, y

    def inverse_xy(self, x: float, y: float) -> tuple[float, float]:
        if abs(self._cos_latitude0) < 1e-9:
            raise DBISamplingConflict("El marco métrico local no es válido cerca del polo.")
        longitude = self.longitude0 + math.degrees(
            x / (_EARTH_RADIUS_M * self._cos_latitude0)
        )
        latitude = self.latitude0 + math.degrees(y / _EARTH_RADIUS_M)
        return longitude, latitude

    def to_metric(self, geometry: BaseGeometry) -> BaseGeometry:
        return transform(
            lambda x, y, z=None: self.forward_xy(x, y),
            geometry,
        )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _geometry_sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _boundary_and_exclusion_hashes(request: DBISamplingPlanRequest) -> tuple[str, str]:
    boundary_payload = request.boundary.model_dump(mode="json")
    boundary_sha = _geometry_sha256(boundary_payload)
    exclusion_hashes = sorted(
        _geometry_sha256(exclusion.model_dump(mode="json"))
        for exclusion in request.exclusions
    )
    exclusions_sha = hashlib.sha256(
        _canonical_json(exclusion_hashes).encode("utf-8")
    ).hexdigest()
    return boundary_sha, exclusions_sha


def _budget(request: DBISamplingPlanRequest) -> DBISamplingBudget:
    profile = request.profile
    usable = profile.field_budget_minutes - profile.fixed_overhead_minutes
    per_primary = profile.sample_minutes + profile.travel_minutes_per_sample
    if per_primary <= 0:
        raise DBISamplingConflict("El tiempo por muestra debe ser positivo.")
    capacity = math.floor(usable / per_primary)
    if capacity < 1:
        raise DBISamplingConflict("El presupuesto no alcanza para una muestra primaria.")
    primary_count = min(capacity, profile.max_primary_points)
    reserve_count = min(
        profile.max_reserve_points,
        math.ceil(primary_count * profile.reserve_ratio),
    )
    if primary_count < profile.min_primary_target:
        target_status = "below_target"
    elif capacity > profile.max_primary_points:
        target_status = "capped"
    else:
        target_status = "within_target"
    return DBISamplingBudget(
        field_budget_minutes=profile.field_budget_minutes,
        fixed_overhead_minutes=profile.fixed_overhead_minutes,
        usable_minutes=usable,
        minutes_per_primary=per_primary,
        capacity_points=capacity,
        primary_count=primary_count,
        reserve_count=reserve_count,
        target_status=target_status,
    )


def _metric_geometry(request: DBISamplingPlanRequest) -> tuple[_MetricFrame, BaseGeometry]:
    boundary = shape(request.boundary.model_dump(mode="python"))
    centroid = boundary.centroid
    frame = _MetricFrame(longitude0=centroid.x, latitude0=centroid.y)
    metric = frame.to_metric(boundary)
    min_x, min_y, max_x, max_y = metric.bounds
    if max(max_x - min_x, max_y - min_y) > _MAX_LOCAL_EXTENT_M:
        raise DBISamplingConflict(
            "El lote supera el alcance del marco métrico local de Sampling V1."
        )

    usable = metric
    if request.profile.edge_buffer_m > 0:
        usable = usable.buffer(-request.profile.edge_buffer_m)
        if usable.is_empty:
            raise DBISamplingConflict(
                "El buffer de borde elimina toda el área utilizable; reduzca edge_buffer_m."
            )

    if request.exclusions:
        exclusions = unary_union(
            [
                frame.to_metric(shape(item.model_dump(mode="python")))
                for item in request.exclusions
            ]
        )
        usable = usable.difference(exclusions)
        if usable.is_empty:
            raise DBISamplingConflict("Las exclusiones eliminan toda el área utilizable.")

    if not usable.is_valid or usable.area <= 0:
        raise DBISamplingConflict("El área utilizable de muestreo no es válida.")
    return frame, usable


def _candidate_grid(
    usable: BaseGeometry,
    *,
    target_points: int,
    candidate_multiplier: int,
    seed: int,
) -> list[Point]:
    target_candidates = max(64, target_points * candidate_multiplier)
    step = max(1.0, math.sqrt(usable.area / target_candidates))
    min_x, min_y, max_x, max_y = usable.bounds
    prepared = prep(usable)
    rng = random.Random(seed)

    for _ in range(7):
        offset_x = rng.random() * step
        offset_y = rng.random() * step
        points: list[Point] = []
        y = min_y + offset_y
        while y <= max_y and len(points) <= _MAX_GRID_CANDIDATES:
            x = min_x + offset_x
            while x <= max_x and len(points) <= _MAX_GRID_CANDIDATES:
                candidate = Point(x, y)
                if prepared.covers(candidate):
                    points.append(candidate)
                x += step
            y += step
        representative = usable.representative_point()
        if prepared.covers(representative):
            points.append(representative)
        if len(points) >= target_points * 4:
            points.sort(key=lambda point: (round(point.x, 6), round(point.y, 6)))
            return points
        step *= 0.7

    raise DBISamplingConflict(
        "No se pudo generar un conjunto suficiente de candidatos dentro del lote."
    )


def _squared_distance(left: Point, right: Point) -> float:
    dx = left.x - right.x
    dy = left.y - right.y
    return dx * dx + dy * dy


def _select_balanced(
    candidates: list[Point],
    *,
    count: int,
    min_spacing_m: float,
    anchor: Point,
) -> list[Point]:
    if count < 1:
        return []
    available = list(candidates)
    first = min(
        available,
        key=lambda point: (_squared_distance(point, anchor), point.x, point.y),
    )
    selected = [first]
    available.remove(first)
    minimum_sq = min_spacing_m * min_spacing_m

    while len(selected) < count:
        best: Point | None = None
        best_min_sq = -1.0
        for candidate in available:
            nearest_sq = min(_squared_distance(candidate, chosen) for chosen in selected)
            if nearest_sq < minimum_sq:
                continue
            if (
                nearest_sq > best_min_sq
                or (
                    math.isclose(nearest_sq, best_min_sq)
                    and best is not None
                    and (candidate.x, candidate.y) < (best.x, best.y)
                )
            ):
                best = candidate
                best_min_sq = nearest_sq
        if best is None:
            raise DBISamplingConflict(
                "El lote no admite la cantidad solicitada con la separación mínima configurada."
            )
        selected.append(best)
        available.remove(best)
    return selected


def _route_orders(points: list[Point]) -> dict[int, int]:
    """Orden euclidiano aproximado; no afirma conocer caminos o accesos de la finca."""

    if not points:
        return {}
    remaining = set(range(len(points)))
    current = min(remaining, key=lambda index: (points[index].x, points[index].y))
    route: list[int] = []
    while remaining:
        route.append(current)
        remaining.remove(current)
        if not remaining:
            break
        current = min(
            remaining,
            key=lambda index: (
                _squared_distance(points[current], points[index]),
                points[index].x,
                points[index].y,
            ),
        )
    return {point_index: order for order, point_index in enumerate(route, start=1)}


def _select_reserves(
    candidates: list[Point],
    primaries: list[Point],
    *,
    count: int,
    min_spacing_m: float,
) -> list[tuple[Point, int]]:
    if count == 0:
        return []
    primary_keys = {(round(point.x, 6), round(point.y, 6)) for point in primaries}
    available = [
        point
        for point in candidates
        if (round(point.x, 6), round(point.y, 6)) not in primary_keys
    ]
    reserve_min_m = max(3.0, min(12.0, min_spacing_m * 0.25))
    reserve_max_m = max(50.0, min_spacing_m * 3.0)
    reserve_min_sq = reserve_min_m * reserve_min_m
    reserve_max_sq = reserve_max_m * reserve_max_m
    selected: list[tuple[Point, int]] = []

    for reserve_index in range(count):
        parent_index = reserve_index % len(primaries)
        parent = primaries[parent_index]
        options: list[tuple[float, Point]] = []
        for candidate in available:
            distance_sq = _squared_distance(candidate, parent)
            if not reserve_min_sq <= distance_sq <= reserve_max_sq:
                continue
            if any(
                _squared_distance(candidate, existing) < reserve_min_sq
                for existing, _ in selected
            ):
                continue
            options.append((distance_sq, candidate))
        if not options:
            raise DBISamplingConflict(
                "No existen suficientes reservas cercanas bajo el perfil configurado."
            )
        _, chosen = min(options, key=lambda item: (item[0], item[1].x, item[1].y))
        selected.append((chosen, parent_index))
        available.remove(chosen)
    return selected


def _plan_id(
    request: DBISamplingPlanRequest,
    *,
    boundary_sha: str,
    exclusions_sha: str,
) -> UUID:
    identity = {
        "tenant_ref": request.tenant_ref,
        "organization_ref": request.organization_ref,
        "farm_id": str(request.farm_id),
        "plot_id": str(request.plot_id),
        "boundary_sha256": boundary_sha,
        "exclusions_sha256": exclusions_sha,
        "profile": request.profile.model_dump(mode="json"),
    }
    return uuid5(_PLAN_NAMESPACE, _canonical_json(identity))


def _point_id(plan_id: UUID, *, role: str, sequence: int, longitude: float, latitude: float) -> UUID:
    return uuid5(
        _POINT_NAMESPACE,
        f"{plan_id}:{role}:{sequence}:{longitude:.7f}:{latitude:.7f}",
    )


def build_sampling_plan(request: DBISamplingPlanRequest) -> DBISamplingPlan:
    """Construye un plan reproducible; no persiste ni convierte candidatos en UP."""

    if not isinstance(request, DBISamplingPlanRequest):
        request = DBISamplingPlanRequest.model_validate(request)
    budget = _budget(request)
    boundary_sha, exclusions_sha = _boundary_and_exclusion_hashes(request)
    plan_id = _plan_id(
        request,
        boundary_sha=boundary_sha,
        exclusions_sha=exclusions_sha,
    )
    frame, usable = _metric_geometry(request)
    total_required = budget.primary_count + budget.reserve_count
    candidates = _candidate_grid(
        usable,
        target_points=total_required,
        candidate_multiplier=request.profile.candidate_multiplier,
        seed=request.profile.seed,
    )
    primaries = _select_balanced(
        candidates,
        count=budget.primary_count,
        min_spacing_m=request.profile.min_spacing_m,
        anchor=usable.representative_point(),
    )
    reserves = _select_reserves(
        candidates,
        primaries,
        count=budget.reserve_count,
        min_spacing_m=request.profile.min_spacing_m,
    )
    route_orders = _route_orders(primaries)

    points: list[DBISamplingPoint] = []
    for index, point in enumerate(primaries, start=1):
        longitude, latitude = frame.inverse_xy(point.x, point.y)
        longitude = round(longitude, 7)
        latitude = round(latitude, 7)
        points.append(
            DBISamplingPoint(
                point_id=_point_id(
                    plan_id,
                    role="primary",
                    sequence=index,
                    longitude=longitude,
                    latitude=latitude,
                ),
                role="primary",
                sequence=index,
                longitude=longitude,
                latitude=latitude,
                route_order=route_orders[index - 1],
                selection_reason="balanced",
            )
        )

    for index, (point, parent_index) in enumerate(reserves, start=1):
        longitude, latitude = frame.inverse_xy(point.x, point.y)
        longitude = round(longitude, 7)
        latitude = round(latitude, 7)
        points.append(
            DBISamplingPoint(
                point_id=_point_id(
                    plan_id,
                    role="reserve",
                    sequence=index,
                    longitude=longitude,
                    latitude=latitude,
                ),
                role="reserve",
                sequence=index,
                longitude=longitude,
                latitude=latitude,
                reserve_for_sequence=parent_index + 1,
                selection_reason="nearby_reserve",
            )
        )

    return DBISamplingPlan(
        plan_id=plan_id,
        tenant_ref=request.tenant_ref,
        organization_ref=request.organization_ref,
        farm_id=request.farm_id,
        plot_id=request.plot_id,
        profile_version=request.profile.profile_version,
        boundary_sha256=boundary_sha,
        exclusions_sha256=exclusions_sha,
        budget=budget,
        points=tuple(points),
    )
