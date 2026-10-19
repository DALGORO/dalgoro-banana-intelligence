"""H14/2H-2C: register private scientific RGB/COG Assets without uploading bytes."""
from __future__ import annotations

import os
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.dbi_scientific_raster_sql_bindings import _locked_campaign
from app.api.v1.dbi_scientific_raster_reservations import (
    RasterIndex, RasterRole, _expected, _manifest, _read_slot,
    _role_index, _slot_address,
)
from app.api.v1.dbi_scientific_raster_preflight import _raster_address
from app.dbi.authorization import DBIAccessContext
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.scientific_raster_asset_repository import (
    DBIScientificRasterAssetRepository, ScientificRasterAssetConflict,
)
from app.dbi.scientific_raster_binding_repository import ScientificRasterBindingIntent
from app.dbi.storage_contracts import DBIStorageConflict, DBIStorageError, DBIStorageNotFound
from app.dbi.storage_policy import validate_sha256

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-raster-assets"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScientificRasterAssetRequest(_Strict):
    schema_version: Literal["dbi-h14-raster-asset-registration-request.v1"]
    manifest_sha256: str
    reservation_sha256: str

    @field_validator("manifest_sha256", "reservation_sha256")
    @classmethod
    def canonical_sha(cls, value: str) -> str:
        try:
            return validate_sha256(value)
        except DBIStorageConflict as error:
            raise ValueError("SHA-256 no canónico.") from error


class ScientificRasterAssetReceipt(_Strict):
    schema_version: Literal["dbi-h14-raster-asset-registration-receipt.v1"]
    campaign_id: UUID
    binding_id: UUID
    asset_id: UUID
    role: RasterRole
    index: RasterIndex | None
    asset_kind: Literal["orthophoto_rgb", "scientific_cog"]
    status: Literal["registered_pending_bytes"]
    declared_size_bytes: int
    declared_sha256: str
    target_object_id: UUID
    created: bool
    file_received: Literal[False]
    content_verified: Literal[False]
    session_started: Literal[False]
    grants_issued: Literal[False]
    institutional_approved: Literal[False]
    published: Literal[False]


def _enabled() -> None:
    if (
        os.environ.get("DBI_SCIENTIFIC_RASTER_ASSET_REGISTRATION_ENABLED") != "1"
        or os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise HTTPException(404, detail="Registro científico no disponible.")


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-raster-assets/{role}/{index}",
    response_model=ScientificRasterAssetReceipt,
)
def register_private_raster_asset(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: str, payload: ScientificRasterAssetRequest,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> ScientificRasterAssetReceipt:
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    mapped_index = None if index == "_" else index
    try:
        # Row lock serializes registration with Campaign approval via same DB UoW.
        _locked_campaign(session, context, organization_ref, farm_id, plot_id, campaign_id)
        _role_index(role, mapped_index)
        store, manifest, manifest_record = _manifest(
            request, context, organization_ref, farm_id, plot_id, campaign_id,
        )
        if manifest_record.metadata.sha256 != payload.manifest_sha256:
            raise HTTPException(409, detail="Manifiesto científico divergente.")
        slot_address = _slot_address(
            context, organization_ref, farm_id, plot_id, campaign_id, role, mapped_index,
        )
        slot, slot_record = _read_slot(store, slot_address)
        if slot_record.metadata.sha256 != payload.reservation_sha256:
            raise HTTPException(409, detail="Reserva científica divergente.")
        expected = _expected(
            context=context, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
            role=role, index=mapped_index, manifest=manifest, record=manifest_record,
        )
        if slot != expected.model_copy(update={"reserved_by": slot.reserved_by}):
            raise DBIStorageConflict("Reserva divergente del manifiesto.")
        if slot.reserved_by != context.principal_ref:
            raise HTTPException(409, detail="La reserva pertenece a otro operador.")

        target = _raster_address(
            context, organization_ref, farm_id, plot_id, campaign_id, role, mapped_index,
        )
        if target.object_id != slot.target_object_id:
            raise DBIStorageConflict("Identidad raster futura no coincide.")
        try:
            store.stat(target)
        except DBIStorageNotFound:
            pass
        else:
            raise HTTPException(409, detail="El TIFF ya existe; se requiere conciliación.")

        intent = ScientificRasterBindingIntent(
            tenant_ref=context.tenant_ref, organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, campaign_id=campaign_id,
            manifest_object_id=manifest_record.metadata.address.object_id,
            manifest_sha256=manifest_record.metadata.sha256,
            slot_object_id=slot_record.metadata.address.object_id,
            slot_sha256=slot_record.metadata.sha256,
            role=role, index_ref=mapped_index or "_",
            target_object_id=slot.target_object_id,
            declared_size_bytes=slot.declared_size_bytes,
            declared_sha256=slot.declared_sha256,
            reserved_by=slot.reserved_by, created_by_ref=context.principal_ref,
        )
        asset, created = DBIScientificRasterAssetRepository(session).register_asset(intent)
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except DBIStorageNotFound as error:
        session.rollback()
        raise HTTPException(404, detail="Expediente científico privado incompleto.") from error
    except ScientificRasterAssetConflict as error:
        session.rollback()
        raise HTTPException(409, detail="Vínculo o Asset científico divergente.") from error
    except (IntegrityError, SQLAlchemyError, DBIStorageError, ValueError, TypeError, KeyError) as error:
        session.rollback()
        raise HTTPException(503, detail="Registro científico privado inconsistente.") from error

    response.status_code = 201 if created else 200
    return ScientificRasterAssetReceipt(
        schema_version="dbi-h14-raster-asset-registration-receipt.v1",
        campaign_id=campaign_id, binding_id=intent.binding_id,
        asset_id=asset.id, role=role, index=mapped_index,
        asset_kind=asset.asset_kind, status="registered_pending_bytes",
        declared_size_bytes=asset.declared_size_bytes,
        declared_sha256=asset.declared_sha256,
        target_object_id=asset.target_object_id, created=created,
        file_received=False, content_verified=False, session_started=False,
        grants_issued=False, institutional_approved=False, published=False,
    )
