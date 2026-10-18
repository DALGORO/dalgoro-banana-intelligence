"""H14/2H-2A: reservas privadas inmutables de slots TIFF, SIN cargas ni sesiones.

Vincula los siete roles al manifiesto H14/2F y a sus objetos futuros H14/2H-1.
El recibo JSON es durable S3, pero NO es una inscripción transaccional en DB.
"""
from __future__ import annotations

import json
import os
from hashlib import sha256
from io import BytesIO
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from app.api.v1.dbi_scientific_manifest_private import (
    _address as _manifest_address, _authorize, _read as _read_manifest,
    _store as _private_store,
)
from app.api.v1.dbi_scientific_raster_preflight import _raster_address
from app.dbi.authorization import DBIAccessContext
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.scientific_intake_scope import INDEXES
from app.dbi.storage_contracts import (
    DBIStorageConflict, DBIStorageError, DBIStorageNotFound,
    DBIStoragePurpose, DBIStorageWriteRequest,
)
from app.dbi.storage_policy import DBIStoragePolicy, validate_sha256

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-raster-reservations"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]
RasterRole = Literal["rgb", "scientific_cog"]
RasterIndex = Literal["ndvi", "ndre", "gndvi", "evi2", "ci_red_edge", "ci_green"]
MAX_RESERVATION_BYTES = 8 * 1024


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PrivateRasterSlotRequest(_Strict):
    schema_version: Literal["dbi-h14-raster-slot-request.v1"]
    manifest_sha256: str

    @field_validator("manifest_sha256")
    @classmethod
    def canonical_sha(cls, value: str) -> str:
        try:
            return validate_sha256(value)
        except DBIStorageConflict as error:
            raise ValueError("Se requiere SHA-256 canónico del manifiesto.") from error


class _StoredSlot(_Strict):
    schema_version: Literal["dbi-h14-raster-slot.v1"]
    campaign_id: UUID
    manifest_object_id: UUID
    manifest_sha256: str
    role: RasterRole
    index: RasterIndex | None
    relative_path: str
    declared_size_bytes: int
    declared_sha256: str
    target_object_id: UUID
    reserved_by: str
    state: Literal["metadata_reserved_no_upload"]
    asset_registered: Literal[False]
    session_initiated: Literal[False]
    grants_issued: Literal[False]
    raster_bytes_received: Literal[False]
    content_verified: Literal[False]
    institutional_approved: Literal[False]
    published: Literal[False]


class PrivateRasterSlotReceipt(_Strict):
    schema_version: Literal["dbi-h14-raster-slot-receipt.v1"]
    reservation_object_id: UUID
    reservation_sha256: str
    created_at: str
    created: bool
    reservation: _StoredSlot


def _hidden() -> HTTPException:
    return HTTPException(404, detail="Reserva raster científica no disponible.")


def _enabled() -> None:
    if (
        os.environ.get("DBI_SCIENTIFIC_RASTER_RESERVATION_ENABLED") != "1"
        or os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise _hidden()


def _role_index(role: RasterRole, index: RasterIndex | None) -> None:
    if not ((role == "rgb" and index is None) or
            (role == "scientific_cog" and index in INDEXES)):
        raise HTTPException(422, detail="Rol e índice raster incompatibles.")


def _slot_address(
    context: DBIAccessContext, organization_ref: str, farm_id: UUID,
    plot_id: UUID, campaign_id: UUID, role: RasterRole, index: RasterIndex | None,
):
    _role_index(role, index)
    identifier = uuid5(
        NAMESPACE_URL,
        "dalgoro-dbi:h14:private-raster-slot:v1:"
        + "|".join((
            context.tenant_ref, organization_ref, str(farm_id),
            str(plot_id), str(campaign_id), role, index or "-",
        )),
    )
    return DBIStoragePolicy.build_address(
        tenant_ref=context.tenant_ref,
        purpose=DBIStoragePurpose.ANALYSIS_INPUT,
        object_id=identifier,
    )


def _manifest(
    request: Request, context: DBIAccessContext, organization_ref: str,
    farm_id: UUID, plot_id: UUID, campaign_id: UUID,
):
    store = _private_store(request)  # S3 obligatorio; nunca proveedor local/in-memory real.
    saved, record = _read_manifest(
        store, _manifest_address(context, organization_ref, farm_id, plot_id, campaign_id),
    )
    scope = saved.submission.draft.scope
    if (
        scope.tenant_ref != context.tenant_ref
        or scope.organization_ref != organization_ref
        or scope.farm_id != farm_id or scope.plot_id != plot_id
        or scope.campaign_id != campaign_id
    ):
        raise _hidden()
    return store, saved, record


def _expected(
    *, context: DBIAccessContext, organization_ref: str,
    farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: RasterIndex | None, manifest, record,
) -> _StoredSlot:
    files = {(x.role, x.index): x for x in manifest.submission.draft.files}
    hashes = {(x.role, x.index): x.declared_sha256 for x in manifest.submission.declared_hashes}
    item = files[(role, index)]
    target = _raster_address(
        context, organization_ref, farm_id, plot_id, campaign_id, role, index,
    )
    return _StoredSlot(
        schema_version="dbi-h14-raster-slot.v1",
        campaign_id=campaign_id,
        manifest_object_id=record.metadata.address.object_id,
        manifest_sha256=record.metadata.sha256,
        role=role, index=index, relative_path=item.relative_path,
        declared_size_bytes=item.size_bytes,
        declared_sha256=hashes[(role, index)],
        target_object_id=target.object_id,
        reserved_by=context.principal_ref,
        state="metadata_reserved_no_upload",
        asset_registered=False, session_initiated=False, grants_issued=False,
        raster_bytes_received=False, content_verified=False,
        institutional_approved=False, published=False,
    )


def _canonical_bytes(saved: _StoredSlot) -> bytes:
    return json.dumps(
        saved.model_dump(mode="json"), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def _read_slot(store, address) -> tuple[_StoredSlot, object]:
    record = store.stat(address)
    meta = record.metadata
    if (
        meta.address != address or meta.content_type != "application/json"
        or meta.size_bytes <= 0 or meta.size_bytes > MAX_RESERVATION_BYTES
    ):
        raise DBIStorageConflict("Metadatos de la reserva no canónicos.")
    with store.open_read(address) as stream:
        payload = stream.read(MAX_RESERVATION_BYTES + 1)
        extra = stream.read(1)
    if (
        not isinstance(payload, bytes) or extra not in (b"", None)
        or len(payload) != meta.size_bytes
        or sha256(payload).hexdigest() != meta.sha256
    ):
        raise DBIStorageConflict("Bytes de la reserva no verificables.")
    saved = _StoredSlot.model_validate_json(payload)
    if _canonical_bytes(saved) != payload:
        raise DBIStorageConflict("JSON de reserva no canónico.")
    return saved, record


def _receipt(saved: _StoredSlot, record, *, created: bool) -> PrivateRasterSlotReceipt:
    return PrivateRasterSlotReceipt(
        schema_version="dbi-h14-raster-slot-receipt.v1",
        reservation_object_id=record.metadata.address.object_id,
        reservation_sha256=record.metadata.sha256,
        created_at=record.created_at.isoformat(),
        created=created, reservation=saved,
    )


PATH = (
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-raster-slots/{role}/{index}"
)


@router.put(PATH, response_model=PrivateRasterSlotReceipt)
def reserve_private_raster_slot(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: str, payload: PrivateRasterSlotRequest,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> PrivateRasterSlotReceipt:
    """Reserva un rol por Campaign y manifiesto; no inicia multipart."""
    _enabled()
    _authorize(
        session, context, organization_ref=organization_ref,
        farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
    )
    mapped_index = None if index == "_" else index
    _role_index(role, mapped_index)
    try:
        store, manifest, record = _manifest(
            request, context, organization_ref, farm_id, plot_id, campaign_id,
        )
        if record.metadata.sha256 != payload.manifest_sha256:
            raise HTTPException(409, detail="Huella del manifiesto no coincide.")
        address = _slot_address(
            context, organization_ref, farm_id, plot_id, campaign_id, role, mapped_index,
        )
        saved = _expected(
            context=context, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
            role=role, index=mapped_index, manifest=manifest, record=record,
        )
        content = _canonical_bytes(saved)
        if len(content) > MAX_RESERVATION_BYTES:
            raise HTTPException(413, detail="Reserva supera cuota privada.")
        # No reservar silenciosamente sobre un TIFF ya presente sin expediente.
        target = _raster_address(
            context, organization_ref, farm_id, plot_id, campaign_id,
            role, mapped_index,
        )
        try:
            store.stat(target)
        except DBIStorageNotFound:
            pass
        else:
            raise HTTPException(409, detail="El destino TIFF ya tiene un objeto.")
        metadata = DBIStoragePolicy.build_metadata(
            address=address, content_type="application/json",
            size_bytes=len(content), sha256_hex=sha256(content).hexdigest(),
        )
        written = store.put(DBIStorageWriteRequest(metadata=metadata), BytesIO(content))
    except DBIStorageNotFound as error:
        raise _hidden() from error
    except (DBIStorageConflict, DBIStorageError, ValueError, TypeError, KeyError) as error:
        # El conflict del proveedor no debe volver a escribir una reserva divergente.
        if isinstance(error, DBIStorageConflict):
            raise HTTPException(409, detail="Ya existe una reserva divergente.") from error
        raise HTTPException(503, detail="Reserva privada inconsistente o no disponible.") from error
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 201 if written.created else 200
    return _receipt(saved, written.record, created=written.created)


@router.get(PATH, response_model=PrivateRasterSlotReceipt)
def read_private_raster_slot(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: str, request: Request, response: Response,
    session: SessionDep, context: AccessDep,
) -> PrivateRasterSlotReceipt:
    _enabled()
    _authorize(
        session, context, organization_ref=organization_ref,
        farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
    )
    mapped_index = None if index == "_" else index
    _role_index(role, mapped_index)
    try:
        store, manifest, record = _manifest(
            request, context, organization_ref, farm_id, plot_id, campaign_id,
        )
        address = _slot_address(
            context, organization_ref, farm_id, plot_id, campaign_id, role, mapped_index,
        )
        saved, slot_record = _read_slot(store, address)
        expected = _expected(
            context=context, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
            role=role, index=mapped_index, manifest=manifest, record=record,
        )
        # Un segundo operador MANAGE sí puede inspeccionar sin cambiar al reservador.
        if saved != expected.model_copy(update={"reserved_by": saved.reserved_by}):
            raise DBIStorageConflict("Reserva divergente del manifiesto vigente.")
    except DBIStorageNotFound as error:
        raise _hidden() from error
    except (DBIStorageConflict, DBIStorageError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(503, detail="Reserva privada inconsistente o no disponible.") from error
    response.headers["Cache-Control"] = "no-store"
    return _receipt(saved, slot_record, created=False)
