"""Endpoints de la interfaz cronológica de mapas DBI."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.map_timeline import DBIMapTimelineReader, DBIMapTimelineUnavailable
from app.models.user import User
from app.schemas.dbi_map import (
    FarmMapTimelineResponse,
    PlotMapTimelineResponse,
    build_empty_farm_map_timeline,
)

router = APIRouter(prefix="/dbi", tags=["dbi-map"])

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]

DBI_MAP_NOT_FOUND_DETAIL = "Mapa DBI no disponible."


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=DBI_MAP_NOT_FOUND_DETAIL,
    )


def _require_plot_read(
    context: DBIAccessContext,
    *,
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


@router.get(
    "/farms/{farm_id}/map/timeline",
    response_model=FarmMapTimelineResponse,
)
def get_farm_map_timeline(
    farm_id: Annotated[
        str,
        Path(
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ],
    _user: User = Depends(current_user),
) -> FarmMapTimelineResponse:
    """Conserva el contrato MAP-001 vacío para compatibilidad heredada."""

    return build_empty_farm_map_timeline(farm_id)


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/timeline",
    response_model=PlotMapTimelineResponse,
)
def get_plot_map_timeline(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
) -> PlotMapTimelineResponse:
    """Devuelve únicamente capas Raster reales del lote autorizado."""

    _require_plot_read(
        context,
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_id=plot_id,
    )
    try:
        return DBIMapTimelineReader(session).read_plot_timeline(
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
    except DBIMapTimelineUnavailable as error:
        raise _not_found() from error
