"""Escrituras agrícolas DBI autorizadas y transaccionales."""

from __future__ import annotations

from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.models import Campaign, Farm, Plot
from app.dbi.read_schemas import (
    CampaignRead,
    FarmRead,
    PlotSpatialRead,
)
from app.dbi.repositories import CampaignRepository, FarmRepository, PlotRepository
from app.dbi.spatial import boundary_to_database
from app.dbi.write_schemas import (
    CampaignCreate,
    CampaignUpdate,
    FarmCreate,
    FarmUpdate,
    PlotCreate,
    PlotUpdate,
)

router = APIRouter(prefix="/dbi", tags=["dbi-write"])

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]

EntityT = TypeVar("EntityT")


FARM_UPDATE_FIELDS = frozenset({"name", "status"})
PLOT_UPDATE_FIELDS = frozenset({"name", "area_hectares", "boundary", "status"})
CAMPAIGN_UPDATE_FIELDS = frozenset({"name", "starts_at", "ends_at", "status"})


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Recurso DBI no encontrado.",
    )


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="La escritura DBI entra en conflicto con datos existentes.",
    )


def _require_organization_write(
    context: DBIAccessContext,
    organization_ref: str,
) -> None:
    try:
        DBIAuthorizationPolicy.require_organization(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            permission=DBIPermission.WRITE,
        )
    except DBIAccessDenied as error:
        raise _not_found() from error


def _require_farm_write(
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
            permission=DBIPermission.WRITE,
        )
    except DBIAccessDenied as error:
        raise _not_found() from error


def _require_plot_write(
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
            permission=DBIPermission.WRITE,
        )
    except DBIAccessDenied as error:
        raise _not_found() from error


def _commit_and_refresh(session: Session, entity: EntityT) -> EntityT:
    try:
        session.commit()
        session.refresh(entity)
    except IntegrityError as error:
        session.rollback()
        raise _conflict() from error
    return entity


def _apply_updates(entity: object, changes: dict[str, object], allowed: frozenset[str]) -> None:
    for field_name in allowed:
        if field_name in changes:
            setattr(entity, field_name, changes[field_name])


@router.post(
    "/organizations/{organization_ref}/farms",
    response_model=FarmRead,
    status_code=status.HTTP_201_CREATED,
)
def create_farm(
    organization_ref: str,
    payload: FarmCreate,
    session: SessionDependency,
    context: AccessDependency,
) -> FarmRead:
    _require_organization_write(context, organization_ref)
    farm = Farm(organization_ref=organization_ref, **payload.model_dump())
    FarmRepository(session).add(farm)
    return FarmRead.model_validate(_commit_and_refresh(session, farm))


@router.patch(
    "/organizations/{organization_ref}/farms/{farm_id}",
    response_model=FarmRead,
)
def update_farm(
    organization_ref: str,
    farm_id: UUID,
    payload: FarmUpdate,
    session: SessionDependency,
    context: AccessDependency,
) -> FarmRead:
    _require_farm_write(context, organization_ref, farm_id)
    farm = FarmRepository(session).get_by_id(
        organization_ref=organization_ref,
        farm_id=farm_id,
    )
    if farm is None:
        raise _not_found()
    _apply_updates(farm, payload.model_dump(exclude_unset=True), FARM_UPDATE_FIELDS)
    return FarmRead.model_validate(_commit_and_refresh(session, farm))


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots",
    response_model=PlotSpatialRead,
    status_code=status.HTTP_201_CREATED,
)
def create_plot(
    organization_ref: str,
    farm_id: UUID,
    payload: PlotCreate,
    session: SessionDependency,
    context: AccessDependency,
) -> PlotSpatialRead:
    _require_farm_write(context, organization_ref, farm_id)
    farm = FarmRepository(session).get_by_id(
        organization_ref=organization_ref,
        farm_id=farm_id,
    )
    if farm is None:
        raise _not_found()

    values = payload.model_dump(exclude={"boundary"})
    plot = Plot(
        farm_id=farm_id,
        boundary=boundary_to_database(payload.boundary),
        **values,
    )
    PlotRepository(session).add(plot)
    return PlotSpatialRead.model_validate(_commit_and_refresh(session, plot))


@router.patch(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}",
    response_model=PlotSpatialRead,
)
def update_plot(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    payload: PlotUpdate,
    session: SessionDependency,
    context: AccessDependency,
) -> PlotSpatialRead:
    _require_plot_write(context, organization_ref, farm_id, plot_id)
    plot = PlotRepository(session).get_by_id(
        organization_ref=organization_ref,
        plot_id=plot_id,
    )
    if plot is None or plot.farm_id != farm_id:
        raise _not_found()

    changes = payload.model_dump(exclude_unset=True, exclude={"boundary"})
    if "boundary" in payload.model_fields_set:
        changes["boundary"] = boundary_to_database(payload.boundary)
    _apply_updates(plot, changes, PLOT_UPDATE_FIELDS)
    return PlotSpatialRead.model_validate(_commit_and_refresh(session, plot))


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/campaigns",
    response_model=CampaignRead,
    status_code=status.HTTP_201_CREATED,
)
def create_campaign(
    organization_ref: str,
    farm_id: UUID,
    payload: CampaignCreate,
    session: SessionDependency,
    context: AccessDependency,
) -> CampaignRead:
    _require_farm_write(context, organization_ref, farm_id)
    farm = FarmRepository(session).get_by_id(
        organization_ref=organization_ref,
        farm_id=farm_id,
    )
    if farm is None:
        raise _not_found()
    campaign = Campaign(farm_id=farm_id, **payload.model_dump())
    CampaignRepository(session).add(campaign)
    return CampaignRead.model_validate(_commit_and_refresh(session, campaign))


@router.patch(
    "/organizations/{organization_ref}/farms/{farm_id}/campaigns/{campaign_id}",
    response_model=CampaignRead,
)
def update_campaign(
    organization_ref: str,
    farm_id: UUID,
    campaign_id: UUID,
    payload: CampaignUpdate,
    session: SessionDependency,
    context: AccessDependency,
) -> CampaignRead:
    _require_farm_write(context, organization_ref, farm_id)
    campaign = CampaignRepository(session).get_by_id(
        organization_ref=organization_ref,
        campaign_id=campaign_id,
    )
    if campaign is None or campaign.farm_id != farm_id:
        raise _not_found()
    changes = payload.model_dump(exclude_unset=True)
    next_starts_at = changes.get("starts_at", campaign.starts_at)
    next_ends_at = changes.get("ends_at", campaign.ends_at)
    if next_ends_at is not None and next_ends_at < next_starts_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ends_at no puede ser anterior a starts_at.",
        )
    _apply_updates(campaign, changes, CAMPAIGN_UPDATE_FIELDS)
    return CampaignRead.model_validate(_commit_and_refresh(session, campaign))
