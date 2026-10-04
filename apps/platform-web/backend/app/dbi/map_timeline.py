"""Lectura autorizable de cronología Raster real para DBI-MAP-002."""

from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

from geoalchemy2.shape import to_shape
from sqlalchemy import select
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


_VISIBLE_TECHNICAL_STATES = frozenset(
    {
        "ANALYZED",
        "TECHNICAL_REVIEW",
        "SAMPLING_READY",
        "FIELD_WORK",
        "FIELD_COMPLETED",
        "APPROVED",
        "PUBLISHED",
    }
)


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
                Campaign.status.in_(_VISIBLE_TECHNICAL_STATES),
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

        for campaign, artifact, raster in rows:
            if campaign.id in seen_campaigns:
                continue
            seen_campaigns.add(campaign.id)

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
