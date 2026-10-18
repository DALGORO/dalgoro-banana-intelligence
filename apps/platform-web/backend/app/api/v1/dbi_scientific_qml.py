"""H14: transporte privado opt-in de UN original QML (sin publicación).

Restringido a entornos locales/pruebas. No es una ruta RGB/COG multipartes,
no crea expediente institucional ni otorga grants READ.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import os
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.dbi.authorization import (
    DBIAccessContext, DBIAccessDenied, DBIAuthorizationPolicy, DBIPermission,
)
from app.dbi.campaigns.contracts import (
    DBICampaignAnalysisType, DBICampaignUnavailable,
)
from app.dbi.campaigns.reader import DBICampaignReader
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.scientific_intake_scope import PRE_INTAKE_STATUSES
from app.dbi.scientific_qml_receipt import (
    QML_MAX_BYTES, ScientificQMLIntakeItem, ScientificQMLPrivateReceipt,
    plan_scientific_qml_private_receipt,
)
from app.dbi.storage_contracts import (
    DBIStorageConflict, DBIStorageError, DBIStorageIntegrityError,
    DBIStorageWriteRequest,
)

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-private-qml"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


def _hidden() -> HTTPException:
    return HTTPException(status_code=404, detail="Recepción científica no disponible.")


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/qml/{index}",
    response_model=ScientificQMLPrivateReceipt,
    status_code=201,
)
async def receive_private_scientific_qml(
    organization_ref: str,
    farm_id: UUID,
    plot_id: UUID,
    campaign_id: UUID,
    index: str,
    request: Request,
    response: Response,
    session: SessionDep,
    context: AccessDep,
    relative_path: Annotated[str, Header(alias="X-DBI-Original-Relative-Path")],
    expected_sha256: Annotated[str, Header(alias="X-DBI-Original-SHA256")],
    expected_size: Annotated[int, Header(alias="X-DBI-Original-Size")],
) -> ScientificQMLPrivateReceipt:
    """MANAGE, Campaign exacta MULTI, SHA-256 del servidor y put privado inmutable."""
    # Antes de leer bytes o consultar almacenamiento, exigir autoridad de lote.
    try:
        DBIAuthorizationPolicy.require_plot(
            context, tenant_ref=context.tenant_ref,
            organization_ref=organization_ref, farm_id=farm_id,
            plot_id=plot_id, permission=DBIPermission.MANAGE,
        )
        campaign = DBICampaignReader(session).read_campaign(
            campaign_id=campaign_id, tenant_ref=context.tenant_ref,
            organization_ref=organization_ref, farm_id=farm_id, plot_id=plot_id,
        )
        if (
            campaign.campaign_id != campaign_id
            or campaign.tenant_ref != context.tenant_ref
            or campaign.organization_ref != organization_ref
            or campaign.farm_id != farm_id or campaign.plot_id != plot_id
            or campaign.analysis_type != DBICampaignAnalysisType.MULTISPECTRAL
            or campaign.status not in PRE_INTAKE_STATUSES
            or campaign.approved_at is not None or campaign.published_at is not None
        ):
            raise _hidden()
    except (DBIAccessDenied, DBICampaignUnavailable) as error:
        raise _hidden() from error

    # La capacidad permanece desactivada en main y no puede habilitarse en
    # staging/production hasta catálogo, auditoría y aprobación institucional.
    if (
        os.environ.get("DBI_SCIENTIFIC_QML_INTAKE_ENABLED") != "1"
        or os.environ.get("DBI_ENVIRONMENT", "").lower() not in {"development", "local", "test"}
    ):
        raise HTTPException(status_code=503, detail="Recepción QML privada no habilitada.")

    try:
        item = ScientificQMLIntakeItem.model_validate({
            "index": index, "relative_path": relative_path,
            "size_bytes": expected_size, "sha256": expected_sha256,
        })
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="Metadatos QML inválidos.") from error

    if (
        (request.headers.get("content-type") or "").lower() != "text/plain"
        or request.headers.get("content-encoding", "identity").lower() != "identity"
    ):
        raise HTTPException(status_code=415, detail="Transporte QML exige text/plain sin compresión.")
    length = request.headers.get("content-length")
    if length is not None and (not length.isdecimal() or int(length) != item.size_bytes):
        raise HTTPException(status_code=409, detail="Longitud HTTP distinta del original declarado.")

    payload = bytearray()
    async for part in request.stream():
        if len(payload) + len(part) > min(item.size_bytes, QML_MAX_BYTES):
            raise HTTPException(status_code=413, detail="Original QML excede la cuota privada.")
        payload.extend(part)
    if len(payload) != item.size_bytes or sha256(payload).hexdigest() != item.sha256:
        raise HTTPException(status_code=409, detail="Tamaño o SHA-256 del original divergente.")

    plan = plan_scientific_qml_private_receipt(
        tenant_ref=context.tenant_ref, organization_ref=organization_ref,
        farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id, item=item,
    )
    store = getattr(request.app.state, "dbi_object_store", None)
    if store is None or not callable(getattr(store, "put", None)):
        raise HTTPException(status_code=503, detail="Almacenamiento privado no disponible.")
    try:
        result = store.put(DBIStorageWriteRequest(metadata=plan.metadata), BytesIO(payload))
        if result.record.metadata != plan.metadata:
            raise DBIStorageIntegrityError("Recibo de objeto divergente.")
    except (DBIStorageConflict, DBIStorageIntegrityError) as error:
        raise HTTPException(status_code=409, detail="Conflicto de integridad en original privado.") from error
    except DBIStorageError as error:
        raise HTTPException(status_code=503, detail="Almacenamiento privado no disponible.") from error

    response.status_code = 201 if result.created else 200
    response.headers["Cache-Control"] = "private, no-store"
    return ScientificQMLPrivateReceipt(
        schema_version="dbi-h14-scientific-qml-private-receipt.v1",
        disposition="private_qml_original_received_pending_review",
        campaign_id=campaign_id, index=item.index,
        relative_path=item.relative_path, object_id=plan.metadata.address.object_id,
        size_bytes=item.size_bytes, sha256=item.sha256, created=result.created,
        transport_hash_verified=True, bundle_complete=False,
        scientific_validated=False, institutional_approved=False, published=False,
    )
