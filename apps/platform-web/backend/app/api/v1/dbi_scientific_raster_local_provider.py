"""H14/2H-2D/2: S3 *loopback only* provider start/inspect/abort, never grants."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.dbi_scientific_raster_session_preparations import (
    ScientificSessionPreparationPayload, _verified_intent,
)
from app.api.v1.dbi_scientific_raster_sql_bindings import _locked_campaign
from app.api.v1.dbi_scientific_raster_reservations import (
    RasterRole, RasterIndex, _role_index,
)
from app.dbi.asset_multipart_provider import (
    DBIMultipartProviderAbortRequest, DBIMultipartProviderError,
    DBIMultipartProviderInitiateRequest, DBIMultipartProviderPolicy,
)
from app.dbi.asset_multipart_s3 import DBIS3MultipartAdapter
from app.dbi.authorization import DBIAccessContext
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.scientific_raster_provider_start_repository import (
    DBIScientificProviderStartRepository, ScientificProviderStartConflict,
)
from app.dbi.scientific_raster_session_repository import (
    DBIScientificSessionPreparationRepository,
    ScientificSessionPreparationConflict, SessionPreparationRequest, _id, _validate,
)
from app.dbi.storage_contracts import DBIStorageError, DBIStorageNotFound
from app.dbi.storage_policy import DBIStoragePolicy
from app.dbi.storage_contracts import DBIStoragePurpose

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-loopback-provider"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]
Operation = Literal["start", "inspect", "abort"]


class ProviderLifecycleReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["dbi-h14-local-provider-lifecycle.v1"]
    campaign_id: UUID
    preparation_id: UUID
    asset_id: UUID
    role: RasterRole
    index: RasterIndex | None
    state: Literal["initiated_no_grants", "aborted_no_grants"]
    created: bool
    changed: bool
    provider_started: bool
    provider_aborted: bool
    ready_for_upload: Literal[False]
    grants_issued: Literal[False]
    parts_received: Literal[False]
    file_received: Literal[False]
    content_verified: Literal[False]
    institutional_approved: Literal[False]
    published: Literal[False]


def _enabled() -> None:
    if (
        os.environ.get("DBI_SCIENTIFIC_RASTER_PROVIDER_START_ENABLED") != "1"
        or os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise HTTPException(404, detail="Inicio S3 científico experimental no disponible.")


def _provider(request: Request) -> DBIS3MultipartAdapter:
    # NEVER resolve the legacy asset uploader here. Distinct app.state handle.
    value = getattr(request.app.state, "dbi_scientific_raster_multipart_store", None)
    if not isinstance(value, DBIS3MultipartAdapter):
        raise HTTPException(503, detail="Se exige adaptador S3 multipart exclusivamente loopback.")
    return value


def _upload_contract(value: SessionPreparationRequest, *, now: datetime):
    _, plan = _validate(value)
    metadata = DBIStoragePolicy.build_metadata(
        address=DBIStoragePolicy.build_address(
            tenant_ref=value.raster.tenant_ref,
            purpose=DBIStoragePurpose.ANALYSIS_INPUT,
            object_id=value.raster.target_object_id,
        ),
        content_type="image/tiff",
        size_bytes=value.raster.declared_size_bytes,
        sha256_hex=value.raster.declared_sha256,
    )
    return DBIMultipartProviderInitiateRequest(
        session_id=_id(value.asset_id),
        metadata=metadata, plan=plan, initiated_at=now,
    )


def _abort_request(contract, *, now: datetime, ref: str | None):
    return DBIMultipartProviderAbortRequest(
        session_id=contract.session_id,
        metadata=contract.metadata, plan=contract.plan,
        initiated_at=contract.initiated_at,
        requested_at=max(now, contract.initiated_at),
        provider_upload_ref=ref,
    )


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-raster-local-provider"
    "/{role}/{index}/{operation}",
    response_model=ProviderLifecycleReceipt,
)
def scientific_local_provider_lifecycle(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: str, operation: Operation,
    payload: ScientificSessionPreparationPayload,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> ProviderLifecycleReceipt:
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(timezone.utc)
    mapped = None if index == "_" else index
    started = None
    provider = None
    contract = None
    committed = False
    try:
        _locked_campaign(
            session, context, organization_ref, farm_id, plot_id, campaign_id,
        )
        _role_index(role, mapped)
        raster = _verified_intent(
            request, context, organization_ref, farm_id, plot_id, campaign_id,
            role, mapped, payload,
        )
        value = SessionPreparationRequest(
            raster=raster, idempotency_key=payload.idempotency_key,
            requested_by=context.principal_ref,
        )
        preparations = DBIScientificSessionPreparationRepository(session)
        ticket = preparations.inspect(value, now=now)
        if ticket.status != "prepared_no_provider" and operation == "start":
            raise ScientificSessionPreparationConflict("Ticket cancelado.")
        ledger = DBIScientificProviderStartRepository(session)
        previous = ledger.get(value)
        provider = _provider(request)
        if operation == "start":
            if now >= ticket.expires_at:
                raise ScientificSessionPreparationConflict("Ticket caducado.")
            if previous is not None:
                if previous.status != "initiated_no_grants":
                    raise ScientificProviderStartConflict("Sesión abortada y no reabrible.")
                row = previous
                created = changed = False
            else:
                contract = _upload_contract(value, now=now)
                started = provider.initiate(contract)
                canonical = DBIMultipartProviderPolicy.validate_upload(started)
                if (
                    canonical.session_id != contract.session_id
                    or canonical.metadata != contract.metadata
                    or canonical.plan != contract.plan
                    or canonical.initiated_at != contract.initiated_at
                ):
                    raise ScientificProviderStartConflict("S3 devolvió otra carga.")
                row = ledger.record_start(value, canonical, now=now)
                created = changed = True
        elif operation == "inspect":
            if previous is None:
                raise ScientificProviderStartConflict("No existe inicio S3.")
            row, created, changed = previous, False, False
        else:
            if previous is None:
                raise ScientificProviderStartConflict("No existe carga iniciada.")
            row, created, changed = previous, False, False
            if row.status == "initiated_no_grants":
                contract = _upload_contract(value, now=row.created_at)
                confirmation = provider.abort(_abort_request(
                    contract, now=now, ref=row.provider_upload_ref,
                ))
                DBIMultipartProviderPolicy.validate_abort_confirmation(confirmation)
                if confirmation.session_id != contract.session_id or not confirmation.cleanup_confirmed:
                    raise ScientificProviderStartConflict("S3 no confirmó limpieza completa.")
                row, changed = ledger.mark_aborted(value, now=now)
                preparations.cancel(value, now=now)
        session.commit()
        committed = True
    except Exception as error:
        session.rollback()
        if started is not None and not committed and provider is not None and contract is not None:
            # Compensating abort is mandatory if S3 has initiated an upload but
            # SQL persistence failed. No grants were ever issued.
            try:
                cleanup = provider.abort(_abort_request(
                    contract, now=datetime.now(timezone.utc),
                    ref=started.provider_upload_ref,
                ))
                DBIMultipartProviderPolicy.validate_abort_confirmation(cleanup)
                if not cleanup.cleanup_confirmed:
                    raise ScientificProviderStartConflict("Limpieza remota no confirmada.")
            except Exception as cleanup_error:
                raise HTTPException(
                    503, detail="Inicio fallido y limpieza S3 pendiente de revisión manual.",
                ) from cleanup_error
        if isinstance(error, HTTPException):
            raise
        if isinstance(error, (ScientificSessionPreparationConflict, ScientificProviderStartConflict)):
            raise HTTPException(409, detail="Sesión científica inexistente, expirada o divergente.") from error
        if isinstance(error, DBIStorageNotFound):
            raise HTTPException(404, detail="Expediente privado incompleto.") from error
        if isinstance(error, (DBIStorageError, DBIMultipartProviderError, SQLAlchemyError,
                              IntegrityError, ValueError, TypeError, KeyError)):
            raise HTTPException(503, detail="Proveedor local o SQL no disponible.") from error
        raise

    response.status_code = 201 if created else 200
    return ProviderLifecycleReceipt(
        schema_version="dbi-h14-local-provider-lifecycle.v1",
        campaign_id=campaign_id, preparation_id=_id(value.asset_id),
        asset_id=value.asset_id, role=role, index=mapped,
        state=row.status, created=created, changed=changed,
        provider_started=row.status == "initiated_no_grants",
        provider_aborted=row.status == "aborted_no_grants",
        ready_for_upload=False, grants_issued=False, parts_received=False,
        file_received=False, content_verified=False,
        institutional_approved=False, published=False,
    )
