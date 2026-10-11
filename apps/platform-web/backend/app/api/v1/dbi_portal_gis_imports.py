"""Recepción privada de fuentes GPKG/ZIP por Campaign, SIN convertir ni publicar.

Esta frontera solo utiliza streaming y controles de ZIP/SQLite; GDAL/Pyogrio
permanecen en el worker geoespacial independiente.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from tempfile import SpooledTemporaryFile
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.dbi_assets import get_dbi_asset_object_store
from app.api.v1.dbi_portal_vectors import _campaign, _require_scope, _info, LayerKind, VectorLayerInfo
from app.dbi.authorization import DBIAccessContext
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.models.portal_gis_imports import DBIPortalGISImport, DBIPortalGISPreview
from app.dbi.models.portal_vectors import DBIPortalVectorLayer
from app.dbi.portal_vector_validation import DBIPortalVectorInvalid, validate_portal_geojson
from app.dbi.portal_gis_staging import (
    MAX_GIS_UPLOAD_BYTES, PortalGISSourceInvalid,
    normalize_upload_filename, validate_staged_source,
)
from app.dbi.storage_contracts import (
    DBIStorageError, DBIStoragePurpose, DBIStorageWriteRequest,
)
from app.dbi.storage_policy import DBIStoragePolicy

router = APIRouter(prefix="/dbi", tags=["dbi-portal-gis-imports"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]
StoreDep = Annotated[object, Depends(get_dbi_asset_object_store)]


class PortalGISImportInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    campaign_id: UUID
    name: str
    original_filename: str
    source_format: str
    layer_kind: LayerKind
    size_bytes: int
    status: str
    available_layers: list[str] | None = None
    selected_layer: str | None = None
    published_layer_id: UUID | None = None
    created_at: datetime


def _response(row: DBIPortalGISImport) -> PortalGISImportInfo:
    return PortalGISImportInfo(
        id=row.id, campaign_id=row.campaign_id, name=row.name,
        original_filename=row.original_filename,
        source_format=row.source_format, layer_kind=row.layer_kind,
        size_bytes=row.size_bytes, status=row.status,
        available_layers=row.available_layers, selected_layer=row.selected_layer,
        published_layer_id=row.published_layer_id, created_at=row.created_at,
    )


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/gis-imports",
    response_model=list[PortalGISImportInfo],
)
def list_gis_imports(
    organization_ref: str, farm_id: UUID, plot_id: UUID,
    session: SessionDep, context: AccessDep,
) -> list[PortalGISImportInfo]:
    # El acceso al original está reservado a quien administra el lote.
    _require_scope(context, organization_ref, farm_id, plot_id, publish=True)
    rows = session.execute(
        select(DBIPortalGISImport).where(
            DBIPortalGISImport.tenant_ref == context.tenant_ref,
            DBIPortalGISImport.organization_ref == organization_ref,
            DBIPortalGISImport.farm_id == farm_id,
            DBIPortalGISImport.plot_id == plot_id,
        ).order_by(DBIPortalGISImport.created_at.desc()).limit(50)
    ).scalars().all()
    return [_response(row) for row in rows]


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/gis-imports",
    response_model=PortalGISImportInfo,
    status_code=201,
)
async def receive_gis_import(
    request: Request,
    organization_ref: str, farm_id: UUID, plot_id: UUID,
    session: SessionDep, context: AccessDep, store: StoreDep,
    campaign_id: UUID,
    layer_kind: LayerKind,
    filename: Annotated[str, Query(min_length=1, max_length=100)],
    name: Annotated[str, Query(min_length=1, max_length=100)],
) -> PortalGISImportInfo:
    _require_scope(context, organization_ref, farm_id, plot_id, publish=True)
    _campaign(session, context, organization_ref, farm_id, plot_id, campaign_id)
    try:
        original_filename, source_format, mime = normalize_upload_filename(filename)
    except PortalGISSourceInvalid as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not hasattr(store, "put") or not hasattr(store, "retire"):
        raise HTTPException(status_code=503, detail="Almacenamiento GIS privado no disponible.")
    if name != name.strip() or not name.strip():
        raise HTTPException(status_code=422, detail="El nombre de capa es obligatorio.")
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/octet-stream":
        raise HTTPException(status_code=415, detail="Formato binario requerido.")
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            length = int(declared)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Content-Length inválido.") from error
        if length < 1 or length > MAX_GIS_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Archivo GIS máximo 30 MiB.")

    # SpooledTemporaryFile desborda a un temporal efímero, NO usa memoria
    # no acotada ni conserva el original en disco local tras responder.
    digest = sha256()
    total = 0
    with SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as staged:
        async for chunk in request.stream():
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_GIS_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Archivo GIS máximo 30 MiB.")
            digest.update(chunk)
            staged.write(chunk)
        if total < 1:
            raise HTTPException(status_code=422, detail="El archivo GIS está vacío.")
        try:
            validate_staged_source(staged, source_format)
        except PortalGISSourceInvalid as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        source_object_id = uuid4()
        metadata = DBIStoragePolicy.build_metadata(
            address=DBIStoragePolicy.build_address(
                tenant_ref=context.tenant_ref,
                purpose=DBIStoragePurpose.TECHNICAL_SOURCE,
                object_id=source_object_id,
            ),
            content_type=mime, size_bytes=total, sha256_hex=digest.hexdigest(),
        )
        staged.seek(0)
        try:
            written = await run_in_threadpool(
                store.put, DBIStorageWriteRequest(metadata=metadata), staged,
            )
            if written.record.metadata != metadata:
                raise DBIStorageError("La fuente almacenada no coincide con el manifiesto.")
        except DBIStorageError as error:
            raise HTTPException(status_code=503, detail="Almacenamiento GIS privado no disponible.") from error

    row = DBIPortalGISImport(
        tenant_ref=context.tenant_ref, organization_ref=organization_ref,
        farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
        source_object_id=source_object_id, source_format=source_format,
        original_filename=original_filename, name=name, layer_kind=layer_kind,
        size_bytes=total, sha256=digest.hexdigest(), status="received",
        created_by_ref=context.principal_ref,
    )
    session.add(row)
    try:
        session.commit()
        session.refresh(row)
    except Exception:
        session.rollback()
        # Compensa si falla el registro: evita exponer un original huérfano.
        try:
            store.retire(metadata.address, retired_at=datetime.now(timezone.utc))
        except DBIStorageError:
            pass  # Seguirá siendo un objeto privado no enumerable.
        raise HTTPException(status_code=503, detail="No se pudo registrar la recepción GIS.")
    return _response(row)


class PortalGISLayerChoice(BaseModel):
    """Elegir exactamente uno de los nombres descubiertos por el worker."""
    model_config = ConfigDict(extra="forbid")
    layer: str = Field(min_length=1, max_length=100, strict=True)


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/gis-imports/{import_id}/select-layer",
    response_model=PortalGISImportInfo,
)
def select_gis_import_layer(
    organization_ref: str, farm_id: UUID, plot_id: UUID, import_id: UUID,
    choice: PortalGISLayerChoice,
    session: SessionDep, context: AccessDep,
) -> PortalGISImportInfo:
    """MANAGE guarda una única elección; el worker queda inactivo en este hito."""
    _require_scope(context, organization_ref, farm_id, plot_id, publish=True)
    row = session.execute(
        select(DBIPortalGISImport).where(
            DBIPortalGISImport.id == import_id,
            DBIPortalGISImport.tenant_ref == context.tenant_ref,
            DBIPortalGISImport.organization_ref == organization_ref,
            DBIPortalGISImport.farm_id == farm_id,
            DBIPortalGISImport.plot_id == plot_id,
        ).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Importación GIS no disponible.")
    # La Campaign se vuelve a validar en el servidor; el navegador no decide su alcance.
    _campaign(session, context, organization_ref, farm_id, plot_id, row.campaign_id)
    if row.status != "needs_selection" or row.source_format != "gpkg":
        raise HTTPException(status_code=409, detail="La importación no admite elegir una capa.")
    if not isinstance(row.available_layers, list) or choice.layer not in row.available_layers:
        raise HTTPException(status_code=422, detail="La capa indicada no pertenece al GeoPackage validado.")
    if row.selected_layer is not None:
        if row.selected_layer != choice.layer:
            raise HTTPException(status_code=409, detail="Este original ya tiene una capa elegida.")
        return _response(row)  # Reintento exacto: sin escritura ni conversión.
    row.selected_layer = choice.layer
    try:
        session.commit()
    except SQLAlchemyError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail="No fue posible guardar la selección GIS.") from error
    return _response(row)


class PortalGISPreviewDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt: PortalGISImportInfo
    feature_count: int
    geojson: dict


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/gis-imports/{import_id}/preview",
    response_model=PortalGISPreviewDetail,
)
def get_gis_import_preview(
    organization_ref: str, farm_id: UUID, plot_id: UUID, import_id: UUID,
    session: SessionDep, context: AccessDep,
) -> PortalGISPreviewDetail:
    # La vista previa no equivale a una capa pública ni confiere permiso READ.
    _require_scope(context, organization_ref, farm_id, plot_id, publish=True)
    row = session.execute(
        select(DBIPortalGISImport).where(
            DBIPortalGISImport.id == import_id,
            DBIPortalGISImport.tenant_ref == context.tenant_ref,
            DBIPortalGISImport.organization_ref == organization_ref,
            DBIPortalGISImport.farm_id == farm_id,
            DBIPortalGISImport.plot_id == plot_id,
        )
    ).scalar_one_or_none()
    if row is None or row.status not in {"prepared", "published"}:
        raise HTTPException(status_code=404, detail="Vista previa GIS no disponible.")
    preview = session.get(DBIPortalGISPreview, row.id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Vista previa GIS no disponible.")
    import json
    return PortalGISPreviewDetail(
        receipt=_response(row),
        feature_count=preview.feature_count,
        geojson=json.loads(preview.geojson_text),
    )


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}/map/gis-imports/{import_id}/publish",
    response_model=VectorLayerInfo,
    status_code=201,
)
def publish_reviewed_gis_import(
    organization_ref: str, farm_id: UUID, plot_id: UUID, import_id: UUID,
    session: SessionDep, context: AccessDep,
) -> VectorLayerInfo:
    """Solo MANAGE aprueba un derivado ya preparado; jamás publica el ZIP/GPKG."""
    _require_scope(context, organization_ref, farm_id, plot_id, publish=True)
    row = session.execute(
        select(DBIPortalGISImport).where(
            DBIPortalGISImport.id == import_id,
            DBIPortalGISImport.tenant_ref == context.tenant_ref,
            DBIPortalGISImport.organization_ref == organization_ref,
            DBIPortalGISImport.farm_id == farm_id,
            DBIPortalGISImport.plot_id == plot_id,
        ).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Importación GIS no disponible.")
    if row.status not in {"prepared", "published"}:
        raise HTTPException(status_code=409, detail="El archivo requiere conversión y revisión previa.")

    # Recomprueba la Campaign actual bajo el scope MANAGE en el instante de publicación.
    _campaign(session, context, organization_ref, farm_id, plot_id, row.campaign_id)
    preview = session.get(DBIPortalGISPreview, row.id)
    if preview is None:
        raise HTTPException(status_code=409, detail="La vista previa validada no está disponible.")
    raw = preview.geojson_text.encode("utf-8")
    try:
        parsed = validate_portal_geojson(raw)
    except DBIPortalVectorInvalid as error:
        raise HTTPException(status_code=409, detail="La vista previa requiere nueva validación.") from error
    if (
        parsed.source_sha256 != preview.sha256
        or parsed.geojson_text != preview.geojson_text
        or parsed.feature_count != preview.feature_count
    ):
        raise HTTPException(status_code=409, detail="La vista previa no coincide con su huella.")

    def _find_layer(layer_id: UUID | None = None) -> DBIPortalVectorLayer | None:
        clause = [DBIPortalVectorLayer.tenant_ref == context.tenant_ref,
                  DBIPortalVectorLayer.organization_ref == organization_ref,
                  DBIPortalVectorLayer.farm_id == farm_id,
                  DBIPortalVectorLayer.plot_id == plot_id,
                  DBIPortalVectorLayer.campaign_id == row.campaign_id,
                  DBIPortalVectorLayer.layer_kind == row.layer_kind,
                  DBIPortalVectorLayer.source_sha256 == preview.sha256]
        if layer_id is not None:
            clause.append(DBIPortalVectorLayer.id == layer_id)
        return session.execute(select(DBIPortalVectorLayer).where(*clause)).scalar_one_or_none()

    if row.status == "published":
        existing = _find_layer(row.published_layer_id)
        if existing is None or row.published_layer_id is None:
            raise HTTPException(status_code=409, detail="La publicación anterior no coincide.")
        return _info(existing)

    existing = _find_layer()
    try:
        if existing is None:
            existing = DBIPortalVectorLayer(
                id=uuid4(),
                tenant_ref=context.tenant_ref, organization_ref=organization_ref,
                farm_id=farm_id, plot_id=plot_id, campaign_id=row.campaign_id,
                name=row.name, layer_kind=row.layer_kind, crs="EPSG:4326",
                source_sha256=preview.sha256,
                geojson_text=parsed.geojson_text, source_bytes=raw,
                feature_count=parsed.feature_count,
                created_by_ref=context.principal_ref,
            )
            session.add(existing)
            # Inserta la capa dentro de la transacción, ANTES de marcar como
            # publicada la importación: la FK y CHECK se mantienen válidas.
            session.flush()
        row.published_layer_id = existing.id
        row.status = "published"
        row.approved_at = datetime.now(timezone.utc)
        row.approved_by_ref = context.principal_ref
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="Conflicto durante la publicación GIS.") from error
    return _info(existing)
