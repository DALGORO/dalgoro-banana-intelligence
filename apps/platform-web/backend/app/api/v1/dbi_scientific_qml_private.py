"""H14/2E: recepción *privada* de QML originales, sin conversión ni publicación.

Superficie intencionalmente reducida: solo seis QML pequeños, bajo un feature
flag apagado por defecto. Los COG/RGB grandes necesitan otra etapa multipart.
"""
from __future__ import annotations

import os
from hashlib import sha256
from io import BytesIO
from typing import Annotated, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
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
from app.dbi.storage_contracts import (
    DBIStorageConflict, DBIStorageError, DBIStorageNotFound,
    DBIStorageObjectRecord, DBIStoragePurpose, DBIStorageWriteRequest,
)
from app.dbi.storage_policy import DBIStoragePolicy, validate_sha256
from app.dbi.storage_s3 import DBIS3ObjectStore

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-qml-private"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]
IndexRef = Literal["ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green"]
MAX_QML_BYTES = 2 * 1024 * 1024


class _PrivateStore(Protocol):
    def put(self, request: DBIStorageWriteRequest, content: BytesIO): ...
    def stat(self, address: object) -> DBIStorageObjectRecord: ...


class PrivateQMLReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["dbi-h14-private-qml-receipt.v1"]
    campaign_id: UUID
    index: IndexRef
    object_id: UUID
    size_bytes: int
    sha256: str
    created: bool
    file_received_privately: Literal[True]
    bundle_received: Literal[False]
    scientific_validated: Literal[False]
    institutional_approved: Literal[False]
    published: Literal[False]


def _hidden() -> HTTPException:
    return HTTPException(404, detail="Recepción científica no disponible.")


def _enabled() -> None:
    # Defensa adicional: incluso importando el router directamente sigue apagado.
    if os.environ.get("DBI_SCIENTIFIC_QML_INTAKE_ENABLED") != "1":
        raise _hidden()


def _authorized_campaign(
    session: Session, context: DBIAccessContext, *,
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
) -> None:
    # Revalidar en cada PUT/GET. Nunca confiar en un scope-preflight anterior.
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
            or campaign.approved_at is not None
            or campaign.published_at is not None
        ):
            raise _hidden()
    except (DBIAccessDenied, DBICampaignUnavailable) as error:
        raise _hidden() from error


def _address(context: DBIAccessContext, organization_ref: str,
             farm_id: UUID, plot_id: UUID, campaign_id: UUID, index: IndexRef):
    # Una clave por Campaign + índice: reintentos idénticos sí, sobrescribir no.
    # El namespace no admite rutas locales, nombres, URLs ni claves del cliente.
    identifier = uuid5(
        NAMESPACE_URL,
        "dalgoro-dbi:h14:private-original-qml:v1:"
        + "|".join((context.tenant_ref, organization_ref, str(farm_id),
                    str(plot_id), str(campaign_id), index)),
    )
    return DBIStoragePolicy.build_address(
        tenant_ref=context.tenant_ref,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=identifier,
    )


def _store(request: Request) -> _PrivateStore:
    provider = getattr(request.app.state, "dbi_object_store", None)
    # No permitir disco local ni memoria efímera para originales científicos reales.
    if not isinstance(provider, DBIS3ObjectStore) or any(
        not callable(getattr(provider, attr, None)) for attr in ("put", "stat")
    ):
        raise HTTPException(503, detail="Almacenamiento científico privado no configurado.")
    return provider


def _receipt(*, campaign_id: UUID, index: IndexRef,
             record: DBIStorageObjectRecord, created: bool) -> PrivateQMLReceipt:
    return PrivateQMLReceipt(
        schema_version="dbi-h14-private-qml-receipt.v1",
        campaign_id=campaign_id, index=index,
        object_id=record.metadata.address.object_id,
        size_bytes=record.metadata.size_bytes, sha256=record.metadata.sha256,
        created=created, file_received_privately=True, bundle_received=False,
        scientific_validated=False, institutional_approved=False, published=False,
    )


@router.put(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-qml/{index}",
    response_model=PrivateQMLReceipt,
)
async def receive_private_qml(
    organization_ref: str, farm_id: UUID, plot_id: UUID,
    campaign_id: UUID, index: IndexRef,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
    expected_size: Annotated[int, Header(alias="X-DBI-Expected-Size")],
    expected_sha256: Annotated[str, Header(alias="X-DBI-Expected-SHA256")],
    content_type: Annotated[str, Header(alias="Content-Type")],
) -> PrivateQMLReceipt:
    """El servidor verifica bytes y escribe el ORIGINAL sin transformarlo."""
    _enabled()
    _authorized_campaign(
        session, context, organization_ref=organization_ref, farm_id=farm_id,
        plot_id=plot_id, campaign_id=campaign_id,
    )
    if content_type != "application/octet-stream":
        raise HTTPException(415, detail="Solo flujo binario QML sin ejecución.")
    if expected_size <= 0 or expected_size > MAX_QML_BYTES:
        raise HTTPException(413, detail="QML fuera de límite privado (2 MiB).")
    try:
        declared_hash = validate_sha256(expected_sha256)
    except DBIStorageConflict as error:
        raise HTTPException(422, detail="SHA-256 declarado no canónico.") from error
    store = _store(request)
    digest = sha256()
    stream = BytesIO()
    size = 0
    async for chunk in request.stream():
        if not isinstance(chunk, bytes):
            raise HTTPException(422, detail="Flujo binario no válido.")
        size += len(chunk)
        if size > expected_size or size > MAX_QML_BYTES:
            raise HTTPException(413, detail="QML excede tamaño declarado o cuota.")
        digest.update(chunk)
        stream.write(chunk)
    if size != expected_size or digest.hexdigest() != declared_hash:
        raise HTTPException(422, detail="El archivo no coincide con tamaño y SHA-256.")
    address = _address(context, organization_ref, farm_id, plot_id, campaign_id, index)
    metadata = DBIStoragePolicy.build_metadata(
        address=address, content_type="application/octet-stream",
        size_bytes=size, sha256_hex=digest.hexdigest(),
    )
    stream.seek(0)
    try:
        result = store.put(DBIStorageWriteRequest(metadata=metadata), stream)
    except DBIStorageConflict as error:
        raise HTTPException(409, detail="El QML ya existe con otros bytes; no se sobrescribe.") from error
    except DBIStorageError as error:
        raise HTTPException(503, detail="Almacenamiento privado no disponible.") from error
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 201 if result.created else 200
    return _receipt(campaign_id=campaign_id, index=index,
                    record=result.record, created=result.created)


@router.get(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-qml/{index}",
    response_model=PrivateQMLReceipt,
)
def get_private_qml_receipt(
    organization_ref: str, farm_id: UUID, plot_id: UUID,
    campaign_id: UUID, index: IndexRef,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> PrivateQMLReceipt:
    """Solo metadatos autorizados MANAGE; jamás entrega binario ni URL pública."""
    _enabled()
    _authorized_campaign(
        session, context, organization_ref=organization_ref,
        farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
    )
    store = _store(request)
    try:
        record = store.stat(_address(context, organization_ref, farm_id, plot_id,
                                     campaign_id, index))
    except DBIStorageNotFound as error:
        raise _hidden() from error
    except DBIStorageError as error:
        raise HTTPException(503, detail="Almacenamiento privado no disponible.") from error
    response.headers["Cache-Control"] = "no-store"
    return _receipt(campaign_id=campaign_id, index=index, record=record, created=False)
