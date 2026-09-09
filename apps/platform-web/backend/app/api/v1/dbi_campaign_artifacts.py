"""API autorizada del catálogo técnico versionado por Campaign DBI."""

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
from app.dbi.campaigns.artifacts import (
    DBICampaignArtifactMutationResponse,
    DBICampaignArtifactReader,
    DBICampaignArtifactRegistration,
    DBICampaignArtifactService,
    DBICampaignArtifactSnapshot,
)
from app.dbi.campaigns.contracts import DBICampaignConflict, DBICampaignUnavailable
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session

router = APIRouter(prefix="/dbi", tags=["dbi-campaign-artifacts"])

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Artefacto o Campaign DBI no disponible.",
    )


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="El catálogo técnico entra en conflicto con el estado actual.",
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
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/artifacts",
    response_model=DBICampaignArtifactMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_campaign_artifact(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    campaign_id: UUID,
    payload: DBICampaignArtifactRegistration,
    session: SessionDependency,
    context: AccessDependency,
) -> DBICampaignArtifactMutationResponse:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.WRITE,
    )
    try:
        snapshot, created = DBICampaignArtifactService(session).register_artifact(
            campaign_id=campaign_id,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            request=payload,
        )
        session.commit()
    except DBICampaignUnavailable as error:
        session.rollback()
        raise _not_found() from error
    except (DBICampaignConflict, IntegrityError) as error:
        session.rollback()
        raise _conflict() from error
    return DBICampaignArtifactMutationResponse(
        **snapshot.model_dump(),
        created=created,
    )


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/artifacts",
    response_model=list[DBICampaignArtifactSnapshot],
)
def list_campaign_artifacts(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    campaign_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> list[DBICampaignArtifactSnapshot]:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.READ,
    )
    try:
        return DBICampaignArtifactReader(session).list_artifacts(
            campaign_id=campaign_id,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
    except DBICampaignUnavailable as error:
        raise _not_found() from error


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/campaigns/{campaign_id}/artifacts/{campaign_artifact_id}",
    response_model=DBICampaignArtifactSnapshot,
)
def get_campaign_artifact(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    campaign_id: UUID,
    campaign_artifact_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> DBICampaignArtifactSnapshot:
    _require_plot(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
        permission=DBIPermission.READ,
    )
    try:
        return DBICampaignArtifactReader(session).read_artifact(
            campaign_artifact_id=campaign_artifact_id,
            campaign_id=campaign_id,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
    except DBICampaignUnavailable as error:
        raise _not_found() from error
