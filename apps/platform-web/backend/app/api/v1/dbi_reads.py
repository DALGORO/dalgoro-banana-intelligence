"""Consultas DBI de solo lectura con autorización no enumerable."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.read_schemas import (
    AnalysisArtifactRead,
    AnalysisInputAssetRead,
    AnalysisJobRead,
    CampaignRead,
    FarmRead,
    PlotRead,
)
from app.dbi.repositories import (
    AnalysisArtifactRepository,
    AnalysisInputAssetRepository,
    AnalysisJobRepository,
    CampaignRepository,
    FarmRepository,
    PlotRepository,
)

router = APIRouter(prefix="/dbi", tags=["dbi-read"])

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Recurso DBI no encontrado.",
    )


def _require_organization(
    context: DBIAccessContext,
    organization_ref: str,
) -> None:
    try:
        DBIAuthorizationPolicy.require_organization(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            permission=DBIPermission.READ,
        )
    except DBIAccessDenied as error:
        raise _not_found() from error


def _require_farm(
    context: DBIAccessContext,
    organization_ref: str,
    farm_id: UUID,
) -> None:
    try:
        DBIAuthorizationPolicy.require_farm(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            permission=DBIPermission.READ,
        )
    except DBIAccessDenied as error:
        raise _not_found() from error


def _require_plot(
    context: DBIAccessContext,
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
) -> None:
    try:
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=DBIPermission.READ,
        )
    except DBIAccessDenied as error:
        raise _not_found() from error


def _authorized_plot_ids(
    context: DBIAccessContext,
    organization_ref: str,
    farm_id: UUID,
) -> frozenset[UUID]:
    return frozenset(
        scope.plot_id
        for scope in context.plot_scopes
        if scope.organization_ref == organization_ref and scope.farm_id == farm_id
    )


@router.get(
    "/organizations/{organization_ref}/farms",
    response_model=list[FarmRead],
)
def list_farms(
    organization_ref: str,
    session: SessionDependency,
    context: AccessDependency,
) -> list[FarmRead]:
    _require_organization(context, organization_ref)
    allowed_ids = {
        scope.farm_id
        for scope in context.farm_scopes
        if scope.organization_ref == organization_ref
    }
    farms = FarmRepository(session).list_by_organization(
        organization_ref=organization_ref
    )
    return [FarmRead.model_validate(farm) for farm in farms if farm.id in allowed_ids]


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}",
    response_model=FarmRead,
)
def get_farm(
    organization_ref: str,
    farm_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> FarmRead:
    _require_farm(context, organization_ref, farm_id)
    farm = FarmRepository(session).get_by_id(
        organization_ref=organization_ref,
        farm_id=farm_id,
    )
    if farm is None:
        raise _not_found()
    return FarmRead.model_validate(farm)


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots",
    response_model=list[PlotRead],
)
def list_plots(
    organization_ref: str,
    farm_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> list[PlotRead]:
    _require_farm(context, organization_ref, farm_id)
    allowed_ids = _authorized_plot_ids(context, organization_ref, farm_id)
    plots = PlotRepository(session).list_by_farm(
        organization_ref=organization_ref,
        farm_id=farm_id,
    )
    return [PlotRead.model_validate(plot) for plot in plots if plot.id in allowed_ids]


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}",
    response_model=PlotRead,
)
def get_plot(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> PlotRead:
    _require_plot(context, organization_ref, farm_id, plot_id)
    plot = PlotRepository(session).get_by_id(
        organization_ref=organization_ref,
        plot_id=plot_id,
    )
    if plot is None or plot.farm_id != farm_id:
        raise _not_found()
    return PlotRead.model_validate(plot)


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/campaigns",
    response_model=list[CampaignRead],
)
def list_campaigns(
    organization_ref: str,
    farm_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> list[CampaignRead]:
    _require_farm(context, organization_ref, farm_id)
    campaigns = CampaignRepository(session).list_by_farm(
        organization_ref=organization_ref,
        farm_id=farm_id,
    )
    return [CampaignRead.model_validate(campaign) for campaign in campaigns]


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/campaigns/{campaign_id}",
    response_model=CampaignRead,
)
def get_campaign(
    organization_ref: str,
    farm_id: UUID,
    campaign_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> CampaignRead:
    _require_farm(context, organization_ref, farm_id)
    campaign = CampaignRepository(session).get_by_id(
        organization_ref=organization_ref,
        campaign_id=campaign_id,
    )
    if campaign is None or campaign.farm_id != farm_id:
        raise _not_found()
    return CampaignRead.model_validate(campaign)


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/jobs",
    response_model=list[AnalysisJobRead],
)
def list_jobs(
    organization_ref: str,
    farm_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> list[AnalysisJobRead]:
    _require_farm(context, organization_ref, farm_id)
    allowed_plot_ids = _authorized_plot_ids(context, organization_ref, farm_id)
    jobs = AnalysisJobRepository(session).list_by_farm(
        tenant_ref=context.tenant_ref,
        farm_id=farm_id,
    )
    return [
        AnalysisJobRead.model_validate(job)
        for job in jobs
        if job.plot_id in allowed_plot_ids
    ]


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}",
    response_model=AnalysisJobRead,
)
def get_job(
    organization_ref: str,
    farm_id: UUID,
    job_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> AnalysisJobRead:
    job = AnalysisJobRepository(session).get_by_id(
        tenant_ref=context.tenant_ref,
        job_id=job_id,
    )
    if job is None or job.farm_id != farm_id:
        raise _not_found()
    _require_plot(context, organization_ref, farm_id, job.plot_id)
    return AnalysisJobRead.model_validate(job)


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/assets",
    response_model=list[AnalysisInputAssetRead],
)
def list_assets(
    organization_ref: str,
    farm_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> list[AnalysisInputAssetRead]:
    _require_farm(context, organization_ref, farm_id)
    allowed_plot_ids = _authorized_plot_ids(context, organization_ref, farm_id)
    assets = AnalysisInputAssetRepository(session).list_by_farm(
        tenant_ref=context.tenant_ref,
        farm_id=farm_id,
    )
    return [
        AnalysisInputAssetRead.model_validate(asset)
        for asset in assets
        if asset.plot_id is None or asset.plot_id in allowed_plot_ids
    ]


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/assets/{asset_id}",
    response_model=AnalysisInputAssetRead,
)
def get_asset(
    organization_ref: str,
    farm_id: UUID,
    asset_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> AnalysisInputAssetRead:
    asset = AnalysisInputAssetRepository(session).get_by_id(
        tenant_ref=context.tenant_ref,
        asset_id=asset_id,
    )
    if asset is None or asset.farm_id != farm_id:
        raise _not_found()
    if asset.plot_id is None:
        _require_farm(context, organization_ref, farm_id)
    else:
        _require_plot(context, organization_ref, farm_id, asset.plot_id)
    return AnalysisInputAssetRead.model_validate(asset)


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}/artifacts",
    response_model=list[AnalysisArtifactRead],
)
def list_artifacts(
    organization_ref: str,
    farm_id: UUID,
    job_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> list[AnalysisArtifactRead]:
    job = AnalysisJobRepository(session).get_by_id(
        tenant_ref=context.tenant_ref,
        job_id=job_id,
    )
    if job is None or job.farm_id != farm_id:
        raise _not_found()
    _require_plot(context, organization_ref, farm_id, job.plot_id)
    artifacts = AnalysisArtifactRepository(session).list_by_job(
        tenant_ref=context.tenant_ref,
        job_id=job_id,
    )
    return [AnalysisArtifactRead.model_validate(item) for item in artifacts]


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/jobs/{job_id}/artifacts/{artifact_id}",
    response_model=AnalysisArtifactRead,
)
def get_artifact(
    organization_ref: str,
    farm_id: UUID,
    job_id: UUID,
    artifact_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> AnalysisArtifactRead:
    job = AnalysisJobRepository(session).get_by_id(
        tenant_ref=context.tenant_ref,
        job_id=job_id,
    )
    artifact = AnalysisArtifactRepository(session).get_by_id(
        tenant_ref=context.tenant_ref,
        artifact_id=artifact_id,
    )
    if (
        job is None
        or artifact is None
        or job.farm_id != farm_id
        or artifact.job_id != job_id
    ):
        raise _not_found()
    _require_plot(context, organization_ref, farm_id, job.plot_id)
    return AnalysisArtifactRead.model_validate(artifact)
