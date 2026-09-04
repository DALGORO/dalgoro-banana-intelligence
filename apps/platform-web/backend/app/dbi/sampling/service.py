"""Servicio autoritativo para creación de planes Sampling DBI."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from shapely.geometry import MultiPolygon, mapping, shape
from shapely.ops import unary_union
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dbi.models.agriculture import Farm, Plot
from app.dbi.sampling.contracts import (
    DBISamplingPlan,
    DBISamplingPlanRequest,
    DBISamplingProfile,
)
from app.dbi.sampling.engine import DBISamplingConflict, build_sampling_plan
from app.dbi.sampling.repository import DBISamplingPlanRepository
from app.dbi.spatial import GeoJSONMultiPolygon, boundary_from_database


class DBISamplingUnavailable(DBISamplingConflict):
    """El ámbito agrícola autoritativo no está disponible para Sampling."""


@dataclass(frozen=True, slots=True)
class DBISamplingPlanCreationEvidence:
    plan_id: UUID
    created: bool
    primary_count: int
    reserve_count: int
    target_status: str
    boundary_sha256: str
    exclusions_sha256: str


def _canonical_ref(value: str, *, field: str, max_length: int = 128) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > max_length
        or "*" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise DBISamplingConflict(f"{field} no es canónico.")
    return value


def _as_multipolygon(geometry) -> MultiPolygon | None:
    if geometry.is_empty or geometry.area <= 0:
        return None
    if geometry.geom_type == "Polygon":
        return MultiPolygon([geometry])
    if geometry.geom_type == "MultiPolygon":
        return geometry
    polygons = [item for item in getattr(geometry, "geoms", ()) if item.geom_type == "Polygon"]
    if not polygons:
        return None
    merged = unary_union(polygons)
    if merged.geom_type == "Polygon":
        return MultiPolygon([merged])
    if merged.geom_type == "MultiPolygon":
        return merged
    return None


def _clip_exclusions_to_boundary(
    boundary: GeoJSONMultiPolygon,
    exclusions: tuple[GeoJSONMultiPolygon, ...],
) -> tuple[GeoJSONMultiPolygon, ...]:
    if not exclusions:
        return ()
    boundary_geometry = shape(boundary.model_dump(mode="python"))
    clipped: list[GeoJSONMultiPolygon] = []
    for exclusion in exclusions:
        exclusion_geometry = shape(exclusion.model_dump(mode="python"))
        polygonal = _as_multipolygon(exclusion_geometry.intersection(boundary_geometry))
        if polygonal is None:
            continue
        clipped.append(GeoJSONMultiPolygon.model_validate(mapping(polygonal)))
    return tuple(clipped)


class DBISamplingPlanService:
    """Construye el plan exclusivamente desde la geometría vigente del lote DBI."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise DBISamplingConflict("session debe ser Session.")
        self._session = session
        self._repository = DBISamplingPlanRepository(session)

    def _authoritative_request(
        self,
        *,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        profile: DBISamplingProfile,
        exclusions: tuple[GeoJSONMultiPolygon, ...] = (),
    ) -> DBISamplingPlanRequest:
        tenant_ref = _canonical_ref(tenant_ref, field="tenant_ref")
        organization_ref = _canonical_ref(
            organization_ref,
            field="organization_ref",
        )
        if not isinstance(farm_id, UUID) or not isinstance(plot_id, UUID):
            raise DBISamplingConflict("farm_id y plot_id deben ser UUID.")
        if not isinstance(profile, DBISamplingProfile):
            profile = DBISamplingProfile.model_validate(profile)

        row = self._session.execute(
            select(Farm, Plot)
            .join(Plot, Plot.farm_id == Farm.id)
            .where(
                Farm.id == farm_id,
                Farm.organization_ref == organization_ref,
                Farm.status == "active",
                Plot.id == plot_id,
                Plot.farm_id == farm_id,
                Plot.status == "active",
            )
        ).one_or_none()
        if row is None:
            raise DBISamplingUnavailable("Finca/lote no disponible para Sampling.")
        _farm, plot = row
        if plot.boundary is None:
            raise DBISamplingUnavailable("El lote no tiene boundary vigente.")
        boundary = boundary_from_database(plot.boundary)
        if boundary is None:
            raise DBISamplingUnavailable("El boundary vigente no pudo resolverse.")

        normalized_exclusions = tuple(
            item
            if isinstance(item, GeoJSONMultiPolygon)
            else GeoJSONMultiPolygon.model_validate(item)
            for item in exclusions
        )
        clipped_exclusions = _clip_exclusions_to_boundary(
            boundary,
            normalized_exclusions,
        )
        return DBISamplingPlanRequest(
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            boundary=boundary,
            exclusions=clipped_exclusions,
            profile=profile,
        )

    def build_authoritative_plan(
        self,
        *,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        profile: DBISamplingProfile,
        exclusions: tuple[GeoJSONMultiPolygon, ...] = (),
    ) -> tuple[DBISamplingPlanRequest, DBISamplingPlan]:
        request = self._authoritative_request(
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            profile=profile,
            exclusions=exclusions,
        )
        return request, build_sampling_plan(request)

    def create_plan(
        self,
        *,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
        profile: DBISamplingProfile,
        created_by_ref: str,
        exclusions: tuple[GeoJSONMultiPolygon, ...] = (),
    ) -> DBISamplingPlanCreationEvidence:
        _canonical_ref(created_by_ref, field="created_by_ref")
        request, plan = self.build_authoritative_plan(
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            profile=profile,
            exclusions=exclusions,
        )
        _row, created = self._repository.persist_plan(
            request,
            plan,
            created_by_ref=created_by_ref,
        )
        return DBISamplingPlanCreationEvidence(
            plan_id=plan.plan_id,
            created=created,
            primary_count=plan.budget.primary_count,
            reserve_count=plan.budget.reserve_count,
            target_status=plan.budget.target_status,
            boundary_sha256=plan.boundary_sha256,
            exclusions_sha256=plan.exclusions_sha256,
        )
