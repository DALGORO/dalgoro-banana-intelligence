"""H14/2H-2B: registrar vínculo SQL reservado, sin crear un Asset ni multipart.

La UoW bloquea Campaign ANTES de consultar S3 y persiste el vínculo
bajo la misma transacción. No existen endpoints para grants/cargas.
"""
from __future__ import annotations

import os
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.dbi_scientific_raster_reservations import (
    RasterIndex, RasterRole,
    _expected, _manifest, _read_slot, _role_index, _slot_address,
)
from app.dbi.authorization import (
    DBIAccessContext, DBIAccessDenied, DBIAuthorizationPolicy, DBIPermission,
)
from app.dbi.campaigns.repository import DBICampaignRepository
from app.dbi.dependencies import get_dbi_access_context, get_dbi_session
from app.dbi.scientific_intake_scope import PRE_INTAKE_STATUSES
from app.dbi.scientific_raster_binding_repository import (
    DBIScientificRasterBindingRepository, ScientificRasterBindingConflict,
    ScientificRasterBindingIntent,
)
from app.dbi.storage_contracts import (
    DBIStorageConflict, DBIStorageError, DBIStorageNotFound,
)
from app.dbi.storage_policy import validate_sha256

router = APIRouter(prefix="/dbi", tags=["dbi-scientific-raster-bindings"])
SessionDep = Annotated[Session, Depends(get_dbi_session)]
AccessDep = Annotated[DBIAccessContext, Depends(get_dbi_access_context)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScientificRasterBindingRequest(_Strict):
    schema_version: Literal["dbi-h14-sql-raster-binding-request.v1"]
    manifest_sha256: str
    reservation_sha256: str

    @field_validator("manifest_sha256", "reservation_sha256")
    @classmethod
    def sha_canonical(cls, value: str) -> str:
        try:
            return validate_sha256(value)
        except DBIStorageConflict as error:
            raise ValueError("SHA-256 no canónico.") from error


class ScientificRasterBindingReceipt(_Strict):
    schema_version: Literal["dbi-h14-sql-raster-binding-receipt.v1"]
    campaign_id: UUID
    binding_id: UUID
    manifest_sha256: str
    reservation_sha256: str
    target_object_id: UUID
    role: RasterRole
    index: RasterIndex | None
    created: bool
    state: Literal["reserved_no_asset"]
    asset_registered: Literal[False]
    session_initiated: Literal[False]
    grants_issued: Literal[False]
    file_received: Literal[False]
    content_verified: Literal[False]
    institutional_approved: Literal[False]
    published: Literal[False]


def _hidden() -> HTTPException:
    return HTTPException(404, detail="Vínculo científico no disponible.")


def _enabled() -> None:
    if (
        os.environ.get("DBI_SCIENTIFIC_RASTER_SQL_BINDING_ENABLED") != "1"
        or os.environ.get("DBI_ENVIRONMENT", "").strip().lower()
        not in {"test", "development", "local"}
    ):
        raise _hidden()


def _locked_campaign(
    session: Session, context: DBIAccessContext,
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
) -> None:
    try:
        DBIAuthorizationPolicy.require_plot(
            context, tenant_ref=context.tenant_ref,
            organization_ref=organization_ref,
            farm_id=farm_id, plot_id=plot_id, permission=DBIPermission.MANAGE,
        )
    except DBIAccessDenied as error:
        raise _hidden() from error
    campaign = DBICampaignRepository(session).get_campaign_for_update(
        campaign_id=campaign_id, tenant_ref=context.tenant_ref,
        organization_ref=organization_ref, farm_id=farm_id, plot_id=plot_id,
    )
    if (
        campaign is None
        or campaign.id != campaign_id or campaign.tenant_ref != context.tenant_ref
        or campaign.organization_ref != organization_ref
        or campaign.farm_id != farm_id or campaign.plot_id != plot_id
        or campaign.analysis_type != "multispectral"
        or campaign.status not in PRE_INTAKE_STATUSES
        or campaign.approved_at is not None or campaign.published_at is not None
    ):
        raise _hidden()


@router.post(
    "/organizations/{organization_ref}/farms/{farm_id}/plots/{plot_id}"
    "/campaigns/{campaign_id}/scientific-intake/private-raster-sql-bindings/{role}/{index}",
    response_model=ScientificRasterBindingReceipt,
)
def bind_private_raster_sql(
    organization_ref: str, farm_id: UUID, plot_id: UUID, campaign_id: UUID,
    role: RasterRole, index: str, payload: ScientificRasterBindingRequest,
    request: Request, response: Response, session: SessionDep, context: AccessDep,
) -> ScientificRasterBindingReceipt:
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    mapped_index = None if index == "_" else index
    try:
        _locked_campaign(
            session, context, organization_ref, farm_id, plot_id, campaign_id,
        )
        _role_index(role, mapped_index)
        store, manifest, manifest_record = _manifest(
            request, context, organization_ref, farm_id, plot_id, campaign_id,
        )
        if manifest_record.metadata.sha256 != payload.manifest_sha256:
            raise HTTPException(409, detail="Manifiesto científico divergente.")
        slot_address = _slot_address(
            context, organization_ref, farm_id, plot_id,
            campaign_id, role, mapped_index,
        )
        slot, slot_record = _read_slot(store, slot_address)
        if slot_record.metadata.sha256 != payload.reservation_sha256:
            raise HTTPException(409, detail="Reserva raster divergente.")
        expected = _expected(
            context=context, organization_ref=organization_ref, farm_id=farm_id,
            plot_id=plot_id, campaign_id=campaign_id,
            role=role, index=mapped_index, manifest=manifest, record=manifest_record,
        )
        if slot != expected.model_copy(update={"reserved_by": slot.reserved_by}):
            raise DBIStorageConflict("Reserva no corresponde a Campaign/manifiesto.")
        if slot.reserved_by != context.principal_ref:
            # No apropiarse del expediente inmutable de otro operador.
            raise HTTPException(409, detail="La reserva pertenece a otro operador.")
        from app.api.v1.dbi_scientific_raster_preflight import _raster_address
        target = _raster_address(
            context, organization_ref, farm_id, plot_id,
            campaign_id, role, mapped_index,
        )
        if target.object_id != slot.target_object_id:
            raise DBIStorageConflict("Dirección futura no coincide con la reserva.")
        try:
            store.stat(target)
        except DBIStorageNotFound:
            pass
        else:
            raise HTTPException(409, detail="El TIFF ya existe; no se puede vincular como pendiente.")

        intent = ScientificRasterBindingIntent(
            tenant_ref=context.tenant_ref,
            organization_ref=organization_ref, farm_id=farm_id, plot_id=plot_id,
            campaign_id=campaign_id,
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
        row, created = DBIScientificRasterBindingRepository(session).persist_binding(intent)
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except DBIStorageNotFound as error:
        session.rollback()
        raise _hidden() from error
    except ScientificRasterBindingConflict as error:
        session.rollback()
        raise HTTPException(409, detail="Vínculo científico existente divergente.") from error
    except (IntegrityError, SQLAlchemyError, DBIStorageError, ValueError, TypeError, KeyError) as error:
        session.rollback()
        raise HTTPException(503, detail="Vínculo SQL privado no disponible o inconsistente.") from error
    response.status_code = 201 if created else 200
    return ScientificRasterBindingReceipt(
        schema_version="dbi-h14-sql-raster-binding-receipt.v1",
        campaign_id=campaign_id, binding_id=row.id,
        manifest_sha256=intent.manifest_sha256,
        reservation_sha256=intent.slot_sha256,
        target_object_id=intent.target_object_id,
        role=role, index=mapped_index, created=created,
        state="reserved_no_asset",
        asset_registered=False, session_initiated=False,
        grants_issued=False, file_received=False, content_verified=False,
        institutional_approved=False, published=False,
    )
