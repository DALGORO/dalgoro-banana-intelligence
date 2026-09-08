"""API autorizada del dominio técnico Campaign/Levantamiento DBI."""

from __future__ import annotations

from typing import Annotated
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
from app.dbi.campaigns.api_schemas import (
    DBICampaignCreateRequest,
    DBICampaignResponse,
    DBICampaignTransitionRequest,
)
from app.dbi.campaigns.contracts import DBICampaignConflict, DBICampaignUnavailable
from app.dbi.campaigns.reader import DBICampaignReader
from app.dbi.campaigns.service import DBICampaignService
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session

router = APIRouter(prefix="/dbi", tags=["dbi-campaigns"])

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]

DBI_CAMPAIGN_NOT_FOUND_DETAIL = "Campaña DBI no disponible."
DBI_CAMPAIGN_CONFLICT_DETAIL = "La campaña DBI entra en conflicto con el estado actual."


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=DBI_CAMPAIGN_NOT_FOUND_DETAIL,
    )


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=DBI_CAMPAIGN_CONFLICT_DETAIL,
    )


def _require_plot(
    context: DBIAccessContext,
    *,
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    permission: DBIPermission,
) -> None:
    try:
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=permission,
        )
    except DBIAccessDenied as error:
        raise _not_found() from error


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns",
    response_model=DBICampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_campaign(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    payload: DBICampaignCreateRequest,
    session: SessionDependency,
    context: AccessDependency,
) -> DBICampaignResponse:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.WRITE,
    )
    try:
        snapshot, created = DBICampaignService(session).create_campaign(
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            request=payload.to_contract(),
        )
        session.commit()
    except DBICampaignUnavailable as error:
        session.rollback()
        raise _not_found() from error
    except (DBICampaignConflict, IntegrityError) as error:
        session.rollback()
        raise _conflict() from error
    return DBICampaignResponse.from_snapshot(snapshot, created=created)


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}",
    response_model=DBICampaignResponse,
)
def get_campaign(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    campaign_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> DBICampaignResponse:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.READ,
    )
    try:
        snapshot = DBICampaignReader(session).read_campaign(
            campaign_id=campaign_id,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
    except DBICampaignUnavailable as error:
        raise _not_found() from error
    return DBICampaignResponse.from_snapshot(snapshot)


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/transitions",
    response_model=DBICampaignResponse,
)
def transition_campaign(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    campaign_id: UUID,
    payload: DBICampaignTransitionRequest,
    session: SessionDependency,
    context: AccessDependency,
) -> DBICampaignResponse:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.WRITE,
    )
    try:
        snapshot = DBICampaignService(session).transition_campaign(
            campaign_id=campaign_id,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            target_status=payload.status,
        )
        session.commit()
    except DBICampaignUnavailable as error:
        session.rollback()
        raise _not_found() from error
    except (DBICampaignConflict, IntegrityError) as error:
        session.rollback()
        raise _conflict() from error
    return DBICampaignResponse.from_snapshot(snapshot)
