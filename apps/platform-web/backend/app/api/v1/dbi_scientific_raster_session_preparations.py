"""H14/2H-2D: private prepare/inspect/cancel *ticket*, not a multipart upload."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.dbi_scientific_raster_sql_bindings import _locked_campaign
from app.api.v1.dbi_scientific_raster_reservations import (
    RasterRole, RasterIndex, _expected, _manifest, _read_slot,
    _role_index, _slot_address,
)
from app.api.v1.dbi_scientific_raster_preflight import _raster_address
from app.dbi.authorization import DBIAccessContext
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.scientific_raster_binding_repository import ScientificRasterBindingIntent
from app.dbi.scientific_raster_session_repository import (
    DBIScientificSessionPreparationRepository, ScientificSessionPreparationConflict,
    SessionPreparationRequest,
)
from app.dbi.storage_contracts import DBIStorageConflict, DBIStorageError, DBIStorageNotFound
from app.dbi.storage_policy import validate_sha256

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-raster-session-preparations"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]
Operation = Literal["prepare", "inspect", "cancel"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScientificSessionPreparationPayload(_Strict):
    schema_version: Literal["dbi-h14-private-session-preparation-request.v1"]
    manifest_sha256: str
    reservation_sha256: str
    idempotency_key: str

    @field_validator("manifest_sha256", "reservation_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        try:
            return validate_sha256(value)
        except DBIStorageConflict as error:
            raise ValueError("Huella no canónica.") from error


class ScientificSessionPreparationReceipt(_Strict):
    schema_version: Literal["dbi-h14-private-session-preparation-receipt.v1"]
    campaign_id: UUID
    binding_id: UUID
    asset_id: UUID
    preparation_id: UUID
    role: RasterRole
    index: RasterIndex | None
    status: Literal["prepared_no_provider", "cancelled_no_provider"]
    created: bool
    changed: bool
    expired: bool
    expires_at: datetime
    part_size_bytes: int
    part_count: int
    transport_checksum_algorithm: Literal["SHA256"]
    transport_checksum_type: Literal["COMPOSITE"]
    ready_for_upload: Literal[False]
    provider_started: Literal[False]
    session_started: Literal[False]
    grants_issued: Literal[False]
    file_received: Literal[False]
    content_verified: Literal[False]
    institutional_approved: Literal[False]
    published: Literal[False]


def _enabled() -> None:
    if (
        os.environ.get("DBI_SCIENTIFIC_RASTER_SESSION_PREP_ENABLED") != "1"
        or os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise HTTPException(404, detail="Preparación multipart privada no disponible.")


def _verified_intent(
    request: Request, context: DBIAccessContext,
    organization_ref: str, farm_id: UUID, plot_id: UUID,
    campaign_id: UUID, role: RasterRole, index: RasterIndex | None,
    payload: ScientificSessionPreparationPayload,
) -> ScientificRasterBindingIntent:
    store, manifest, manifest_record = _manifest(
        request, context, organization_ref, farm_id, plot_id, campaign_id,
    )
    if manifest_record.metadata.sha256 != payload.manifest_sha256:
        raise HTTPException(409, detail="Manifiesto divergente.")
    slot_address = _slot_address(
        context, organization_ref, farm_id, plot_id, campaign_id, role, index,
    )
    slot, slot_record = _read_slot(store, slot_address)
    if slot_record.metadata.sha256 != payload.reservation_sha256:
        raise HTTPException(409, detail="Reserva divergente.")
    expected = _expected(
        context=context, organization_ref=organization_ref,
        farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
        role=role, index=index, manifest=manifest, record=manifest_record,
    )
    if slot != expected.model_copy(update={"reserved_by": slot.reserved_by}):
        raise DBIStorageConflict("Reserva ajena o inconsistente.")
    if slot.reserved_by != context.principal_ref:
        raise HTTPException(409, detail="La reserva pertenece a otro operador.")
    target = _raster_address(
        context, organization_ref, farm_id, plot_id, campaign_id, role, index,
    )
    if slot.target_object_id != target.object_id:
        raise DBIStorageConflict("La identidad del TIFF no coincide.")
    try:
        store.stat(target)
    except DBIStorageNotFound:
        pass
    else:
        raise HTTPException(409, detail="El TIFF ya existe; no se prepara otra sesión.")

    return ScientificRasterBindingIntent(
        tenant_ref=context.tenant_ref, organization_ref=organization_ref,
        farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
        manifest_object_id=manifest_record.metadata.address.object_id,
        manifest_sha256=manifest_record.metadata.sha256,
        slot_object_id=slot_record.metadata.address.object_id,
        slot_sha256=slot_record.metadata.sha256,
        role=role, index_ref=index or "_",
        target_object_id=slot.target_object_id,
        declared_size_bytes=slot.declared_size_bytes,
        declared_sha256=slot.declared_sha256,
        reserved_by=slot.reserved_by, created_by_ref=context.principal_ref,
    )


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-raster-session-preparations"
    "/{role}/{index}/{operation}",
    response_model=ScientificSessionPreparationReceipt,
)
def handle_scientific_session_preparation(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: str, operation: Operation,
    payload: ScientificSessionPreparationPayload,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> ScientificSessionPreparationReceipt:
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    mapped_index = None if index == "_" else index
    now = datetime.now(timezone.utc)
    try:
        # Every operation (including inspection and cancellation) takes the
        # exact Campaign row lock BEFORE S3 or SQL binding/asset access.
        _locked_campaign(
            session, context, organization_ref, farm_id, plot_id, campaign_id,
        )
        _role_index(role, mapped_index)
        raster = _verified_intent(
            request, context, organization_ref, farm_id, plot_id, campaign_id,
            role, mapped_index, payload,
        )
        evidence = SessionPreparationRequest(
            raster=raster, idempotency_key=payload.idempotency_key,
            requested_by=context.principal_ref,
        )
        repository = DBIScientificSessionPreparationRepository(session)
        if operation == "prepare":
            row, created = repository.prepare(evidence, now=now)
            changed = created
        elif operation == "inspect":
            row = repository.inspect(evidence, now=now)
            created = changed = False
        else:
            row, changed = repository.cancel(evidence, now=now)
            created = False
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except DBIStorageNotFound as error:
        session.rollback()
        raise HTTPException(404, detail="Expediente privado incompleto.") from error
    except ScientificSessionPreparationConflict as error:
        session.rollback()
        raise HTTPException(409, detail=str(error)) from error
    except (DBIStorageError, IntegrityError, SQLAlchemyError, ValueError, TypeError, KeyError) as error:
        session.rollback()
        raise HTTPException(503, detail="Preparación científica inaccesible/inconsistente.") from error

    response.status_code = 201 if created else 200
    return ScientificSessionPreparationReceipt(
        schema_version="dbi-h14-private-session-preparation-receipt.v1",
        campaign_id=campaign_id,
        binding_id=raster.binding_id, asset_id=evidence.asset_id,
        preparation_id=row.id, role=role, index=mapped_index,
        status=row.status, created=created, changed=changed,
        expired=now >= row.expires_at, expires_at=row.expires_at,
        part_size_bytes=row.part_size_bytes, part_count=row.part_count,
        transport_checksum_algorithm="SHA256", transport_checksum_type="COMPOSITE",
        ready_for_upload=False, provider_started=False, session_started=False,
        grants_issued=False, file_received=False, content_verified=False,
        institutional_approved=False, published=False,
    )
