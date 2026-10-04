"""Lectura autorizable de cronología Raster real para DBI-MAP-002."""

from __future__ import annotations

import json
import math
import re
from urllib.parse import quote
from uuid import UUID

from geoalchemy2.shape import to_shape
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.dbi.models.agriculture import Campaign, Farm, Plot
from app.dbi.models.campaign_artifacts import DBICampaignArtifact
from app.dbi.models.raster_products import DBIRasterProduct
from app.schemas.dbi_map import (
    MAP_LAYER_CATALOG,
    MapComparisonCapability,
    PlotMapTimelineResponse,
    ProfessionalReviewStatus,
    RasterTileTimelineEntry,
)


class DBIMapTimelineUnavailable(LookupError):
    """El lote/campaña/raster solicitado no está disponible dentro del scope."""


# Esta proyección publica exclusivamente la ortofoto RGB observada, no
# inferencias de la Campaign. Por eso una Campaign técnica real puede mostrar
# su fuente RGB desde DRAFT/PROCESSING; las capas inferidas siguen gobernadas
# por sus propios estados y contratos.
_VISIBLE_RGB_CAMPAIGN_STATES = frozenset(
    {
        "DRAFT",
        "PROCESSING",
        "ANALYZED",
        "TECHNICAL_REVIEW",
        "SAMPLING_READY",
        "FIELD_WORK",
        "FIELD_COMPLETED",
        "APPROVED",
        "PUBLISHED",
    }
)


_EPSG_PATTERN = re.compile(r"^EPSG:(?P<code>[1-9][0-9]{2,6})$")


def _validated_bounds(
    bounds_json: str,
) -> tuple[float, float, float, float] | None:
    try:
        raw = json.loads(bounds_json)
    except (TypeError, ValueError):
        return None

    if not isinstance(raw, list) or len(raw) != 4:
        return None
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in raw
    ):
        return None

    west, south, east, north = (float(value) for value in raw)
    if not all(math.isfinite(value) for value in (west, south, east, north)):
        return None
    if west >= east or south >= north:
        return None
    return west, south, east, north


def _valid_wgs84_bounds(
    bounds: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    west, south, east, north = bounds
    if (
        -180.0 <= west < east <= 180.0
        and -90.0 <= south < north <= 90.0
    ):
        return bounds
    return None


def raster_bounds_wgs84(
    session: Session,
    *,
    crs: str,
    bounds_json: str,
) -> tuple[float, float, float, float] | None:
    """Deriva viewport WGS84 sin convertir el Raster en autoridad territorial."""

    bounds = _validated_bounds(bounds_json)
    if bounds is None:
        return None

    match = _EPSG_PATTERN.fullmatch(str(crs).strip())
    if match is None:
        return None
    srid = int(match.group("code"))

    if srid == 4326:
        return _valid_wgs84_bounds(bounds)

    west, south, east, north = bounds
    transformed = func.ST_Transform(
        func.ST_MakeEnvelope(west, south, east, north, srid),
        4326,
    )
    box = func.Box3D(transformed)
    try:
        row = session.execute(
            select(
                func.ST_XMin(box),
                func.ST_YMin(box),
                func.ST_XMax(box),
                func.ST_YMax(box),
            )
        ).one()
    except SQLAlchemyError:
        return None

    try:
        candidate = tuple(float(value) for value in row)
    except (TypeError, ValueError):
        return None
    if len(candidate) != 4 or not all(math.isfinite(value) for value in candidate):
        return None
    return _valid_wgs84_bounds(candidate)  # type: ignore[arg-type]


def _review_status(campaign_status: str) -> ProfessionalReviewStatus:
    if campaign_status in {"APPROVED", "PUBLISHED"}:
        return ProfessionalReviewStatus.APPROVED
    return ProfessionalReviewStatus.PENDING


def _tile_template(
    *,
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    product_id: UUID,
) -> str:
    organization = quote(organization_ref, safe="")
    return (
        f"/api/v1/dbi/organizations/{organization}/farms/{farm_id}/plots/"
        f"{plot_id}/raster-products/{product_id}/tiles/"
        "{z}/{x}/{y}.png"
    )


class DBIMapTimelineReader:
    """Proyecta Campaign + Artifact + Raster a una vista segura para MapLibre."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session debe ser Session.")
        self._session = session

    def _plot_bounds(
        self,
        *,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> tuple[float, float, float, float] | None:
        row = self._session.execute(
            select(Plot)
            .join(Farm, Farm.id == Plot.farm_id)
            .where(
                Farm.id == farm_id,
                Farm.organization_ref == organization_ref,
                Plot.id == plot_id,
                Plot.farm_id == farm_id,
                Farm.status != "archived",
                Plot.status != "archived",
            )
        ).scalar_one_or_none()
        if row is None:
            raise DBIMapTimelineUnavailable("Lote DBI no disponible.")
        if row.boundary is None:
            return None

        west, south, east, north = to_shape(row.boundary).bounds
        return (
            float(west),
            float(south),
            float(east),
            float(north),
        )

    def read_plot_timeline(
        self,
        *,
        tenant_ref: str,
        organization_ref: str,
        farm_id: UUID,
        plot_id: UUID,
    ) -> PlotMapTimelineResponse:
        bounds = self._plot_bounds(
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )

        rows = self._session.execute(
            select(Campaign, DBICampaignArtifact, DBIRasterProduct)
            .join(
                DBICampaignArtifact,
                DBICampaignArtifact.campaign_id == Campaign.id,
            )
            .join(
                DBIRasterProduct,
                (
                    DBIRasterProduct.source_kind
                    == DBICampaignArtifact.source_kind
                )
                & (
                    DBIRasterProduct.source_ref
                    == DBICampaignArtifact.source_ref
                )
                & (
                    DBIRasterProduct.source_sha256
                    == DBICampaignArtifact.sha256
                ),
            )
            .where(
                Campaign.tenant_ref == tenant_ref,
                Campaign.organization_ref == organization_ref,
                Campaign.farm_id == farm_id,
                Campaign.plot_id == plot_id,
                Campaign.analysis_type.is_not(None),
                Campaign.captured_at.is_not(None),
                Campaign.status.in_(_VISIBLE_RGB_CAMPAIGN_STATES),
                DBICampaignArtifact.artifact_type == "orthophoto_source",
                DBICampaignArtifact.technical_status == "current",
                DBIRasterProduct.tenant_ref == tenant_ref,
                DBIRasterProduct.farm_id == farm_id,
                DBIRasterProduct.plot_id == plot_id,
                DBIRasterProduct.product_kind == "rgb_visual",
                DBIRasterProduct.status == "ready",
            )
            .order_by(
                Campaign.captured_at.desc(),
                DBIRasterProduct.created_at.desc(),
            )
        ).all()

        timeline: list[RasterTileTimelineEntry] = []
        seen_campaigns: set[UUID] = set()
        viewport_raster: DBIRasterProduct | None = None

        for campaign, artifact, raster in rows:
            if campaign.id in seen_campaigns:
                continue
            seen_campaigns.add(campaign.id)
            if viewport_raster is None:
                viewport_raster = raster

            assert campaign.captured_at is not None
            timeline.append(
                RasterTileTimelineEntry(
                    entry_id=f"rgb:{campaign.id}:{raster.id}",
                    campaign_id=str(campaign.id),
                    plot_id=str(plot_id),
                    captured_at=campaign.captured_at,
                    title=campaign.name,
                    source_artifact_id=str(artifact.id),
                    raster_product_id=str(raster.id),
                    tile_url_template=_tile_template(
                        organization_ref=organization_ref,
                        farm_id=farm_id,
                        plot_id=plot_id,
                        product_id=raster.id,
                    ),
                    professional_review_status=_review_status(campaign.status),
                )
            )

        if bounds is None and viewport_raster is not None:
            bounds = raster_bounds_wgs84(
                self._session,
                crs=viewport_raster.crs,
                bounds_json=viewport_raster.bounds_json,
            )

        dates = sorted({entry.captured_at for entry in timeline})
        return PlotMapTimelineResponse(
            organization_ref=organization_ref,
            farm_id=str(farm_id),
            plot_id=str(plot_id),
            status="ready" if timeline else "awaiting_data",
            available_layers=list(MAP_LAYER_CATALOG),
            timeline=timeline,
            comparison=MapComparisonCapability(
                available_dates=dates,
                enabled=len(dates) >= 2,
            ),
            viewport_bounds=bounds,
        )
