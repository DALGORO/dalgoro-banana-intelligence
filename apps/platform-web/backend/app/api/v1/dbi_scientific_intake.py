"""H14: verificación privada de Campaign para borrador científico de dos carpetas.

NO recibe archivos ni produce grants, DB writes, aprobaciones o visibilidad READ.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext, DBIAccessDenied, DBIAuthorizationPolicy, DBIPermission,
)
from app.dbi.campaigns.contracts import DBICampaignUnavailable
from app.dbi.campaigns.reader import DBICampaignReader
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.scientific_intake_scope import (
    ScientificDraftScopeRequest, ScientificScopePreflightResponse,
    ScientificScopeUnavailable, check_scientific_campaign_scope,
)

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-intake"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


def _hidden() -> HTTPException:
    return HTTPException(status_code=404, detail="Preparación científica o Campaign no disponible.")


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/scope-preflight",
    response_model=ScientificScopePreflightResponse,
)
def preflight_scientific_intake_scope(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    campaign_id: UUID,
    payload: ScientificDraftScopeRequest,
    session: SessionDep,
    context: AccessDep,
) -> ScientificScopePreflightResponse:
    """MANAGE en lote + Campaign exacta MULTI + borrador 13 piezas, sin mutación."""
    try:
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=DBIPermission.MANAGE,
        )
        campaign = DBICampaignReader(session).read_campaign(
            campaign_id=campaign_id,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        return check_scientific_campaign_scope(
            request=payload,
            campaign=campaign,
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
    except (DBIAccessDenied, DBICampaignUnavailable, ScientificScopeUnavailable) as error:
        raise _hidden() from error
