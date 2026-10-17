"""Carga y consulta de GeoJSON publicado para un lote/Campaign autorizado.

No procesa Shapefiles, GeoPackage ni GDAL en FastAPI. La capa de visualización
está limitada a 2 MB y sólo puede publicarse con permiso MANAGE del lote.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext, DBIAccessDenied, DBIAuthorizationPolicy, DBIPermission,
)
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.models.agriculture import Campaign
from app.dbi.models.portal_vectors import DBIPortalVectorLayer
from app.dbi.portal_vector_validation import (
    DBIPortalVectorInvalid, MAX_VECTOR_BYTES, validate_portal_geojson,
)

router = APIRouter(prefix="/dbi", tags=["dbi-portal-vectors"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]
LayerKind = Literal["plants", "density_hexagons", "planting_candidates", "boundaries", "observations", "other"]


class VectorCampaignInfo(BaseModel):
    """Campaña técnica visible en este lote, incluso sin ortofoto RGB lista."""

    model_config = ConfigDict(extra="forbid")
    id: UUID
    name: str
    captured_at: datetime
    analysis_type: Literal["density", "multispectral"]
    status: str


class VectorLayerInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    campaign_id: UUID
    name: str
    layer_kind: LayerKind
    feature_count: int
    created_at: datetime


class VectorLayerDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layer: VectorLayerInfo
    geojson: dict


def _hidden() -> HTTPException:
    return HTTPException(status_code=404, detail="Capa cartográfica no disponible.")


def _require_scope(
    context: DBIAccessContext,
    organization_ref: str, farm_id: UUID, plot_id: UUID, *,
    publish: bool = False,
) -> None:
    try:
        DBIAuthorizationPolicy.require_plot(
            context, tenant_ref=context.tenant_ref,
            organization_ref=organization_ref, farm_id=farm_id, plot_id=plot_id,
            permission=DBIPermission.MANAGE if publish else DBIPermission.READ,
        )
    except DBIAccessDenied as error:
        raise _hidden() from error


def _campaign(
    session: Session, context: DBIAccessContext,
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
) -> Campaign:
    row = session.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.tenant_ref == context.tenant_ref,
            Campaign.organization_ref == organization_ref,
            Campaign.farm_id == farm_id,
            Campaign.plot_id == plot_id,
            Campaign.analysis_type.is_not(None),
            Campaign.captured_at.is_not(None),
        )
    ).scalar_one_or_none()
    if row is None:
        raise _hidden()
    return row


def _scoped_layer(
    session: Session, context: DBIAccessContext,
    organization_ref: str, farm_id: UUID, plot_id: UUID, layer_id: UUID,
) -> DBIPortalVectorLayer:
    layer = session.execute(
        select(DBIPortalVectorLayer).where(
            DBIPortalVectorLayer.id == layer_id,
            DBIPortalVectorLayer.tenant_ref == context.tenant_ref,
            DBIPortalVectorLayer.organization_ref == organization_ref,
            DBIPortalVectorLayer.farm_id == farm_id,
            DBIPortalVectorLayer.plot_id == plot_id,
        )
    ).scalar_one_or_none()
    if layer is None:
        raise _hidden()
    return layer


def _info(layer: DBIPortalVectorLayer) -> VectorLayerInfo:
    return VectorLayerInfo(
        id=layer.id, campaign_id=layer.campaign_id,
        name=layer.name, layer_kind=layer.layer_kind,
        feature_count=layer.feature_count, created_at=layer.created_at,
    )


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/vector-campaigns",
    response_model=list[VectorCampaignInfo],
)
def list_vector_campaigns(
    organization_ref: str, farm_id: UUID, plot_id: UUID,
    session: SessionDep, context: AccessDep,
) -> list[VectorCampaignInfo]:
    _require_scope(context, organization_ref, farm_id, plot_id)
    rows = session.execute(
        select(Campaign)
        .where(
            Campaign.tenant_ref == context.tenant_ref,
            Campaign.organization_ref == organization_ref,
            Campaign.farm_id == farm_id,
            Campaign.plot_id == plot_id,
            Campaign.analysis_type.in_(("density", "multispectral")),
            Campaign.captured_at.is_not(None),
            Campaign.status == "PUBLISHED",
            Campaign.approved_at.is_not(None),
            Campaign.published_at.is_not(None),
        )
        .order_by(Campaign.captured_at.desc(), Campaign.id)
        .limit(100)
    ).scalars().all()
    return [
        VectorCampaignInfo(
            id=campaign.id,
            name=campaign.name,
            captured_at=campaign.captured_at,
            analysis_type=campaign.analysis_type,
            status=campaign.status,
        )
        for campaign in rows
    ]


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/management-campaigns",
    response_model=list[VectorCampaignInfo],
)
def list_management_campaigns(
    organization_ref: str, farm_id: UUID, plot_id: UUID,
    session: SessionDep, context: AccessDep,
) -> list[VectorCampaignInfo]:
    """Catálogo técnico reservado a gestores para preparar capas no publicadas.

    Tener MANAGE no concede por sí solo el cargo institucional DALGORO
    requerido por el endpoint de transición final a PUBLISHED.
    """
    _require_scope(context, organization_ref, farm_id, plot_id, publish=True)
    rows = session.execute(
        select(Campaign).where(
            Campaign.tenant_ref == context.tenant_ref,
            Campaign.organization_ref == organization_ref,
            Campaign.farm_id == farm_id,
            Campaign.plot_id == plot_id,
            Campaign.analysis_type.in_(("density", "multispectral")),
            Campaign.captured_at.is_not(None),
        ).order_by(Campaign.captured_at.desc(), Campaign.id).limit(100)
    ).scalars().all()
    return [
        VectorCampaignInfo(
            id=row.id, name=row.name, captured_at=row.captured_at,
            analysis_type=row.analysis_type, status=row.status,
        )
        for row in rows
    ]


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/vector-layers",
    response_model=list[VectorLayerInfo],
)
def list_vector_layers(
    organization_ref: str, farm_id: UUID, plot_id: UUID,
    session: SessionDep, context: AccessDep,
) -> list[VectorLayerInfo]:
    _require_scope(context, organization_ref, farm_id, plot_id)
    rows = session.execute(
        select(DBIPortalVectorLayer)
        .join(Campaign, Campaign.id == DBIPortalVectorLayer.campaign_id)
        .where(
            DBIPortalVectorLayer.tenant_ref == context.tenant_ref,
            DBIPortalVectorLayer.organization_ref == organization_ref,
            DBIPortalVectorLayer.farm_id == farm_id,
            DBIPortalVectorLayer.plot_id == plot_id,
            Campaign.tenant_ref == context.tenant_ref,
            Campaign.organization_ref == organization_ref,
            Campaign.farm_id == farm_id,
            Campaign.plot_id == plot_id,
            Campaign.status == "PUBLISHED",
            Campaign.approved_at.is_not(None),
            Campaign.published_at.is_not(None),
        )
        .order_by(DBIPortalVectorLayer.created_at.desc())
        .limit(100)
    ).scalars().all()
    return [_info(row) for row in rows]


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/vector-layers/{layer_id}",
    response_model=VectorLayerDetail,
)
def get_vector_layer(
    organization_ref: str, farm_id: UUID, plot_id: UUID, layer_id: UUID,
    session: SessionDep, context: AccessDep,
) -> VectorLayerDetail:
    _require_scope(context, organization_ref, farm_id, plot_id)
    layer = _scoped_layer(
        session, context, organization_ref, farm_id, plot_id, layer_id
    )
    # Nunca entregar GeoJSON por ID directo sin comprobar publicación final.
    _published = session.execute(
        select(Campaign.id).where(
            Campaign.id == layer.campaign_id,
            Campaign.tenant_ref == context.tenant_ref,
            Campaign.organization_ref == organization_ref,
            Campaign.farm_id == farm_id,
            Campaign.plot_id == plot_id,
            Campaign.status == "PUBLISHED",
            Campaign.approved_at.is_not(None),
            Campaign.published_at.is_not(None),
        )
    ).scalar_one_or_none()
    if _published is None:
        raise _hidden()
    return VectorLayerDetail(layer=_info(layer), geojson=json.loads(layer.geojson_text))


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/vector-layers",
    response_model=VectorLayerInfo,
    status_code=201,
)
async def publish_vector_layer(
    request: Request,
    organization_ref: str, farm_id: UUID, plot_id: UUID,
    session: SessionDep, context: AccessDep,
    campaign_id: UUID,
    layer_kind: LayerKind,
    name: Annotated[str, Query(min_length=1, max_length=100)],
) -> VectorLayerInfo:
    _require_scope(context, organization_ref, farm_id, plot_id, publish=True)
    campaign = session.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.tenant_ref == context.tenant_ref,
            Campaign.organization_ref == organization_ref,
            Campaign.farm_id == farm_id,
            Campaign.plot_id == plot_id,
            Campaign.analysis_type.is_not(None),
            Campaign.captured_at.is_not(None),
        ).with_for_update()
    ).scalar_one_or_none()
    if campaign is None:
        raise _hidden()
    if campaign.status == "PUBLISHED":
        raise HTTPException(status_code=409, detail="Campaña publicada: no se aceptan capas nuevas sin otra revisión.")

    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/geo+json":
        raise HTTPException(status_code=415, detail="Sube un archivo .geojson válido.")
    declared_length = request.headers.get("content-length")
    if declared_length:
        try:
            if int(declared_length) > MAX_VECTOR_BYTES:
                raise HTTPException(status_code=413, detail="GeoJSON máximo 2 MB.")
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Content-Length inválido.") from error
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_VECTOR_BYTES:
            raise HTTPException(status_code=413, detail="GeoJSON máximo 2 MB.")
        raw.extend(chunk)
    try:
        parsed = validate_portal_geojson(bytes(raw))
    except DBIPortalVectorInvalid as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    normalized_name = name.strip()
    if not normalized_name:
        raise HTTPException(status_code=422, detail="El nombre de capa es obligatorio.")

    existing = session.execute(
        select(DBIPortalVectorLayer).where(
            DBIPortalVectorLayer.tenant_ref == context.tenant_ref,
            DBIPortalVectorLayer.campaign_id == campaign_id,
            DBIPortalVectorLayer.layer_kind == layer_kind,
            DBIPortalVectorLayer.source_sha256 == parsed.source_sha256,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _info(existing)

    record = DBIPortalVectorLayer(
        tenant_ref=context.tenant_ref, organization_ref=organization_ref,
        farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
        name=normalized_name, layer_kind=layer_kind, crs="EPSG:4326",
        source_sha256=parsed.source_sha256,
        geojson_text=parsed.geojson_text,
        source_bytes=bytes(raw),
        feature_count=parsed.feature_count,
        created_by_ref=context.principal_ref,
    )
    session.add(record)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="La capa entra en conflicto con un archivo ya registrado.") from error
    session.refresh(record)
    return _info(record)
