"""Operación local para preparar el COG RGB consumido por MAP-002."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import current_user, db as get_db
from app.api.v1.dbi_pilot import (
    _context_for,
    _local_store,
    _organization_ref,
    _require_company,
    _require_local_pilot,
    _tenant_ref,
)
from app.dbi.authorization import (
    DBIAccessDenied,
    DBIAuthorizationPolicy,
    DBIPermission,
)
from app.dbi.dependencies import get_dbi_session
from app.dbi.map_timeline import DBIMapTimelineReader, DBIMapTimelineUnavailable
from app.dbi.models.agriculture import Farm, Plot
from app.dbi.raster.pilot_builder import (
    DBIPilotRasterBuilder,
    DBIPilotRasterConflict,
    DBIPilotRasterUnavailable,
)
from app.models.user import User


router = APIRouter(prefix="/dbi/pilot", tags=["dbi-pilot-raster"])

LegacySession = Annotated[Session, Depends(get_db)]
DBISession = Annotated[Session, Depends(get_dbi_session)]
CurrentUser = Annotated[User, Depends(current_user)]


def _raster_python() -> Path | None:
    raw = (
        os.environ.get("DBI_RASTER_RENDERER_PYTHON", "").strip()
        or os.environ.get("DBI_DENSITY_PYTHON", "").strip()
    )
    if not raw:
        return None
    path = Path(raw).expanduser().resolve(strict=False)
    return path if path.is_file() else None


def _flight_test_script() -> Path:
    return (
        Path(__file__).resolve().parents[6]
        / "services"
        / "banana-density"
        / "flight_test_cog.py"
    )


class PilotRasterResponse(BaseModel):
    product_id: UUID
    source_asset_id: UUID
    created: bool
    status: str
    profile_version: str
    size_bytes: int
    sha256: str
    crs: str
    width: int
    height: int
    band_count: int
    map_ready: bool
    map_path: str


def _map_path(
    *,
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    tenant_ref: str,
) -> str:
    return (
        f"/dbi/organizations/{quote(organization_ref, safe='')}/farms/{farm_id}/plots/"
        f"{plot_id}/mapa?tenant={quote(tenant_ref, safe='')}"
    )


@router.post(
    "/companies/{company_id}/farms/{farm_id}/plots/{plot_id}/"
    "orthophotos/{asset_id}/rgb-cog",
    response_model=PilotRasterResponse,
    status_code=status.HTTP_201_CREATED,
)
def prepare_pilot_rgb_cog(
    company_id: int,
    farm_id: UUID,
    plot_id: UUID,
    asset_id: UUID,
    request: Request,
    legacy_session: LegacySession,
    dbi_session: DBISession,
    user: CurrentUser,
) -> PilotRasterResponse:
    """Genera/recupera el COG RGB privado sin cargar Rasterio en FastAPI."""

    _require_local_pilot()
    _require_company(legacy_session, user, company_id)

    organization_ref = _organization_ref(company_id)
    tenant_ref = _tenant_ref()

    farm = dbi_session.get(Farm, farm_id)
    if farm is None or farm.organization_ref != organization_ref:
        raise HTTPException(status_code=404, detail="Finca DBI no encontrada.")
    plot = dbi_session.get(Plot, plot_id)
    if plot is None or plot.farm_id != farm_id:
        raise HTTPException(status_code=404, detail="Lote DBI no encontrado.")

    try:
        context = _context_for(
            dbi_session,
            user=user,
            organization_ref=organization_ref,
        )
        DBIAuthorizationPolicy.require_plot(
            context,
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            permission=DBIPermission.WRITE,
        )
    except DBIAccessDenied as error:
        dbi_session.rollback()
        raise HTTPException(status_code=404, detail="Recurso no disponible.") from error

    raster_python = _raster_python()
    if raster_python is None:
        dbi_session.rollback()
        raise HTTPException(
            status_code=503,
            detail="El Python geoespacial de Density/Raster no está disponible.",
        )

    store = _local_store(request)
    try:
        result = DBIPilotRasterBuilder(
            dbi_session,
            store,
            raster_python=raster_python,
            flight_test_script=_flight_test_script(),
        ).prepare_rgb(
            tenant_ref=tenant_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            asset_id=asset_id,
        )
        dbi_session.commit()
    except DBIPilotRasterUnavailable as error:
        dbi_session.rollback()
        raise HTTPException(status_code=503, detail=str(error)) from error
    except DBIPilotRasterConflict as error:
        dbi_session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except IntegrityError as error:
        dbi_session.rollback()
        raise HTTPException(
            status_code=409,
            detail="El producto Raster entra en conflicto con el estado DBI.",
        ) from error

    map_ready = False
    try:
        timeline = DBIMapTimelineReader(dbi_session).read_plot_timeline(
            tenant_ref=tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
        )
        map_ready = any(
            entry.raster_product_id == str(result.product_id)
            for entry in timeline.timeline
        )
    except DBIMapTimelineUnavailable:
        map_ready = False

    return PilotRasterResponse(
        product_id=result.product_id,
        source_asset_id=result.source_asset_id,
        created=result.created,
        status=result.status,
        profile_version=result.profile_version,
        size_bytes=result.size_bytes,
        sha256=result.sha256,
        crs=result.crs,
        width=result.width,
        height=result.height,
        band_count=result.band_count,
        map_ready=map_ready,
        map_path=_map_path(
            organization_ref=organization_ref,
            farm_id=farm_id,
            plot_id=plot_id,
            tenant_ref=tenant_ref,
        ),
    )
