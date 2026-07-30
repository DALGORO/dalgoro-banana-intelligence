"""Consultas espaciales DBI autorizadas y limitadas."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext,
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.read_schemas import PlotRead
from app.dbi.repositories import DBI_READ_LIST_LIMIT, PlotRepository

router = APIRouter(prefix="/dbi", tags=["dbi-spatial"])

SessionDependency = Annotated[Session, Depends(get_dbi_session)]
AccessDependency = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Recurso DBI no encontrado.",
    )


def _invalid_envelope() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="La envolvente espacial DBI es inválida.",
    )


def _require_farm_read(
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
    "/organizations/{organization_ref}/farms/{farm_id}/plots/spatial/intersections",
    response_model=list[PlotRead],
)
def list_intersecting_plots(
    organization_ref: str,
    farm_id: UUID,
    session: SessionDependency,
    context: AccessDependency,
    min_longitude: Annotated[
        float,
        Query(alias="min_lon", ge=-180, le=180),
    ],
    min_latitude: Annotated[
        float,
        Query(alias="min_lat", ge=-90, le=90),
    ],
    max_longitude: Annotated[
        float,
        Query(alias="max_lon", ge=-180, le=180),
    ],
    max_latitude: Annotated[
        float,
        Query(alias="max_lat", ge=-90, le=90),
    ],
    limit: Annotated[int, Query(ge=1, le=DBI_READ_LIST_LIMIT)] = DBI_READ_LIST_LIMIT,
) -> list[PlotRead]:
    """Lista lotes autorizados que intersectan una envolvente EPSG:4326."""

    if min_longitude >= max_longitude or min_latitude >= max_latitude:
        raise _invalid_envelope()

    _require_farm_read(context, organization_ref, farm_id)
    plots = PlotRepository(session).list_intersecting_boundary(
        organization_ref=organization_ref,
        farm_id=farm_id,
        plot_ids=_authorized_plot_ids(context, organization_ref, farm_id),
        min_longitude=min_longitude,
        min_latitude=min_latitude,
        max_longitude=max_longitude,
        max_latitude=max_latitude,
        limit=limit,
    )
    return [PlotRead.model_validate(plot) for plot in plots]
